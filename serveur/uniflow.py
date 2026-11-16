"""UniFlow : serveur local sans dépendance, sessions et SQLite.
Lancer : python serveur/uniflow.py --port 8765
"""
import argparse, base64, hashlib, hmac, json, mimetypes, os, secrets, sqlite3, time, uuid
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get('UNIFLOW_DB', str(Path(__file__).with_name('uniflow.sqlite'))))
TYPES = ['Attestation de scolarité', 'Relevé de notes', 'Certificat de réussite', 'Demande de stage', 'Réclamation administrative', 'Autre']
STATUSES = ['En attente', 'En cours de traitement', 'Informations complémentaires demandées', 'Acceptée', 'Refusée', 'Terminée']
NEXT = {STATUSES[0]: STATUSES[1:5], STATUSES[1]: STATUSES[2:5], STATUSES[2]: [STATUSES[1], STATUSES[4]], STATUSES[3]: [STATUSES[5]], STATUSES[4]: [], STATUSES[5]: []}
ATTEMPTS = {}

def now(): return datetime.now(timezone.utc).isoformat()
def uid(prefix): return prefix + '-' + uuid.uuid4().hex[:16].upper()
@contextmanager
def connect():
    c = sqlite3.connect(DB, timeout=15); c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        with c: yield c
    finally: c.close()
