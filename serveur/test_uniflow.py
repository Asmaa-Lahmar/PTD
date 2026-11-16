"""Vérifie les permissions au niveau HTTP et un parcours complet sur une base isolée."""
import base64, importlib.util, json, os, tempfile, threading, unittest
from http.cookiejar import CookieJar
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError
from pathlib import Path

class UniFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();os.environ['UNIFLOW_DB']=str(Path(cls.tmp.name)/'test.sqlite')
        spec=importlib.util.spec_from_file_location('uniflow',Path(__file__).with_name('uniflow.py'));cls.app=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.app)
        cls.app.init()
        with cls.app.connect() as c:
            for name,email,role in [('Étudiant A','a@test.invalid','student'),('Étudiant B','b@test.invalid','student'),('Administrateur','admin@test.invalid','admin')]:
                salt='ab'*16;c.execute('INSERT INTO users(id,name,email,role,salt,password) VALUES(?,?,?,?,?,?)',(email,name,email,role,salt,cls.app.password_hash('Test-UniFlow-2026',salt)))
        cls.server=cls.app.ThreadingHTTPServer(('127.0.0.1',0),cls.app.Handler);cls.port=cls.server.server_port
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()
    def client(self,email):
        op=build_opener(HTTPCookieProcessor(CookieJar()));self.call(op,'login',{'email':email,'password':'Test-UniFlow-2026'},csrf='')
        status,state=self.call(op,'state');self.assertEqual(status,200);return op,state['csrf']
    def call(self,op,path,data=None,csrf='',raw=False):
        url=f'http://127.0.0.1:{self.port}/'+(path if raw else 'api/'+path)
        req=Request(url,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','X-CSRF-Token':csrf})
        try:
            with op.open(req) as r:return r.status,json.loads(r.read()) if not raw else r.read()
        except HTTPError as e:
            try:body=json.loads(e.read())
            except:body={}
            e.close()
            return e.code,body
    def test_password_change(self):
        with self.app.connect() as c:
            salt='cd'*16;c.execute('INSERT INTO users(id,name,email,role,salt,password) VALUES(?,?,?,?,?,?)',('password@test.invalid','Compte test','password@test.invalid','student',salt,self.app.password_hash('Test-UniFlow-2026',salt)))
        a,t=self.client('password@test.invalid');other,_=self.client('password@test.invalid')
        payload={'current_password':'incorrect','new_password':'Nouveau-UniFlow-2026'}
        self.assertEqual(self.call(a,'password',payload,t)[0],400)
        payload['current_password']='Test-UniFlow-2026';payload['new_password']='court'
        self.assertEqual(self.call(a,'password',payload,t)[0],400)
        payload['new_password']='Nouveau-UniFlow-2026'
        self.assertEqual(self.call(a,'password',payload)[0],403)
        self.assertEqual(self.call(a,'password',payload,t)[0],200)
        self.assertEqual(self.call(a,'state')[0],200)
        self.assertEqual(self.call(other,'state')[0],401)
        fresh=build_opener(HTTPCookieProcessor(CookieJar()))
        self.assertEqual(self.call(fresh,'login',{'email':'password@test.invalid','password':'Test-UniFlow-2026'})[0],401)
        self.assertEqual(self.call(fresh,'login',{'email':'password@test.invalid','password':payload['new_password']})[0],200)
        self.assertEqual(self.call(a,'password',{'current_password':payload['new_password'],'new_password':'Test-UniFlow-2026'},t)[0],200)

    def test_full_flow_and_permissions(self):
        anonymous=build_opener();self.assertEqual(self.call(anonymous,'state')[0],401)
        a,ta=self.client('a@test.invalid');b,tb=self.client('b@test.invalid');admin,tc=self.client('admin@test.invalid')
        self.assertEqual(self.call(a,'create',{'type':self.app.TYPES[0],'description':'Une demande de test complète.'})[0],403)
        doc={'name':'preuve.pdf','type':'application/pdf','data':'data:application/pdf;base64,'+base64.b64encode(b'%PDF-1.4\nTest').decode()}
        code,result=self.call(a,'create',{'type':self.app.TYPES[0],'description':'Je souhaite une attestation pour mon dossier.','student_id':'b@test.invalid','status':'Acceptée','document':doc},ta)
        self.assertEqual(code,200);rid=result['id']
        mine=self.call(a,'state')[1];self.assertEqual(len(mine['requests']),1);self.assertEqual(mine['requests'][0]['student_id'],'a@test.invalid');self.assertEqual(mine['requests'][0]['status'],'En attente');self.assertEqual(mine['requests'][0]['document'],doc)
        self.assertEqual(self.call(b,'state')[1]['requests'],[])
        self.assertEqual(self.call(b,'reply',{'id':rid,'comment':'Intrusion'},tb)[0],403)
        self.assertEqual(self.call(a,'update',{'id':rid,'status':'Acceptée','comment':'Intrusion'},ta)[0],403)
        self.assertEqual(self.call(a,'tableau-de-bord.html',raw=True)[0],403)
        self.assertEqual(self.call(anonymous,'serveur/uniflow.sqlite',raw=True)[0],404)
        self.assertEqual(self.call(anonymous,'nouvelle-demande-v2.html',raw=True)[0],404)
        self.assertEqual(self.call(a,'user',{'id':'b@test.invalid','role':'admin','status':'active'},ta)[0],403)
        update=lambda status,comment:self.call(admin,'update',{'id':rid,'status':status,'comment':comment,'assigned_id':'admin@test.invalid'},tc)
        self.assertEqual(update('Terminée','Terminer sans accepter')[0],400)
        self.assertEqual(update('En cours de traitement','Prise en charge')[0],200)
        self.assertEqual(update('Informations complémentaires demandées','')[0],400)
        self.assertEqual(update('Informations complémentaires demandées','Précisez votre année universitaire.')[0],200)
        self.assertEqual(self.call(a,'reply',{'id':rid,'comment':'Année 2026-2027.'},ta)[0],200)
        self.assertEqual(update('Acceptée','Votre dossier est complet.')[0],200)
        self.assertEqual(update('Terminée','Document remis à la scolarité.')[0],200)
        self.assertEqual(update('En cours de traitement','Réouvrir')[0],400)
        final=self.call(a,'state')[1];r=final['requests'][0]
        self.assertEqual(r['status'],'Terminée');self.assertTrue(r['decision_at']);self.assertTrue(r['completed_at']);self.assertEqual(r['decision_by'],'admin@test.invalid');self.assertEqual(len(r['history']),6)
        self.assertGreaterEqual(len(final['notifications']),6)
        notification=final['notifications'][0]['id'];self.assertEqual(self.call(b,'read',{'id':notification},tb)[0],200)
        self.assertFalse(next(n for n in self.call(a,'state')[1]['notifications'] if n['id']==notification)['read'])
        self.call(a,'read',{},ta);self.assertTrue(all(n['read'] for n in self.call(a,'state')[1]['notifications']))
        self.call(admin,'user',{'id':'a@test.invalid','role':'student','status':'suspended'},tc)
        self.assertEqual(self.call(a,'state')[0],401)
    def test_attachment_and_profile_validation(self):
        a,t=self.client('b@test.invalid')
        invalid={'name':'danger.pdf','type':'application/pdf','data':'data:application/pdf;base64,'+base64.b64encode(b'<script>alert(1)</script>').decode()}
        self.assertEqual(self.call(a,'create',{'type':self.app.TYPES[0],'description':'Justificatif invalide de test.','document':invalid},t)[0],400)
        self.assertEqual(self.call(a,'profile',{'name':'Étudiant B','photo':'javascript:alert(1)'},t)[0],400)
        self.assertEqual(self.call(a,'profile',{'name':'Nouveau nom','photo':'','role':'admin'},t)[0],200)
        self.assertEqual(self.call(a,'state')[1]['user']['role'],'student')

if __name__=='__main__':unittest.main(verbosity=2)
