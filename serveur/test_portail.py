"""Tests de bout en bout du serveur Portail Scolarité, sur une base temporaire.

    python serveur/test_portail.py
"""
import json
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

TMP = tempfile.mkdtemp(prefix='portail-test-')
os.environ['PORTAIL_DATA'] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parent))
import portail  # noqa: E402

PDF = b'%PDF-1.4\n' + bytes(range(256)) * 40 + b'\r\n\r\n--fin\r\n%%EOF'
PNG = b'\x89PNG\r\n\x1a\n' + os.urandom(3000)


class Client:
    def __init__(self, base, espace):
        self.base, self.espace, self.cookie = base, espace, None

    def req(self, method, path, body=None, files=None, headers=None, raw=False):
        h = {'X-Espace': self.espace}
        data = None
        if files is not None:
            boundary = uuid.uuid4().hex
            parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="payload"\r\n\r\n'.encode() + json.dumps(body).encode() + b'\r\n']
            for name, (filename, content) in files.items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + b'\r\n')
            data = b''.join(parts) + f'--{boundary}--\r\n'.encode()
            h['Content-Type'] = 'multipart/form-data; boundary=' + boundary
        elif body is not None:
            data = json.dumps(body).encode()
            h['Content-Type'] = 'application/json'
        if self.cookie:
            h['Cookie'] = self.cookie
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=data, method=method, headers={k: v for k, v in h.items() if v is not None})
        try:
            with urllib.request.urlopen(r) as res:
                status, payload, hdrs = res.status, res.read(), res.headers
        except urllib.error.HTTPError as e:
            status, payload, hdrs = e.code, e.read(), e.headers
        if hdrs.get('Set-Cookie'):
            self.cookie = hdrs['Set-Cookie'].split(';')[0]
        if raw:
            return status, payload, hdrs
        return status, (json.loads(payload) if payload else None)

    def login(self, email, password):
        return self.req('POST', '/api/session', {'email': email, 'password': password, 'espace': self.espace})

    def state(self):
        status, body = self.req('GET', '/api/state')
        assert status == 200, (status, body)
        return body


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    lines = portail.initialise(demo=True)
    creds = {l.split()[1]: l.split()[2] for l in lines}
    srv = portail.http.server.ThreadingHTTPServer(('127.0.0.1', 0), portail.Handler)
    srv.secure_cookies = False
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    ok = 0

    def check(cond, label):
        nonlocal ok
        if not cond:
            raise AssertionError(label)
        ok += 1
        print('  ✓', label)

    ines, yanis, agent = Client(base, 'etudiant'), Client(base, 'etudiant'), Client(base, 'agent')
    INES, YANIS, SAMIRA = 'ines.benali@etu.universite.fr', 'yanis.martin@etu.universite.fr', 'samira.haddad@universite.fr'

    print('Authentification')
    check(ines.login(INES, 'mauvais')[0] == 401, 'mot de passe faux refusé')
    check(Client(base, 'agent').login(INES, creds[INES])[0] == 403, 'compte étudiant refusé sur le back-office')
    check(ines.login(INES, creds[INES])[0] == 200, 'connexion étudiante')
    check(yanis.login(YANIS, creds[YANIS])[0] == 200, 'connexion second étudiant')
    check(agent.login(SAMIRA, creds[SAMIRA])[0] == 200, 'connexion agent')
    check(Client(base, 'etudiant').req('GET', '/api/state')[0] == 401, 'API refusée sans session')
    st, body, h = Client(base, 'etudiant').req('GET', '/mes-demandes.html', raw=True)
    check(b'id="form"' in body and 'Accédez à votre espace'.encode() in body, 'page protégée redirigée vers la connexion')
    st, body, h = Client(base, 'agent').req('GET', '/serveur/portail.py', raw=True)
    check(st == 404, 'sources serveur non exposées')
    st, body, h = ines.req('GET', '/file-traitement.html', raw=True)
    check(b'Connexion' in body, 'back-office inaccessible avec une session étudiante')

    print('Lecture et cloisonnement')
    s = ines.state()
    check(s['me']['name'] == 'Inès Benali' and len(s['requests']) == 4, 'l’étudiante voit ses 4 demandes')
    check(all(r['student']['id'] == s['me']['id'] for r in s['requests']), 'aucune demande d’un autre étudiant')
    check(len(s['notifications']) == 8 and sum(not n['read'] for n in s['notifications']) == 2, 'notifications de démonstration')
    check(len(yanis.state()['requests']) == 0, 'second étudiant : aucune demande')
    a = agent.state()
    check(len(a['requests']) >= 60 and a['agent']['name'] == 'Samira Haddad', 'l’agent voit toute la file')
    st, _, h = ines.req('GET', '/api/state', raw=True)
    check(ines.req('GET', '/api/state', headers={'If-None-Match': h['ETag']}, raw=True)[0] == 304, 'ETag : 304 si rien n’a changé')

    print('Dépôt')
    st, body = ines.req('POST', '/api/demandes', {'type': 'attestation', 'data': portail.defaults_for('attestation')}, files={})
    check(st == 200 and re.match(r'DEM-\d{4}-\d{4}', body['result']['id']), 'attestation déposée')
    rid = body['result']['id']
    r = next(x for x in body['state']['requests'] if x['id'] == rid)
    check(r['status'] == 'soumise' and len(r['history']) == 2 and r['history'][1].get('auto'), 'historique initial + acheminement')
    check(any(n['reqId'] == rid for n in body['state']['notifications']), 'accusé de réception notifié')
    st, body = ines.req('POST', '/api/demandes', {'type': 'attestation', 'data': {**portail.defaults_for('attestation'), 'motif': 'Autre'}}, files={})
    check(st == 400 and 'Précisez' in body['error'], 'champ conditionnel obligatoire vérifié')
    st, body = ines.req('POST', '/api/demandes', {'type': 'attestation', 'data': {**portail.defaults_for('attestation'), 'annee': '1999'}}, files={})
    check(st == 400, 'valeur hors liste refusée')
    data = {**portail.defaults_for('reussite'), 'parcours': 'Économie', 'parchemin': True}
    check(ines.req('POST', '/api/demandes', {'type': 'reussite', 'data': data}, files={})[0] == 400, 'justificatif obligatoire exigé')
    check(ines.req('POST', '/api/demandes', {'type': 'reussite', 'data': data}, files={'piece': ('id.txt', b'hello')})[0] == 415, 'format de fichier refusé')
    st, body = ines.req('POST', '/api/demandes', {'type': 'reussite', 'data': data}, files={'piece': ('carte identité.pdf', PDF)})
    check(st == 200, 'dépôt avec pièce PDF')
    rid2 = body['result']['id']
    f = next(x for x in body['state']['requests'] if x['id'] == rid2)['files'][0]
    st, content, h = ines.req('GET', f'/api/fichiers/{f["id"]}', raw=True)
    check(st == 200 and content == PDF, 'pièce téléchargée intacte par l’étudiante')
    check(agent.req('GET', f'/api/fichiers/{f["id"]}', raw=True)[1] == PDF, 'pièce téléchargeable par l’agent')
    check(yanis.req('GET', f'/api/fichiers/{f["id"]}', raw=True)[0] == 404, 'pièce invisible pour un autre étudiant')
    check(agent.req('POST', '/api/demandes', {'type': 'attestation', 'data': {}}, files={})[0] == 403, 'un agent ne dépose pas de demande')

    print('Workflow back-office')
    check(ines.req('POST', f'/api/demandes/{rid}/statut', {'status': 'en_cours'})[0] == 403, 'étudiant : changement de statut refusé')
    check(agent.req('POST', f'/api/demandes/{rid}/statut', {'status': 'en_cours', 'from': 'en_cours'})[0] == 409, 'conflit détecté (statut modifié entre-temps)')
    check(agent.req('POST', f'/api/demandes/{rid}/statut', {'status': 'prete', 'from': 'soumise'})[0] == 409, 'transition non autorisée')
    st, body = agent.req('POST', f'/api/demandes/{rid}/statut', {'status': 'en_cours', 'from': 'soumise'})
    r = next(x for x in body['state']['requests'] if x['id'] == rid)
    check(st == 200 and r['agent'] == 'Samira Haddad', 'prise en charge, agent affecté')
    check(agent.req('POST', f'/api/demandes/{rid}/statut', {'status': 'info_requise', 'from': 'en_cours'})[0] == 400, 'complément sans message refusé')
    check(agent.req('POST', f'/api/demandes/{rid}/statut', {'status': 'info_requise', 'note': 'Précisez la CAF.', 'from': 'en_cours'})[0] == 200, 'complément demandé')
    check(agent.req('POST', f'/api/demandes/{rid}/relance', {})[1]['result']['ok'] is True, 'relance enregistrée')
    check(agent.req('POST', f'/api/demandes/{rid}/relance', {})[1]['result']['ok'] is False, 'une seule relance par jour')
    s = ines.state()
    check(sum(n['reqId'] == rid and n['kind'] == 'info_requise' for n in s['notifications']) == 2, 'étudiante notifiée (demande + rappel)')
    check(yanis.req('POST', f'/api/demandes/{rid}/complement', {'text': 'x'}, files={})[0] == 404, 'complément refusé à un autre étudiant')
    st, body = ines.req('POST', f'/api/demandes/{rid}/complement', {'text': 'Pour la CAF du Rhône.'}, files={'fichier': ('scan.png', PNG)})
    r = next(x for x in body['state']['requests'] if x['id'] == rid)
    check(st == 200 and r['status'] == 'en_cours' and r['files'][0]['field'] == 'complement', 'complément envoyé avec pièce, traitement relancé')
    check(ines.req('POST', f'/api/demandes/{rid}/complement', {'text': 'encore'}, files={})[0] == 409, 'complément hors statut refusé')
    st, body = agent.req('POST', f'/api/demandes/{rid}/statut', {'status': 'prete', 'note': 'Disponible.', 'from': 'en_cours'})
    r = next(x for x in body['state']['requests'] if x['id'] == rid)
    check(r['status'] == 'prete' and r['closedAt'], 'demande prête et clôturée')
    check(agent.req('POST', f'/api/demandes/{rid}/statut', {'status': 'refusee', 'note': 'x'})[0] == 409, 'demande clôturée figée')
    check(agent.req('POST', f'/api/demandes/{rid2}/transfert', {'service': 'centrale'})[0] == 200, 'transfert de service')
    r = next(x for x in agent.state()['requests'] if x['id'] == rid2)
    check(r['service'] == 'centrale' and r['status'] == 'soumise' and r['agent'] is None, 'transfert : service changé, attribution remise à zéro')

    print('Profil, préférences, notifications')
    s = ines.state()
    unread = [n['id'] for n in s['notifications'] if not n['read']]
    st, body = ines.req('POST', '/api/moi', {'read': unread, 'prefs': {'sms': True}})
    check(st == 200 and all(n['read'] for n in body['state']['notifications']) and body['state']['prefs']['sms'], 'lecture et préférences enregistrées')
    check(ines.req('POST', '/api/moi', {'profile': {'tel': 'abc'}})[0] == 400, 'téléphone invalide refusé')
    st, body = ines.req('POST', '/api/moi', {'profile': {'tel': '06 12 34 56 78', 'mail2': 'ines@exemple.fr', 'adr': '1 rue X'}})
    check(st == 200 and body['state']['profile']['tel'] == '06 12 34 56 78', 'coordonnées enregistrées')
    agent.req('POST', f'/api/demandes/{rid2}/statut', {'status': 'en_cours', 'from': 'soumise'})
    fresh = [n['id'] for n in ines.state()['notifications'] if not n['read']]
    yanis.req('POST', '/api/moi', {'read': fresh})
    check(fresh and all(not n['read'] for n in ines.state()['notifications'] if n['id'] in fresh), 'marquage des notifications d’autrui sans effet')

    print('Sécurité des requêtes')
    check(ines.req('POST', '/api/moi', {'prefs': {}}, headers={'X-Espace': None})[0] == 403, 'POST sans en-tête X-Espace refusé (CSRF)')
    check(ines.req('POST', '/api/moi', {'prefs': {}}, headers={'Origin': 'http://evil.example'})[0] == 403, 'origine étrangère refusée')
    bad = Client(base, 'etudiant')
    for _ in range(5):
        bad.login(YANIS, 'faux')
    check(bad.login(YANIS, creds[YANIS])[0] == 429, 'limitation des tentatives de connexion')

    print('Démonstration et déconnexion')
    check(ines.req('POST', '/api/demo/reinitialiser', {})[0] == 403, 'réinitialisation interdite aux étudiants')
    check(agent.req('POST', '/api/demo/reinitialiser', {})[0] == 200, 'réinitialisation par un agent')
    check(len(ines.state()['requests']) == 4, 'données de démonstration recréées')
    check(ines.req('POST', '/api/logout', {})[0] == 200 and ines.req('GET', '/api/state')[0] == 401, 'déconnexion : session révoquée')

    srv.shutdown()
    print(f'\n{ok} vérifications réussies.')


if __name__ == '__main__':
    main()
