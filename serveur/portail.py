"""Portail Scolarité — serveur applicatif.

Serveur HTTP autonome (bibliothèque standard Python 3.10+, SQLite) qui sert les
écrans HTML du portail et une API JSON : authentification, rôles étudiant / agent,
règles du workflow (acheminement, transitions, relances, transferts), notifications,
préférences, coordonnées et pièces justificatives.

    python serveur/portail.py                      démarre sur http://127.0.0.1:8766
    python serveur/portail.py --port 9000
    python serveur/portail.py compte --email x@y.fr --nom "Prénom Nom" --role agent --service centrale
    python serveur/portail.py mot-de-passe --email x@y.fr
    python serveur/portail.py reinitialiser        recrée les données de démonstration
"""
from __future__ import annotations

import argparse
import email.parser
import email.policy
import hashlib
import hmac
import http.server
import json
import mimetypes
import os
import random
import re
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('PORTAIL_DATA', Path(__file__).resolve().parent / 'donnees'))
DAY = 86_400_000
SESSION_MS = 8 * 3600 * 1000
REMEMBER_MS = 30 * 86_400_000
MAX_UPLOAD = 5 * 1024 * 1024
MAX_BODY = 12 * 1024 * 1024
UNIVERSITE = 'Université — nom à préciser'

# ── Référentiel (miroir de assets/portail.js) ─────────────────────────────
SERVICES = {
    'centrale': 'Scolarité centrale',
    'composante': 'Scolarité de la composante',
    'diplomes': 'Bureau des diplômes',
    'stages': 'Bureau des stages',
    'accueil': 'Accueil – cartes étudiantes',
}
ANNEES = ['2026-2027', '2025-2026', '2024-2025']


def F(id, label, type, **kw):
    return dict(id=id, label=label, type=type, **kw)


TYPES = {
    'attestation': dict(label='Attestation de scolarité', service='centrale', sla=2, fields=[
        F('annee', 'Année universitaire', 'select', options=ANNEES, required=True, default=ANNEES[0]),
        F('motif', 'Motif', 'radio', options=['CAF / logement', 'Bourse', 'Transports', 'Employeur', 'Autre'], required=True, default='CAF / logement'),
        F('motif_autre', 'Précisez le motif', 'text', required=True, show=lambda d: d.get('motif') == 'Autre'),
        F('format', 'Format', 'radio', options=['Numérique (PDF signé)', 'Papier'], required=True, default='Numérique (PDF signé)'),
        F('exemplaires', 'Nombre d’exemplaires', 'number', min=1, max=3, default=1, show=lambda d: d.get('format') == 'Papier'),
        F('retrait', 'Mode de remise', 'radio', options=['Retrait au guichet', 'Envoi postal'], required=True, default='Retrait au guichet', show=lambda d: d.get('format') == 'Papier'),
        F('adresse', 'Adresse postale', 'textarea', required=True, show=lambda d: d.get('format') == 'Papier' and d.get('retrait') == 'Envoi postal'),
    ]),
    'releve': dict(label='Relevé de notes', service='composante', sla=5, extra=lambda d: 2 if d.get('langue') == 'Anglais' else 0, fields=[
        F('annee', 'Année universitaire', 'select', options=ANNEES, required=True, default=ANNEES[1]),
        F('semestres', 'Semestres concernés', 'checkbox', options=['S1', 'S2', 'S3', 'S4', 'S5', 'S6'], required=True, default=[]),
        F('session', 'Session', 'radio', options=['Session 1', 'Session 2 (rattrapage)'], required=True, default='Session 1'),
        F('langue', 'Langue', 'radio', options=['Français', 'Anglais'], required=True, default='Français'),
        F('destinataire', 'Établissement destinataire', 'text', required=True, show=lambda d: d.get('langue') == 'Anglais'),
        F('cachet', 'Avec cachet et signature originale', 'switch', default=True),
    ]),
    'reussite': dict(label='Attestation de réussite', service='diplomes', sla=7, fields=[
        F('diplome', 'Diplôme', 'select', options=['Licence', 'Licence professionnelle', 'Master 1', 'Master 2', 'DUT / BUT'], required=True, default='Licence'),
        F('annee', 'Année d’obtention', 'select', options=ANNEES, required=True, default=ANNEES[1]),
        F('parcours', 'Mention / parcours', 'text', required=True),
        F('parchemin', 'Demander aussi le parchemin du diplôme', 'switch', default=False),
        F('piece', 'Pièce d’identité (recto/verso)', 'file', required=True, show=lambda d: bool(d.get('parchemin'))),
    ]),
    'convention': dict(label='Convention de stage', service='stages', sla=5, fields=[
        F('organisme', 'Organisme d’accueil', 'text', required=True),
        F('tuteur', 'Tuteur en entreprise', 'text', required=True),
        F('tuteur_email', 'E-mail du tuteur', 'email', required=True),
        F('debut', 'Date de début', 'date', required=True),
        F('fin', 'Date de fin', 'date', required=True),
        F('etranger', 'Stage à l’étranger', 'switch', default=False),
        F('pays', 'Pays', 'text', required=True, show=lambda d: bool(d.get('etranger'))),
        F('assurance', 'Attestation d’assurance rapatriement', 'file', required=True, show=lambda d: bool(d.get('etranger'))),
    ]),
    'carte': dict(label='Duplicata de carte étudiante', service='accueil', sla=3, fields=[
        F('raison', 'Raison', 'radio', options=['Perte', 'Vol', 'Carte abîmée'], required=True, default='Perte'),
        F('declaration', 'Récépissé de déclaration de vol', 'file', required=True, show=lambda d: d.get('raison') == 'Vol'),
        F('photo', 'Nouvelle photo d’identité', 'file', required=False),
    ]),
}
OPEN = ('soumise', 'en_cours', 'info_requise')
CLOSED = ('prete', 'refusee')
# Transitions proposées par le back-office (file-traitement.html).
TRANSITIONS = {
    'soumise': {'en_cours', 'info_requise', 'refusee'},
    'en_cours': {'prete', 'info_requise', 'refusee'},
    'info_requise': {'en_cours', 'refusee'},
}
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
NAME_RE = re.compile(r'^[^<>&"\'\x00-\x1f]{2,80}$')


def visible(field, data):
    return 'show' not in field or field['show'](data)


def defaults_for(type_id):
    d = {}
    for f in TYPES[type_id]['fields']:
        if 'default' in f:
            d[f['id']] = list(f['default']) if isinstance(f['default'], list) else f['default']
    return d