def password_hash(password, salt): return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()
def init():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,role TEXT NOT NULL CHECK(role IN ('student','admin')),photo TEXT DEFAULT '',status TEXT DEFAULT 'active',salt TEXT NOT NULL,password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,student_id TEXT NOT NULL REFERENCES users(id),type TEXT NOT NULL,description TEXT NOT NULL,document TEXT,submitted_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,comment TEXT DEFAULT '',assigned_id TEXT REFERENCES users(id),decision_at TEXT,decision_by TEXT REFERENCES users(id),completed_at TEXT);
        CREATE TABLE IF NOT EXISTS history(id TEXT PRIMARY KEY,request_id TEXT NOT NULL REFERENCES requests(id),previous_status TEXT,new_status TEXT NOT NULL,comment TEXT,changed_by TEXT NOT NULL REFERENCES users(id),changed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,recipient_id TEXT NOT NULL REFERENCES users(id),request_id TEXT NOT NULL REFERENCES requests(id),message TEXT NOT NULL,created_at TEXT NOT NULL,read INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),csrf TEXT NOT NULL,expires REAL NOT NULL);
        ''')
        if not c.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            credentials = []
            for name,email,role in [('Inès Benali','ines.benali@uniflow.test','student'),('Yanis Martin','yanis.martin@uniflow.test','student'),('Samira Haddad','samira.haddad@uniflow.test','admin'),('Julien Durand','julien.durand@uniflow.test','admin')]:
                password = secrets.token_urlsafe(12); salt = secrets.token_hex(16)
                c.execute('INSERT INTO users(id,name,email,role,salt,password) VALUES(?,?,?,?,?,?)',(uid('USR'),name,email,role,salt,password_hash(password,salt)))
                credentials.append(f'{name} | {email} | {password}')
            out = DB.with_name('comptes-locaux.txt')
            out.write_text('Comptes locaux de test — ne pas publier\n'+'\n'.join(credentials),encoding='utf-8')
            print('Comptes de test créés dans serveur/comptes-locaux.txt',flush=True)

def public_user(row): return {k:row[k] for k in ('id','name','email','role','photo','status')}
def history_add(c,rid,old,new,comment,actor):
    c.execute('INSERT INTO history VALUES(?,?,?,?,?,?,?)',(uid('HIS'),rid,old,new,comment,actor,now()))
def notify(c,recipient,rid,message):
    c.execute('INSERT INTO notifications(id,recipient_id,request_id,message,created_at) VALUES(?,?,?,?,?)',(uid('NOT'),recipient,rid,message,now()))

class Handler(BaseHTTPRequestHandler):
    server_version = 'UniFlow'
    def log_message(self,fmt,*args): pass
    def send_json(self,data,code=200,cookie=None):
        raw=json.dumps(data,ensure_ascii=False).encode(); self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def session(self,c):
        cookies=SimpleCookie(); cookies.load(self.headers.get('Cookie',''))
        token=cookies.get('uniflow_session'); token=hashlib.sha256(token.value.encode()).hexdigest() if token else ''
        return c.execute('SELECT s.csrf,s.token,u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.status=?',(token,time.time(),'active')).fetchone()
    def data(self):
        size=int(self.headers.get('Content-Length','0'))
        if size>4500000: raise ValueError('Fichier trop volumineux. Maximum : 3 Mo.')
        return json.loads(self.rfile.read(size) or b'{}')
    def do_GET(self):
        if self.path.startswith('/api/'):
            try:
                with connect() as c:
                    user=self.session(c)
                    if not user:return self.send_json({'error':'Connectez-vous pour continuer.'},401)
                    if self.path=='/api/state':return self.send_json(self.state(c,user))
                    return self.send_json({'error':'Ressource introuvable.'},404)
            except Exception:return self.send_json({'error':'Impossible de charger les données.'},500)
        name=self.path.split('?')[0].lstrip('/') or 'index.html'
        # Les anciens écrans sans contrôle de session ne sont jamais servis.
        allowed={'index.html','espace-etudiant.html','nouvelle-demande.html','mes-demandes.html','notifications.html','profil.html','tableau-de-bord.html','file-traitement.html','statistiques.html','utilisateurs.html','brand-spec.md','GUIDE-UNIFLOW.md','assets/uniflow.js','assets/uniflow.css'}
        if name not in allowed:return self.send_error(404)
        if name.endswith('.html') and name!='index.html':
            with connect() as c:
                u=self.session(c)
                if not u:self.send_response(302);self.send_header('Location','/index.html');self.end_headers();return
                is_admin=name in ('tableau-de-bord.html','file-traitement.html','statistiques.html','utilisateurs.html')
                if is_admin and u['role']!='admin':return self.send_error(403,'Acces refuse')
        file=ROOT/name
        if not file.is_file():return self.send_error(404)
        raw=file.read_bytes();self.send_response(200);self.send_header('Content-Type',(mimetypes.guess_type(name)[0] or 'text/plain')+'; charset=utf-8')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def state(self,c,u):
        admin=u['role']=='admin'
        query='SELECT r.*,u.name student_name,u.email student_email FROM requests r JOIN users u ON u.id=r.student_id'
        rows=c.execute(query+('' if admin else ' WHERE r.student_id=?')+' ORDER BY r.submitted_at DESC',() if admin else (u['id'],)).fetchall()
        requests=[]
        for r in rows:
            d=dict(r);d['document']=json.loads(d['document']) if d['document'] else None
            d['history']=[dict(h) for h in c.execute('SELECT h.*,u.name actor FROM history h JOIN users u ON u.id=h.changed_by WHERE request_id=? ORDER BY changed_at',(r['id'],))]
            requests.append(d)
        users=[public_user(x) for x in c.execute('SELECT * FROM users')] if admin else [public_user(u)]
        return {'user':public_user(u),'users':users,'requests':requests,'notifications':[dict(n) for n in c.execute('SELECT * FROM notifications WHERE recipient_id=? ORDER BY created_at DESC',(u['id'],))],'csrf':u['csrf'],'mode':'server'}
    def do_POST(self):
        try:
            d=self.data()
            with connect() as c:
                if self.path=='/api/login':
                    address=self.client_address[0]; recent=[t for t in ATTEMPTS.get(address,[]) if t>time.time()-300]
                    if len(recent)>=12:return self.send_json({'error':'Trop de tentatives. Réessayez dans cinq minutes.'},429)
                    email=str(d.get('email','')).strip().lower();password=str(d.get('password',''))
                    u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
                    if not u or u['status']!='active' or not hmac.compare_digest(password_hash(password,u['salt']),u['password']):
                        ATTEMPTS[address]=recent+[time.time()];return self.send_json({'error':'Identifiants incorrects ou compte suspendu.'},401)
                    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
                    c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],csrf,time.time()+28800))
                    return self.send_json({'user':public_user(u)},cookie=f'uniflow_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
                u=self.session(c)
                if not u:return self.send_json({'error':'Session expirée. Reconnectez-vous.'},401)
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),u['csrf']):return self.send_json({'error':'Action non autorisée. Rechargez la page.'},403)
                if self.path=='/api/logout':
                    c.execute('DELETE FROM sessions WHERE token=?',(u['token'],));return self.send_json({'ok':True},cookie='uniflow_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                if self.path=='/api/create':
                    if u['role']!='student':return self.send_json({'error':'Action réservée aux étudiants.'},403)
                    kind=d.get('type');desc=str(d.get('description','')).strip()
                    if kind not in TYPES or not 10<=len(desc)<=5000:raise ValueError('Choisissez un type et décrivez votre demande (10 à 5 000 caractères).')
                    doc=self.validate_doc(d.get('document'));rid=uid('UF');ts=now()
                    c.execute('INSERT INTO requests(id,student_id,type,description,document,submitted_at,updated_at,status) VALUES(?,?,?,?,?,?,?,?)',(rid,u['id'],kind,desc,json.dumps(doc) if doc else None,ts,ts,STATUSES[0]))
                    history_add(c,rid,None,STATUSES[0],'Demande déposée.',u['id']);notify(c,u['id'],rid,'Votre demande a bien été reçue : '+kind+'.')
                    for staff in c.execute("SELECT id FROM users WHERE role='admin' AND status='active'"):notify(c,staff['id'],rid,'Nouvelle demande de '+u['name']+' : '+kind+'.')
                    return self.send_json({'id':rid})
                if self.path=='/api/read':
                    if d.get('id'):c.execute('UPDATE notifications SET read=1 WHERE id=? AND recipient_id=?',(d['id'],u['id']))
                    else:c.execute('UPDATE notifications SET read=1 WHERE recipient_id=?',(u['id'],))
                    return self.send_json({'ok':True})
                if self.path=='/api/password':
                    current=str(d.get('current_password','')); password=str(d.get('new_password',''))
                    if not hmac.compare_digest(password_hash(current,u['salt']),u['password']):raise ValueError('Le mot de passe actuel est incorrect.')
                    if not 12<=len(password)<=200:raise ValueError('Utilisez entre 12 et 200 caractères pour le nouveau mot de passe.')
                    if hmac.compare_digest(current,password):raise ValueError('Choisissez un mot de passe différent du mot de passe actuel.')
                    salt=secrets.token_hex(16)
                    c.execute('UPDATE users SET salt=?,password=? WHERE id=?',(salt,password_hash(password,salt),u['id']))
                    c.execute('DELETE FROM sessions WHERE user_id=? AND token<>?',(u['id'],u['token']))
                    return self.send_json({'ok':True})
                if self.path=='/api/profile':
                    name=str(d.get('name','')).strip(); photo=str(d.get('photo',''))
                    if len(name)<2 or len(name)>100:raise ValueError('Saisissez un nom de 2 à 100 caractères.')
                    if photo and (not photo.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')) or len(photo)>1400000):raise ValueError('Photo invalide ou trop volumineuse (1 Mo maximum).')
                    c.execute('UPDATE users SET name=?,photo=? WHERE id=?',(name,photo,u['id']));return self.send_json({'ok':True})
                if self.path=='/api/user':
                    if u['role']!='admin':return self.send_json({'error':'Accès administrateur requis.'},403)
                    target=c.execute('SELECT * FROM users WHERE id=?',(d.get('id'),)).fetchone()
                    if not target:raise ValueError('Compte introuvable.')
                    if target['id']==u['id']:raise ValueError('Vous ne pouvez pas modifier votre propre accès.')
                    role=d.get('role',target['role']);status=d.get('status',target['status'])
                    if role not in ('admin','student') or status not in ('active','suspended'):raise ValueError('Rôle ou statut invalide.')
                    if role!=target['role'] and c.execute('SELECT 1 FROM requests WHERE student_id=? OR assigned_id=?',(target['id'],target['id'])).fetchone():raise ValueError('Le rôle ne peut pas changer tant que ce compte est lié à des demandes.')
                    c.execute('UPDATE users SET role=?,status=? WHERE id=?',(role,status,target['id']))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(target['id'],));return self.send_json({'ok':True})
                if self.path not in ('/api/update','/api/reply'):return self.send_json({'error':'Action introuvable.'},404)
                r=c.execute('SELECT * FROM requests WHERE id=?',(d.get('id'),)).fetchone()
                if not r:return self.send_json({'error':'Demande introuvable.'},404)
                comment=str(d.get('comment','')).strip()
                if len(comment)>5000:raise ValueError('Commentaire trop long (5 000 caractères maximum).')
                if self.path=='/api/reply':
                    if u['role']!='student' or r['student_id']!=u['id']:return self.send_json({'error':'Accès refusé.'},403)
                    if r['status']!=STATUSES[2] or not comment:raise ValueError('Cette demande n’attend pas de complément, ou votre réponse est vide.')
                    c.execute('UPDATE requests SET status=?,updated_at=? WHERE id=?',(STATUSES[1],now(),r['id']))
                    history_add(c,r['id'],r['status'],STATUSES[1],comment,u['id'])
                    for a in c.execute("SELECT id FROM users WHERE role='admin' AND status='active'"):notify(c,a['id'],r['id'],'Complément reçu pour '+r['id']+'.')
                    notify(c,u['id'],r['id'],'Votre complément a été transmis. Le traitement reprend.')
                else:
                    if u['role']!='admin':return self.send_json({'error':'Accès administrateur requis.'},403)
                    status=d.get('status',r['status']);assigned=d.get('assigned_id') or None
                    if status!=r['status'] and status not in NEXT[r['status']]:raise ValueError('Transition de statut non autorisée.')
                    if assigned and not c.execute("SELECT id FROM users WHERE id=? AND role='admin' AND status='active'",(assigned,)).fetchone():raise ValueError('Agent invalide.')
                    if status!=r['status'] and status in (STATUSES[2],STATUSES[3],STATUSES[4]) and not comment:raise ValueError('Expliquez la décision ou le complément attendu.')
                    if not comment and status==r['status'] and assigned==r['assigned_id']:raise ValueError('Aucune modification à enregistrer.')
                    ts=now();decision=ts if status!=r['status'] and status in (STATUSES[3],STATUSES[4]) else r['decision_at']
                    actor=u['id'] if decision!=r['decision_at'] else r['decision_by'];completed=ts if status==STATUSES[5] else r['completed_at']
                    c.execute('UPDATE requests SET status=?,comment=?,assigned_id=?,updated_at=?,decision_at=?,decision_by=?,completed_at=? WHERE id=?',(status,comment or r['comment'],assigned,ts,decision,actor,completed,r['id']))
                    history_add(c,r['id'],r['status'],status,comment or 'Affectation mise à jour.',u['id'])
                    notify(c,r['student_id'],r['id'],r['id']+' : '+status+'. '+(comment or 'Affectation mise à jour.'))
                return self.send_json({'ok':True})
        except (ValueError,TypeError,KeyError,json.JSONDecodeError) as e:return self.send_json({'error':str(e)},400)
        except Exception:return self.send_json({'error':'Enregistrement impossible. Réessayez.'},500)
    def validate_doc(self,doc):
        if not doc:return None
        if not isinstance(doc,dict):raise ValueError('Justificatif invalide.')
        name=str(doc.get('name',''));data=str(doc.get('data',''));mime=str(doc.get('type',''))
        if mime not in ('application/pdf','image/png','image/jpeg') or not data.startswith('data:'+mime+';base64,'):raise ValueError('Formats autorisés : PDF, PNG et JPEG.')
        raw=base64.b64decode(data.split(',',1)[1],validate=True)
        if len(raw)>3*1024*1024 or not name or len(name)>200:raise ValueError('Justificatif trop volumineux ou nom invalide (3 Mo maximum).')
        valid=(mime=='application/pdf' and raw.startswith(b'%PDF-')) or (mime=='image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (mime=='image/jpeg' and raw.startswith(b'\xff\xd8\xff'))
        if not valid:raise ValueError('Le contenu du fichier ne correspond pas à son format.')
        return {'name':name,'data':data,'type':mime}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    init();print(f'UniFlow prêt : http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
