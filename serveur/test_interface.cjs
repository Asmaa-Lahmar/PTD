/* Vérification des vues et événements dans un DOM simulé, sans navigateur. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),{webcrypto}=require('crypto');
const source=fs.readFileSync(require('path').join(__dirname,'../assets/uniflow.js'),'utf8').replace(/\nboot\(\);\n\}\)\(\);/,'\n})();');
const memory={};
const storage=store=>({getItem:k=>store[k]??null,setItem:(k,v)=>store[k]=String(v),removeItem:k=>delete store[k]});
async function context(page,user){
 const elements={},events={},session={'uniflow-demo-session':user};
 class Element{
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.value='';this.dataset={};this.files=[];this.open=false;this.classList={toggle:()=>false,remove:()=>{}};this.attributes={};}
  set id(v){this._id=v;elements[v]=this;}get id(){return this._id;}
  set innerHTML(html){this.html=html;for(const m of html.matchAll(/<(\w+)([^>]*?\sid="([^"]+)"[^>]*)>/g)){const el=new Element(m[1]);el.id=m[3];el.value=m[2].match(/\bvalue="([^"]*)"/)?.[1]||'';}}
  get innerHTML(){return this.html||'';}setAttribute(k,v){this.attributes[k]=v;}
  appendChild(n){if(n.id)elements[n.id]=n;}remove(){}focus(){}showModal(){this.open=true;}close(){this.open=false;}
  querySelector(){return new Element('button');}querySelectorAll(){return [];}reportValidity(){return true;}
 }
 const body=new Element('body');body.dataset.page=page;const app=new Element();app.id='app';
 const doc={body,hidden:false,events,createElement:t=>new Element(t),getElementById:id=>elements[id]||null,querySelector:s=>s.startsWith('#')?elements[s.slice(1)]||null:null,querySelectorAll:()=>[],addEventListener:(type,fn)=>(events[type]??=[]).push(fn)};
 const ctx={document:doc,window:{},location:{search:'',replace:url=>ctx.redirect=url,href:''},localStorage:storage(memory),sessionStorage:storage(session),crypto:webcrypto,URL,URLSearchParams,Blob,FileReader:class{},console,setTimeout:()=>0,setInterval:()=>0,clearInterval:()=>{},confirm:()=>true,fetch:()=>{throw Error('Accès réseau inattendu');}};
 vm.createContext(ctx);vm.runInContext(source,ctx);await ctx.window.UniFlow.boot();return {ctx,elements,events,U:ctx.window.UniFlow};
}
async function submit(c,id){await c.events.submit[0]({target:Object.assign(c.elements[id],{id}),preventDefault(){}});}
async function clickOpen(c,id){await c.events.click[0]({target:{closest:s=>s==='[data-open]'?{dataset:{open:id}}:null},preventDefault(){}});}
(async()=>{
 for(const page of ['dashboard','new','requests','notifications','profile']){const c=await context(page,'USR-INES');assert(c.elements['page-content'].innerHTML.length>500,page);assert(!c.elements['page-content'].innerHTML.includes('undefined'),page);}
 for(const page of ['admin','queue','stats','users']){const c=await context(page,'USR-SAMIRA');assert(c.elements['page-content'].innerHTML.length>500,page);assert(!c.elements['page-content'].innerHTML.includes('undefined'),page);}
 const denied=await context('admin','USR-INES');assert.equal(denied.ctx.redirect,'espace-etudiant.html');
 const student=await context('new','USR-INES');student.elements['request-type'].value='Autre';student.elements['request-description'].value='Je souhaite une précision sur mon inscription administrative.';
 await submit(student,'request-form');assert(student.elements['detail-dialog'].open);await student.elements['confirm-action'].onclick();
 assert(student.elements['page-content'].innerHTML.includes('C’est transmis'));let db=JSON.parse(memory['uniflow-demo-v1']);const r=db.requests[0];assert.equal(r.status,'En attente');
 const admin=await context('queue','USR-SAMIRA');await clickOpen(admin,r.id);admin.elements['action-status'].value='Informations complémentaires demandées';admin.elements['action-staff'].value='USR-SAMIRA';admin.elements['action-comment'].value='Précisez votre année.';
 await submit(admin,'admin-action');await admin.elements['confirm-action'].onclick();
 const student2=await context('requests','USR-INES');await clickOpen(student2,r.id);student2.elements['reply-text'].value='Année 2026-2027.';await submit(student2,'reply-form');
 db=JSON.parse(memory['uniflow-demo-v1']);assert.equal(db.requests.find(x=>x.id===r.id).status,'En cours de traitement');
 const other=await context('requests','USR-YANIS');assert(!other.U.demoState().requests.some(x=>x.id===r.id));
 console.log('Interface : 9 vues, redirection par rôle, dépôt confirmé, complément et réponse, isolation des listes OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