# ── Jours ouvrés (mêmes règles que le navigateur, heure locale du serveur) ──
def is_weekend(ts):
    return datetime.fromtimestamp(ts / 1000).weekday() >= 5


def add_business_days(ts, n):
    left = n
    while left > 0:
        ts += DAY
        if not is_weekend(ts):
            left -= 1
    return ts


def sla_of(type_id, data):
    t = TYPES[type_id]
    return t['sla'] + (t['extra'](data) if 'extra' in t else 0)


def now_ms():
    return int(time.time() * 1000)


# ── Mots de passe ──────────────────────────────────────────────────────────
def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 310_000)
    return salt.hex() + '$' + digest.hex()


def check_password(password, stored):
    if not stored or '$' not in stored:
        hashlib.pbkdf2_hmac('sha256', password.encode(), b'0' * 16, 310_000)  # temps constant
        return False
    salt, digest = stored.split('$', 1)
    other = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310_000).hex()
    return hmac.compare_digest(other, digest)


# ── Base de données ────────────────────────────────────────────────────────
SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('etudiant','agent')),
  student_no TEXT UNIQUE,
  programme TEXT,
  service TEXT,
  password TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  prefs TEXT NOT NULL DEFAULT '{"email":true,"sms":false,"push":true}',
  profile TEXT
);
CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  service TEXT NOT NULL,
  student_id INTEGER NOT NULL REFERENCES users(id),
  data TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  status TEXT NOT NULL,
  agent_id INTEGER REFERENCES users(id),
  closed_at INTEGER,
  last_reminder_at INTEGER
);
CREATE INDEX IF NOT EXISTS requests_student ON requests(student_id);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
  status TEXT,
  auto INTEGER NOT NULL DEFAULT 0,
  at INTEGER NOT NULL,
  by_name TEXT NOT NULL,
  by_id INTEGER REFERENCES users(id),
  note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS history_request ON history(request_id);
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  recipient_id INTEGER NOT NULL REFERENCES users(id),
  request_id TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
  at INTEGER NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS notifications_recipient ON notifications(recipient_id);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  request_id TEXT REFERENCES requests(id) ON DELETE CASCADE,
  field TEXT NOT NULL,
  name TEXT NOT NULL,
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  uploaded_by INTEGER NOT NULL REFERENCES users(id),
  at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  espace TEXT NOT NULL,
  expires INTEGER NOT NULL
);
'''

_lock = threading.RLock()
_conn = None


def db():
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / 'fichiers').mkdir(exist_ok=True)
        _conn = sqlite3.connect(DATA_DIR / 'portail.sqlite', check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute('PRAGMA foreign_keys = ON')
        _conn.execute('PRAGMA journal_mode = WAL')
        _conn.executescript(SCHEMA)
    return _conn


class tx:
    """Transaction exclusive : toutes les écritures d'une opération ou aucune."""
    def __enter__(self):
        _lock.acquire()
        db().execute('BEGIN IMMEDIATE')
        return db()

    def __exit__(self, exc_type, *_):
        try:
            db().execute('ROLLBACK' if exc_type else 'COMMIT')
        finally:
            _lock.release()


def meta_get(key, default=None):
    row = db().execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()
    return row['value'] if row else default


def meta_set(c, key, value):
    c.execute('INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, str(value)))


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ── Comptes et démonstration ───────────────────────────────────────────────
DEMO_STUDENT = dict(email='ines.benali@etu.universite.fr', name='Inès Benali', student_no='E21400187', programme='Licence 3 Économie-Gestion')
DEMO_STUDENT_2 = dict(email='yanis.martin@etu.universite.fr', name='Yanis Martin', student_no='E21400542', programme='Licence 2 Psychologie')
DEMO_AGENTS = [
    dict(email='samira.haddad@universite.fr', name='Samira Haddad', service='centrale'),
    dict(email='julien.durand@universite.fr', name='Julien Durand', service='composante'),
    dict(email='claire.lefevre@universite.fr', name='Claire Lefèvre', service='diplomes'),
    dict(email='moussa.ndiaye@universite.fr', name='Moussa Ndiaye', service='stages'),
]
STUDENTS = ['Léa Dubois', 'Omar El Idrissi', 'Chloé Bernard', 'Hugo Petit', 'Aya Benjelloun', 'Lucas Moreau', 'Sarah Cohen', 'Nathan Girard', 'Fatou Diallo', 'Emma Roux', 'Karim Mansouri', 'Manon Fournier', 'Théo Lambert', 'Zoé Garnier', 'Rayan Haddou', 'Camille Faure', 'Adam Chevalier']
PROGRAMMES = ['Licence 1 Droit', 'Licence 2 Psychologie', 'Licence 3 Économie-Gestion', 'Master 1 Finance', 'Master 2 Data Science', 'BUT GEA 2']


def slug(name):
    table = str.maketrans('àâäéèêëîïôöùûüçÉÈÎÏÔÖ', 'aaaeeeeiioouuucEEIIOO')
    return re.sub(r'[^a-z]+', '.', name.translate(table).lower()).strip('.')


def upsert_user(c, email, name, role, password=None, student_no=None, programme=None, service=None):
    row = c.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    pw = hash_password(password) if password else None
    if row:
        c.execute('UPDATE users SET name=?, role=?, student_no=?, programme=?, service=?, password=COALESCE(?, password), active=1 WHERE id=?',
                  (name, role, student_no, programme, service, pw, row['id']))
        return row['id']
    return c.execute('INSERT INTO users(email, name, role, student_no, programme, service, password) VALUES(?,?,?,?,?,?,?)',
                     (email, name, role, student_no, programme, service, pw)).lastrowid


def create_demo_accounts(c):
    """Crée les comptes de démonstration ; renvoie les identifiants en clair (une seule fois)."""
    lines = []
    for spec, role in [(DEMO_STUDENT, 'etudiant'), (DEMO_STUDENT_2, 'etudiant')] + [(a, 'agent') for a in DEMO_AGENTS]:
        pw = secrets.token_urlsafe(9)
        upsert_user(c, spec['email'], spec['name'], role, pw, spec.get('student_no'), spec.get('programme'), spec.get('service'))
        lines.append(f"{'Étudiant·e' if role == 'etudiant' else 'Agent':12} {spec['email']:34} {pw}")
    r = random.Random(7)
    for name in STUDENTS:
        # Étudiants des données d'exemple : pas de mot de passe, connexion impossible.
        upsert_user(c, slug(name) + '@etu.universite.fr', name, 'etudiant', None,
                    'E2' + str(10_000_000 + r.randrange(90_000_000)), r.choice(PROGRAMMES))
    return lines


def seed_requests(c):
    """Jeu de données de démonstration (même scénario que l'ancien prototype navigateur)."""
    c.execute('DELETE FROM notifications'); c.execute('DELETE FROM history'); c.execute('DELETE FROM files'); c.execute('DELETE FROM requests')
    for f in (DATA_DIR / 'fichiers').glob('*'):
        f.unlink(missing_ok=True)
    r = random.Random(20261015)
    now = now_ms()
    agents = {row['name']: row['id'] for row in c.execute("SELECT id, name FROM users WHERE role='agent'")}
    agent_names = [a['name'] for a in DEMO_AGENTS if a['name'] in agents] or list(agents)
    others = [dict(row) for row in c.execute("SELECT id, name FROM users WHERE role='etudiant' AND password IS NULL")]
    seq = 300
    weights = [('attestation', .32), ('releve', .24), ('convention', .18), ('reussite', .14), ('carte', .12)]

    def pick_type():
        x, acc = r.random(), 0
        for tid, w in weights:
            acc += w
            if x <= acc:
                return tid
        return 'attestation'

    def demo_data(tid):
        d = defaults_for(tid)
        if tid == 'releve':
            d['semestres'] = ['S3', 'S4'] if r.random() > .5 else ['S5']
        if tid == 'reussite':
            d['parcours'] = 'Économie-Gestion, parcours Finance'
        if tid == 'convention':
            d.update(organisme=r.choice(['Crédit Agricole', 'Decathlon', 'Mairie de Lyon', 'Capgemini', 'Clinique du Parc']), tuteur='M. Leroy',
                     tuteur_email='tuteur@organisme.fr', debut='2027-02-01', fin='2027-06-30')
        return d

    def insert(tid, student, data, created, status, agent, closed, hist):
        nonlocal seq
        seq += 1
        rid = f'DEM-{datetime.fromtimestamp(now / 1000).year}-{seq:04d}'
        c.execute('INSERT INTO requests(id, type, service, student_id, data, created_at, status, agent_id, closed_at) VALUES(?,?,?,?,?,?,?,?,?)',
                  (rid, tid, TYPES[tid]['service'], student['id'], json.dumps(data, ensure_ascii=False), created, status, agents.get(agent), closed))
        hist = [('soumise', 0, created, student['name'], '')] + \
               [(None, 1, created + 60000, 'Flux automatique', f"Acheminée vers {SERVICES[TYPES[tid]['service']]} · délai cible {sla_of(tid, data)} j ouvrés")] + hist
        for st, auto, at, by, note in hist:
            c.execute('INSERT INTO history(request_id, status, auto, at, by_name, by_id, note) VALUES(?,?,?,?,?,?,?)', (rid, st, auto, at, by, agents.get(by), note))
        return rid

    for _ in range(64):
        tid = pick_type()
        sla = sla_of(tid, defaults_for(tid))
        age = int(r.random() * 84 * r.random() + r.random() * 6)
        created = now - age * DAY - int(r.random() * 8) * 3_600_000
        student = r.choice(others) if others else None
        if not student:
            break
        data = demo_data(tid)
        sla = sla_of(tid, data)
        agent = r.choice(agent_names)
        take_at = min(now - 3_600_000, add_business_days(created, 1) - int(r.random() * 20) * 3_600_000)
        hist, status, closed, assigned = [], 'soumise', None, None
        if age > 16:
            proc = max(1, round(sla * (0.3 + r.random() * 1.2)))
            closed = min(now - DAY, add_business_days(created, proc))
            assigned = agent
            hist.append(('en_cours', 0, min(take_at, closed - 3_600_000), agent, ''))
            refused = r.random() < .1
            status = 'refusee' if refused else 'prete'
            hist.append((status, 0, closed, agent, 'Dossier incomplet : pièce justificative manquante.' if refused else ''))
        elif age > 2:
            x = r.random()
            assigned = agent
            hist.append(('en_cours', 0, take_at, agent, ''))
            if x < .18:
                status = 'info_requise'
                hist.append(('info_requise', 0, take_at + 5 * 3_600_000, agent, 'Merci de joindre la pièce justificative demandée.'))
            elif x < .45:
                status = 'prete'
                closed = min(now - 3_600_000, add_business_days(created, max(1, round(sla * (.5 + r.random())))))
                hist.append(('prete', 0, closed, agent, ''))
            else:
                status = 'en_cours'
        elif r.random() < .45 and age >= 1:
            assigned, status = agent, 'en_cours'
            hist.append(('en_cours', 0, take_at, agent, ''))
        insert(tid, student, data, created, status, assigned, closed, hist)

    me = c.execute('SELECT id, name FROM users WHERE email = ?', (DEMO_STUDENT['email'],)).fetchone()
    if not me:
        return

    def notif(rid, at, kind, title, body, read):
        c.execute('INSERT INTO notifications(id, recipient_id, request_id, at, kind, title, body, read) VALUES(?,?,?,?,?,?,?,?)',
                  (uuid.uuid4().hex[:12], me['id'], rid, at, kind, title, body, int(read)))

    def mine(tid, age_days, steps, extra):
        created = now - age_days * DAY - 3 * 3_600_000
        data = {**defaults_for(tid), **extra}
        hist, status, agent, closed = [], 'soumise', None, None
        for st, hours, by, *note in steps:
            at = created + hours * 3_600_000
            hist.append((st, 0, at, by, note[0] if note else ''))
            status = st
            if st == 'en_cours':
                agent = by
            if st in CLOSED:
                closed = at
        rid = insert(tid, dict(me), data, created, status, agent, closed, hist)
        return rid, created, hist

    a, ac, ah = mine('attestation', 9, [('en_cours', 20, 'Samira Haddad'), ('prete', 26, 'Samira Haddad', 'Votre attestation signée est disponible en téléchargement.')], {'motif': 'CAF / logement'})
    b, bc, bh = mine('reussite', 21, [('en_cours', 30, 'Claire Lefèvre'), ('refusee', 52, 'Claire Lefèvre', 'Les résultats de la Licence 3 ne sont pas encore délibérés. Vous pourrez redéposer la demande après le jury du 2 juillet.')], {'diplome': 'Licence', 'parcours': 'Économie-Gestion'})
    cc_, ccc, chh = mine('releve', 4, [('en_cours', 22, 'Julien Durand'), ('info_requise', 30, 'Julien Durand', 'Souhaitez-vous le relevé de la session 1 ou celui intégrant le rattrapage du S5 ? Merci de préciser.')], {'semestres': ['S5'], 'annee': ANNEES[1]})
    d, dc, dh = mine('convention', 2, [('en_cours', 18, 'Moussa Ndiaye')], {'organisme': 'Banque Populaire Auvergne-Rhône-Alpes', 'tuteur': 'Mme Garcia', 'tuteur_email': 'l.garcia@bpaura.fr', 'debut': '2027-01-11', 'fin': '2027-04-30'})
    notif(b, bc + 60000, 'soumise', 'Demande reçue', 'Votre demande d’attestation de réussite a été transmise au Bureau des diplômes.', True)
    notif(b, bh[-1][2], 'refusee', 'Demande refusée', 'Attestation de réussite : ' + bh[-1][4], True)
    notif(a, ac + 60000, 'soumise', 'Demande reçue', 'Votre demande d’attestation de scolarité a été transmise à la Scolarité centrale.', True)
    notif(a, ah[-1][2], 'prete', 'Document prêt', 'Votre attestation de scolarité est disponible en téléchargement.', True)
    notif(cc_, ccc + 60000, 'soumise', 'Demande reçue', 'Votre demande de relevé de notes a été transmise à la Scolarité de la composante.', True)
    notif(cc_, chh[-1][2], 'info_requise', 'Information complémentaire requise', 'Relevé de notes : ' + chh[-1][4], False)
    notif(d, dc + 60000, 'soumise', 'Demande reçue', 'Votre convention de stage a été transmise au Bureau des stages.', True)
    notif(d, dh[-1][2], 'en_cours', 'Prise en charge', 'Moussa Ndiaye (Bureau des stages) traite votre convention de stage.', False)
    meta_set(c, 'seq', seq)


def initialise(demo=True):
    """Premier démarrage : comptes et (facultativement) données de démonstration."""
    if meta_get('initialised'):
        return None
    with tx() as c:
        lines = create_demo_accounts(c) if demo else []
        if demo:
            seed_requests(c)
        meta_set(c, 'demo', '1' if demo else '0')
        meta_set(c, 'initialised', now_ms())
    if lines:
        path = DATA_DIR / 'comptes-demo.txt'
        path.write_text('Portail Scolarité — comptes de démonstration (mots de passe générés au premier démarrage)\n'
                        'Ne publiez pas ce fichier. Changez un mot de passe : python serveur/portail.py mot-de-passe --email ...\n\n'
                        + '\n'.join(lines) + '\n', encoding='utf-8')
    return lines


# ── Sérialisation vers le format attendu par assets/portail.js ────────────
def initials(name):
    parts = [p for p in re.split(r'[\s\-]+', name) if p]
    return ((parts[0][0] if parts else '') + (parts[-1][0] if len(parts) > 1 else '')).upper()


def serialize_requests(where, params, viewer_role):
    c = db()
    rows = c.execute(f'''SELECT r.*, s.name AS s_name, s.student_no AS s_no, s.programme AS s_prog, a.name AS a_name
                         FROM requests r JOIN users s ON s.id = r.student_id LEFT JOIN users a ON a.id = r.agent_id
                         WHERE {where}''', params).fetchall()
    if not rows:
        return []
    ids = [r['id'] for r in rows]
    marks = ','.join('?' * len(ids))
    hist, files = {}, {}
    for h in c.execute(f'SELECT * FROM history WHERE request_id IN ({marks}) ORDER BY at, id', ids):
        item = {'at': h['at'], 'by': h['by_name'], 'note': h['note']}
        if h['auto']:
            item['auto'] = True
        if h['status']:
            item['status'] = h['status']
        hist.setdefault(h['request_id'], []).append(item)
    for f in c.execute(f'SELECT id, request_id, field, name, size FROM files WHERE request_id IN ({marks}) ORDER BY at', ids):
        files.setdefault(f['request_id'], []).append({'id': f['id'], 'field': f['field'], 'name': f['name'], 'size': f['size']})
    out = []
    for r in rows:
        out.append({
            'id': r['id'], 'type': r['type'], 'service': r['service'],
            'student': {'id': r['s_no'], 'name': r['s_name'], 'programme': r['s_prog'] or ''},
            'data': json.loads(r['data']), 'createdAt': r['created_at'], 'status': r['status'],
            'agent': r['a_name'], 'closedAt': r['closed_at'], 'lastReminderAt': r['last_reminder_at'],
            'history': hist.get(r['id'], []), 'files': files.get(r['id'], []),
        })
    return out


def state_for(user):
    c = db()
    agents = [row['name'] for row in c.execute("SELECT name FROM users WHERE role='agent' AND active=1 ORDER BY name")]
    base = {'version': 1, 'role': user['role'], 'demo': meta_get('demo') == '1', 'agents': agents}
    if user['role'] == 'etudiant':
        prefs = json.loads(user['prefs'])
        base.update(
            me={'id': user['student_no'], 'name': user['name'], 'initials': initials(user['name']), 'programme': user['programme'] or '', 'email': user['email']},
            requests=serialize_requests('r.student_id = ?', (user['id'],), 'etudiant'),
            notifications=[{'id': n['id'], 'reqId': n['request_id'], 'at': n['at'], 'kind': n['kind'], 'title': n['title'], 'body': n['body'], 'read': bool(n['read'])}
                           for n in c.execute('SELECT * FROM notifications WHERE recipient_id = ? ORDER BY at', (user['id'],))],
            prefs=prefs, profile=json.loads(user['profile']) if user['profile'] else None)
    else:
        base.update(
            agent={'name': user['name'], 'initials': initials(user['name']), 'service': SERVICES.get(user['service'], 'Scolarité')},
            requests=serialize_requests('1 = 1', (), 'agent'),
            notifications=[], prefs={}, profile=None)
    return base


# ── Règles métier ──────────────────────────────────────────────────────────
def fmt_date(ts):
    mois = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']
    d = datetime.fromtimestamp(ts / 1000)
    return f'{d.day} {mois[d.month - 1]} {d.year}'


def notify(c, request_id, student_id, kind, title, body, at=None):
    c.execute('INSERT INTO notifications(id, recipient_id, request_id, at, kind, title, body) VALUES(?,?,?,?,?,?,?)',
              (uuid.uuid4().hex[:12], student_id, request_id, at or now_ms(), kind, title, body))


def add_history(c, rid, status, at, by_name, by_id, note='', auto=False):
    c.execute('INSERT INTO history(request_id, status, auto, at, by_name, by_id, note) VALUES(?,?,?,?,?,?,?)',
              (rid, status, int(auto), at, by_name, by_id, note or ''))


def clean_text(value, limit, label):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ApiError(400, f'{label} : valeur invalide.')
    value = value.strip()
    if len(value) > limit:
        raise ApiError(400, f'{label} : {limit} caractères maximum.')
    return value


def validate_request_data(type_id, raw, uploaded_fields):
    if type_id not in TYPES:
        raise ApiError(400, 'Type de document inconnu.')
    if not isinstance(raw, dict):
        raise ApiError(400, 'Données invalides.')
    t = TYPES[type_id]
    data = {}
    # Visibilité calculée sur les valeurs brutes, comme dans le formulaire.
    for f in t['fields']:
        if not visible(f, raw):
            continue
        k, v, kind = f['id'], raw.get(f['id']), f['type']
        empty = v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v)
        if kind == 'file':
            if k in uploaded_fields:
                data[k] = uploaded_fields[k]
            elif f.get('required'):
                raise ApiError(400, f'{f["label"]} : ce justificatif est obligatoire.')
            continue
        if empty:
            if f.get('required'):
                raise ApiError(400, f'{f["label"]} : ce champ est obligatoire.')
            if kind == 'switch':
                data[k] = False
            continue
        if kind in ('select', 'radio'):
            if v not in f['options']:
                raise ApiError(400, f'{f["label"]} : valeur non autorisée.')
        elif kind == 'checkbox':
            if not isinstance(v, list) or any(x not in f['options'] for x in v):
                raise ApiError(400, f'{f["label"]} : valeur non autorisée.')
            v = [o for o in f['options'] if o in v]
        elif kind == 'switch':
            v = bool(v)
        elif kind == 'number':
            if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not f['min'] <= v <= f['max']:
                raise ApiError(400, f'{f["label"]} : entier entre {f["min"]} et {f["max"]}.')
            v = int(v)
        elif kind == 'email':
            v = clean_text(v, 254, f['label'])
            if not EMAIL_RE.match(v):
                raise ApiError(400, f'{f["label"]} : adresse e-mail invalide.')
        elif kind == 'date':
            try:
                date.fromisoformat(v)
            except (TypeError, ValueError):
                raise ApiError(400, f'{f["label"]} : date invalide.')
        else:
            v = clean_text(v, 1000 if kind == 'textarea' else 200, f['label'])
        data[k] = v
    if data.get('debut') and data.get('fin') and data['fin'] <= data['debut']:
        raise ApiError(400, 'La date de fin doit suivre la date de début.')
    comment = clean_text(raw.get('commentaire'), 1000, 'Commentaire')
    if comment:
        data['commentaire'] = comment
    return data


ALLOWED_MIME = {'application/pdf': b'%PDF', 'image/png': b'\x89PNG', 'image/jpeg': b'\xff\xd8\xff'}


def store_upload(c, part, user_id, field, rid=None):
    content = part['content']
    if not content:
        return None
    if len(content) > MAX_UPLOAD:
        raise ApiError(413, f'« {part["filename"]} » dépasse 5 Mo.')
    mime = next((m for m, sig in ALLOWED_MIME.items() if content.startswith(sig)), None)
    if not mime:
        raise ApiError(415, f'« {part["filename"]} » : formats acceptés PDF, JPEG ou PNG.')
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', '_', Path(part['filename'] or 'fichier').name)[:120] or 'fichier'
    fid = uuid.uuid4().hex
    (DATA_DIR / 'fichiers' / fid).write_bytes(content)
    c.execute('INSERT INTO files(id, request_id, field, name, mime, size, uploaded_by, at) VALUES(?,?,?,?,?,?,?,?)',
              (fid, rid, field, name, mime, len(content), user_id, now_ms()))
    return name, fid


def create_request(user, payload, uploads):
    type_id = payload.get('type')
    raw = payload.get('data') or {}
    if type_id not in TYPES:
        raise ApiError(400, 'Type de document inconnu.')
    file_fields = {f['id'] for f in TYPES[type_id]['fields'] if f['type'] == 'file' and visible(f, raw)}
    with tx() as c:
        stored = []
        names = {}
        for field, part in uploads.items():
            if field in file_fields:
                res = store_upload(c, part, user['id'], field)
                if res:
                    names[field] = res[0]
                    stored.append(res[1])
        data = validate_request_data(type_id, raw, names)
        now = now_ms()
        seq = int(meta_get('seq', '300')) + 1
        meta_set(c, 'seq', seq)
        rid = f'DEM-{datetime.fromtimestamp(now / 1000).year}-{seq:04d}'
        t = TYPES[type_id]
        c.execute('INSERT INTO requests(id, type, service, student_id, data, created_at, status) VALUES(?,?,?,?,?,?,?)',
                  (rid, type_id, t['service'], user['id'], json.dumps(data, ensure_ascii=False), now, 'soumise'))
        for fid in stored:
            c.execute('UPDATE files SET request_id = ? WHERE id = ?', (rid, fid))
        sla = sla_of(type_id, data)
        add_history(c, rid, 'soumise', now, user['name'], user['id'])
        add_history(c, rid, None, now + 1000, 'Flux automatique', None, f'Acheminée vers {SERVICES[t["service"]]} · délai cible {sla} j ouvrés', auto=True)
        notify(c, rid, user['id'], 'soumise', 'Demande reçue',
               f'{t["label"]} : transmise à {SERVICES[t["service"]]}. Disponibilité estimée le {fmt_date(add_business_days(now, sla))}.', now)
    return rid


def load_request(c, rid):
    r = c.execute('SELECT r.*, a.name AS a_name FROM requests r LEFT JOIN users a ON a.id = r.agent_id WHERE r.id = ?', (rid,)).fetchone()
    if not r:
        raise ApiError(404, 'Demande introuvable.')
    return r


def transition(user, rid, payload):
    status = payload.get('status')
    note = clean_text(payload.get('note'), 1000, 'Message')
    with tx() as c:
        r = load_request(c, rid)
        expected = payload.get('from')
        if expected and expected != r['status']:
            raise ApiError(409, 'Cette demande a été modifiée entre-temps. L’affichage a été actualisé.')
        if status not in TRANSITIONS.get(r['status'], set()):
            raise ApiError(409, 'Ce changement de statut n’est pas possible depuis « ' + r['status'] + ' ».')
        if status in ('info_requise', 'refusee') and not note:
            raise ApiError(400, 'Un message est obligatoire.')
        now = now_ms()
        agent_id = r['agent_id'] or user['id']
        agent_name = r['a_name'] or user['name']
        closed = now if status in CLOSED else None
        c.execute('UPDATE requests SET status=?, agent_id=?, closed_at=? WHERE id=?', (status, agent_id, closed, rid))
        add_history(c, rid, status, now, user['name'], user['id'], note)
        label = TYPES[r['type']]['label']
        title, body = {
            'en_cours': ('Prise en charge', f'{agent_name} ({SERVICES[r["service"]]}) traite votre demande : {label.lower()}.'),
            'info_requise': ('Information complémentaire requise', f'{label} : {note}'),
            'prete': ('Document prêt', f'{label} disponible. {note}'.strip()),
            'refusee': ('Demande refusée', f'{label} : {note}'),
        }[status]
        notify(c, rid, r['student_id'], status, title, body, now)


def remind(user, rid):
    with tx() as c:
        r = load_request(c, rid)
        if r['status'] != 'info_requise':
            raise ApiError(409, 'Aucun complément n’est attendu pour cette demande.')
        now = now_ms()
        if r['last_reminder_at'] and now - r['last_reminder_at'] < DAY:
            return False
        ask = c.execute("SELECT note FROM history WHERE request_id=? AND status='info_requise' ORDER BY at DESC, id DESC LIMIT 1", (rid,)).fetchone()
        note = ask['note'] if ask else ''
        c.execute('UPDATE requests SET last_reminder_at=? WHERE id=?', (now, rid))
        add_history(c, rid, None, now, user['name'], user['id'], 'Relance du complément : ' + note, auto=True)
        notify(c, rid, r['student_id'], 'info_requise', 'Rappel : votre réponse est attendue', note, now)
    return True


def transfer(user, rid, service):
    with tx() as c:
        r = load_request(c, rid)
        if r['status'] not in OPEN or service not in SERVICES or service == r['service']:
            raise ApiError(409, 'Transfert impossible pour cette demande.')
        now = now_ms()
        c.execute("UPDATE requests SET service=?, agent_id=NULL, status='soumise' WHERE id=?", (service, rid))
        add_history(c, rid, None, now, user['name'], user['id'], f'Transfert vers {SERVICES[service]}. Le délai initial est conservé.', auto=True)
        notify(c, rid, r['student_id'], 'soumise', 'Votre demande change de service', f'{TYPES[r["type"]]["label"]} : transmise à {SERVICES[service]}.', now)


def answer_info(user, rid, text, upload):
    text = clean_text(text, 2000, 'Réponse')
    if not text:
        raise ApiError(400, 'Merci de saisir une réponse.')
    with tx() as c:
        r = load_request(c, rid)
        if r['student_id'] != user['id']:
            raise ApiError(404, 'Demande introuvable.')
        if r['status'] != 'info_requise':
            raise ApiError(409, 'Aucun complément n’est attendu pour cette demande.')
        res = store_upload(c, upload, user['id'], 'complement', rid) if upload else None
        now = now_ms()
        add_history(c, rid, 'complement', now, user['name'], user['id'], text + (f' · Pièce jointe : {res[0]}' if res else ''))
        c.execute("UPDATE requests SET status='en_cours' WHERE id=?", (rid,))
        add_history(c, rid, None, now + 1000, 'Flux automatique', None,
                    'Complément reçu : demande renvoyée à ' + (r['a_name'] or SERVICES[r['service']]), auto=True)


def update_me(user, payload):
    with tx() as c:
        if isinstance(payload.get('read'), list):
            ids = [str(x) for x in payload['read']][:1000]
            if ids:
                c.execute(f'UPDATE notifications SET read=1 WHERE recipient_id=? AND id IN ({",".join("?" * len(ids))})', (user['id'], *ids))
        if isinstance(payload.get('prefs'), dict):
            prefs = json.loads(user['prefs'])
            for k in ('email', 'sms', 'push'):
                if k in payload['prefs']:
                    prefs[k] = bool(payload['prefs'][k])
            c.execute('UPDATE users SET prefs=? WHERE id=?', (json.dumps(prefs), user['id']))
        if isinstance(payload.get('profile'), dict):
            p = payload['profile']
            tel = clean_text(p.get('tel'), 30, 'Téléphone')
            mail2 = clean_text(p.get('mail2'), 254, 'E-mail personnel')
            adr = clean_text(p.get('adr'), 240, 'Adresse postale')
            if tel and not re.match(r'^(?:\+\d{8,14}|0\d{9})$', re.sub(r'[\s.\-]', '', tel)):
                raise ApiError(400, 'Numéro de téléphone non reconnu.')
            if mail2 and not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$', mail2):
                raise ApiError(400, 'Adresse e-mail personnelle invalide.')
            c.execute('UPDATE users SET profile=? WHERE id=?', (json.dumps({'tel': tel, 'mail2': mail2, 'adr': adr, 'at': now_ms()}, ensure_ascii=False), user['id']))


# ── Sessions ───────────────────────────────────────────────────────────────
COOKIE = {'etudiant': 'ps_etudiant', 'agent': 'ps_agent'}
_attempts = {}


def new_session(user_id, espace, duration=SESSION_MS):
    token = secrets.token_urlsafe(32)
    with tx() as c:
        c.execute('DELETE FROM sessions WHERE expires < ?', (now_ms(),))
        c.execute('INSERT INTO sessions(token_hash, user_id, espace, expires) VALUES(?,?,?,?)',
                  (hashlib.sha256(token.encode()).hexdigest(), user_id, espace, now_ms() + duration))
    return token


def session_user(token, espace):
    if not token:
        return None
    row = db().execute('''SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                          WHERE s.token_hash = ? AND s.espace = ? AND s.expires > ? AND u.active = 1''',
                       (hashlib.sha256(token.encode()).hexdigest(), espace, now_ms())).fetchone()
    return row if row and row['role'] == espace else None


def throttled(key):
    now = time.time()
    hits = [t for t in _attempts.get(key, []) if now - t < 600]
    _attempts[key] = hits
    return len(hits) >= 5


# ── HTTP ───────────────────────────────────────────────────────────────────
PUBLIC_PAGES = {'index.html', 'connexion.html'}
STUDENT_PAGES = {'nouvelle-demande.html', 'mes-demandes.html', 'notifications.html', 'profil.html'}
AGENT_PAGES = {'file-traitement.html', 'tableau-de-bord.html', 'statistiques.html'}
ASSETS = {'assets/portail.css', 'assets/portail.js', 'assets/logo-ensa-khouribga.png', 'assets/ensa-batiment.jpg'}


def parse_multipart(content_type, body):
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b'Content-Type: ' + content_type.encode('latin-1') + b'\r\n\r\n' + body)
    if not msg.is_multipart():
        raise ApiError(400, 'Envoi de formulaire invalide.')
    fields, files = {}, {}
    for part in msg.iter_parts():
        name = part.get_param('name', header='content-disposition')
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b''
        if filename is not None:
            files[name] = {'filename': filename, 'content': payload}
        else:
            fields[name] = payload.decode('utf-8', 'replace')
    return fields, files


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'PortailScolarite'
    sys_version = ''

    def log_message(self, fmt, *args):
        sys.stderr.write('%s %s\n' % (self.log_date_time_string(), fmt % args))

    # Réponses
    def send(self, status, body=b'', ctype='application/json; charset=utf-8', headers=None):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Cache-Control', 'no-store')
        for k, v in (headers or {}).items():
            if isinstance(v, list):
                for item in v:
                    self.send_header(k, item)
            else:
                self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def json(self, status, obj, headers=None):
        self.send(status, json.dumps(obj, ensure_ascii=False).encode(), headers=headers)

    def error(self, status, message):
        self.json(status, {'error': message})

    def cookies(self):
        out = {}
        for part in (self.headers.get('Cookie') or '').split(';'):
            if '=' in part:
                k, v = part.strip().split('=', 1)
                out[k] = v
        return out

    def user_for(self, espace):
        return session_user(self.cookies().get(COOKIE[espace]), espace)

    # Routage
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            url = urlparse(self.path)
            path = url.path.lstrip('/') or 'index.html'
            if path.startswith('api/'):
                return self.api('GET', path[4:], url)
            return self.static(path, url)
        except ApiError as e:
            self.error(e.status, e.message)
        except Exception:
            import traceback; traceback.print_exc()
            self.error(500, 'Erreur interne du serveur.')

    def do_POST(self):
        try:
            url = urlparse(self.path)
            path = url.path.lstrip('/')
            if not path.startswith('api/'):
                return self.error(404, 'Introuvable.')
            # Protection CSRF : en-tête personnalisé (impossible en cross-origin sans pré-vol) + Origin.
            origin = self.headers.get('Origin')
            host = self.headers.get('Host', '')
            if origin and urlparse(origin).netloc != host:
                return self.error(403, 'Origine refusée.')
            if self.headers.get('X-Espace') not in COOKIE:
                return self.error(403, 'En-tête X-Espace manquant.')
            return self.api('POST', path[4:], url)
        except ApiError as e:
            self.error(e.status, e.message)
        except Exception:
            import traceback; traceback.print_exc()
            self.error(500, 'Erreur interne du serveur.')

    def read_body(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_BODY:
            raise ApiError(413, 'Envoi trop volumineux.')
        body = self.rfile.read(length) if length else b''
        ctype = self.headers.get('Content-Type', '')
        if ctype.startswith('multipart/form-data'):
            fields, files = parse_multipart(ctype, body)
            try:
                payload = json.loads(fields.get('payload') or '{}')
            except ValueError:
                raise ApiError(400, 'Données invalides.')
            return payload, files
        try:
            return (json.loads(body) if body else {}), {}
        except ValueError:
            raise ApiError(400, 'JSON invalide.')

    def static(self, path, url):
        if path in STUDENT_PAGES or path in AGENT_PAGES:
            espace = 'etudiant' if path in STUDENT_PAGES else 'agent'
            if not self.user_for(espace):
                target = 'connexion.html?espace=' + espace + '&suite=' + quote('/' + path + (('?' + url.query) if url.query else ''), safe='')
                return self.send(302, b'', headers={'Location': '/' + target})
        elif path not in PUBLIC_PAGES and path not in ASSETS:
            return self.send(404, 'Page introuvable.'.encode(), 'text/plain; charset=utf-8')
        file = ROOT / path
        if not file.is_file():
            return self.send(404, 'Page introuvable.'.encode(), 'text/plain; charset=utf-8')
        ctype = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype.endswith('javascript'):
            ctype += '; charset=utf-8'
        self.send(200, file.read_bytes(), ctype, headers={
            'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'"})

    def api(self, method, route, url):
        espace = self.headers.get('X-Espace') or parse_qs(url.query).get('espace', [''])[0]
        if route == 'session' and method == 'POST':
            return self.login()
        if route == 'logout' and method == 'POST':
            return self.logout()
        if espace not in COOKIE:
            raise ApiError(400, 'Espace non précisé.')
        user = self.user_for(espace)
        if not user:
            raise ApiError(401, 'Session expirée : reconnectez-vous.')

        if method == 'GET' and route == 'state':
            body = json.dumps(state_for(user), ensure_ascii=False).encode()
            etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
            if self.headers.get('If-None-Match') == etag:
                return self.send(304, headers={'ETag': etag})
            return self.send(200, body, headers={'ETag': etag})

        m = re.fullmatch(r'fichiers/([0-9a-f]{32})', route)
        if method == 'GET' and m:
            return self.download(user, m.group(1))

        if method != 'POST':
            raise ApiError(404, 'Introuvable.')
        payload, files = self.read_body()
        result = None
        if route == 'demandes' and user['role'] == 'etudiant':
            result = {'id': create_request(user, payload, files)}
        elif (m := re.fullmatch(r'demandes/([A-Z0-9\-]{1,30})/(\w+)', route)):
            rid, action = m.groups()
            if action == 'complement' and user['role'] == 'etudiant':
                answer_info(user, rid, payload.get('text'), files.get('fichier'))
            elif user['role'] != 'agent':
                raise ApiError(403, 'Action réservée aux agents de la scolarité.')
            elif action == 'statut':
                transition(user, rid, payload)
            elif action == 'relance':
                result = {'ok': remind(user, rid)}
            elif action == 'transfert':
                transfer(user, rid, payload.get('service'))
            else:
                raise ApiError(404, 'Action inconnue.')
        elif route == 'moi' and user['role'] == 'etudiant':
            update_me(user, payload)
        elif route == 'demo/reinitialiser':
            if user['role'] != 'agent':
                raise ApiError(403, 'Réservé aux agents de la scolarité.')
            if meta_get('demo') != '1':
                raise ApiError(403, 'La réinitialisation est désactivée sur cette installation.')
            with tx() as c:
                seed_requests(c)
        else:
            raise ApiError(403 if route in ('demandes', 'moi') else 404, 'Action non autorisée.')
        fresh = db().execute('SELECT * FROM users WHERE id = ?', (user['id'],)).fetchone()
        self.json(200, {'result': result, 'state': state_for(fresh)})

    def download(self, user, fid):
        f = db().execute('SELECT f.*, r.student_id FROM files f JOIN requests r ON r.id = f.request_id WHERE f.id = ?', (fid,)).fetchone()
        if not f or (user['role'] != 'agent' and f['student_id'] != user['id']):
            raise ApiError(404, 'Fichier introuvable.')
        path = DATA_DIR / 'fichiers' / fid
        if not path.is_file():
            raise ApiError(404, 'Fichier introuvable.')
        self.send(200, path.read_bytes(), f['mime'], headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(f['name']),
            'Content-Security-Policy': "default-src 'none'; sandbox"})

    def login(self):
        payload, _ = self.read_body()
        email_ = clean_text(payload.get('email'), 254, 'E-mail').lower()
        password = payload.get('password') if isinstance(payload.get('password'), str) else ''
        espace = payload.get('espace')
        if espace not in COOKIE:
            raise ApiError(400, 'Espace inconnu.')
        key = self.client_address[0] + '|' + email_
        if throttled(key):
            raise ApiError(429, 'Trop de tentatives. Réessayez dans quelques minutes.')
        user = db().execute('SELECT * FROM users WHERE email = ? AND active = 1', (email_,)).fetchone()
        if not check_password(password[:200], user['password'] if user else None):
            _attempts.setdefault(key, []).append(time.time())
            raise ApiError(401, 'Adresse e-mail ou mot de passe incorrect.')
        if user['role'] != espace:
            raise ApiError(403, 'Ce compte donne accès à ' + ('l’espace étudiant.' if user['role'] == 'etudiant' else 'l’espace scolarité (back-office).'))
        _attempts.pop(key, None)
        # « Se souvenir de moi » : 30 jours ; sinon cookie de session (8 h maximum côté serveur).
        remember = payload.get('remember') is True
        token = new_session(user['id'], espace, REMEMBER_MS if remember else SESSION_MS)
        cookie = f'{COOKIE[espace]}={token}; Path=/; HttpOnly; SameSite=Strict' + (f'; Max-Age={REMEMBER_MS // 1000}' if remember else '')
        if self.server.secure_cookies:
            cookie += '; Secure'
        self.json(200, {'ok': True}, headers={'Set-Cookie': cookie})

    def logout(self):
        espace = self.headers.get('X-Espace')
        if espace in COOKIE:
            token = self.cookies().get(COOKIE[espace])
            if token:
                with tx() as c:
                    c.execute('DELETE FROM sessions WHERE token_hash = ?', (hashlib.sha256(token.encode()).hexdigest(),))
        self.json(200, {'ok': True}, headers={'Set-Cookie': f'{COOKIE.get(espace, "ps_x")}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'})


# ── Ligne de commande ──────────────────────────────────────────────────────
def main(argv=None):
    p = argparse.ArgumentParser(description='Portail Scolarité — serveur')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--sans-demo', action='store_true', help='premier démarrage sans comptes ni données de démonstration')
    p.add_argument('--cookies-secure', action='store_true', help='à activer derrière un proxy HTTPS')
    sub = p.add_subparsers(dest='cmd')
    a = sub.add_parser('compte', help='créer ou modifier un compte')
    a.add_argument('--email', required=True); a.add_argument('--nom', required=True)
    a.add_argument('--role', choices=['etudiant', 'agent'], required=True)
    a.add_argument('--numero', help='numéro étudiant'); a.add_argument('--formation')
    a.add_argument('--service', choices=list(SERVICES))
    m = sub.add_parser('mot-de-passe', help='définir un nouveau mot de passe')
    m.add_argument('--email', required=True)
    d = sub.add_parser('desactiver', help='désactiver un compte et fermer ses sessions')
    d.add_argument('--email', required=True)
    sub.add_parser('reinitialiser', help='remplacer les demandes par les données de démonstration')
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    import getpass
    if args.cmd in ('compte', 'mot-de-passe'):
        initialise(demo=not args.sans_demo)
        if args.cmd == 'compte':
            if not EMAIL_RE.match(args.email) or not NAME_RE.match(args.nom):
                sys.exit('E-mail ou nom invalide (caractères < > & " \' interdits).')
            if args.role == 'etudiant' and not args.numero:
                sys.exit('--numero est obligatoire pour un compte étudiant.')
        pw = getpass.getpass('Mot de passe (12 caractères minimum) : ')
        if len(pw) < 12 or pw != getpass.getpass('Confirmation : '):
            sys.exit('Mot de passe trop court ou confirmation différente.')
        with tx() as c:
            if args.cmd == 'compte':
                upsert_user(c, args.email.lower(), args.nom, args.role, pw, args.numero if args.role == 'etudiant' else None,
                            args.formation, args.service if args.role == 'agent' else None)
            else:
                row = c.execute('SELECT id FROM users WHERE email = ?', (args.email,)).fetchone()
                if not row:
                    sys.exit('Compte introuvable.')
                c.execute('UPDATE users SET password = ? WHERE id = ?', (hash_password(pw), row['id']))
                c.execute('DELETE FROM sessions WHERE user_id = ?', (row['id'],))
        print('Compte enregistré.')
        return
    if args.cmd == 'desactiver':
        with tx() as c:
            row = c.execute('SELECT id FROM users WHERE email = ?', (args.email,)).fetchone()
            if not row:
                sys.exit('Compte introuvable.')
            c.execute('UPDATE users SET active = 0 WHERE id = ?', (row['id'],))
            c.execute('DELETE FROM sessions WHERE user_id = ?', (row['id'],))
        print('Compte désactivé.')
        return
    if args.cmd == 'reinitialiser':
        initialise(demo=True)
        with tx() as c:
            seed_requests(c)
        print('Données de démonstration recréées.')
        return

    lines = initialise(demo=not args.sans_demo)
    if lines:
        print(f'Premier démarrage — comptes de démonstration (aussi dans {DATA_DIR / "comptes-demo.txt"}) :')
        print('\n'.join('  ' + l for l in lines))
    srv = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    srv.secure_cookies = args.cookies_secure
    print(f'Portail Scolarité prêt : http://{"127.0.0.1" if args.host in ("0.0.0.0", "") else args.host}:{args.port}', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
