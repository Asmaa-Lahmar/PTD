"""Reconstitue les pages HTML autonomes à partir des sources partagées."""
from pathlib import Path
root=Path(__file__).resolve().parent.parent
css=(root/'assets/uniflow.css').read_text(encoding='utf-8')
js=(root/'assets/uniflow.js').read_text(encoding='utf-8')
login='''
<div class="login" data-od-id="login-page">
  <section class="login-story" data-od-id="uniflow-introduction">
    <div><a class="brand" href="index.html" aria-label="UniFlow, accueil"><span class="brand-mark" aria-hidden="true">U</span><span class="brand-name">UniFlow</span></a><div class="brand-sub">La scolarité, simplement</div></div>
    <div><p class="eyebrow" style="color:var(--border-soft)">Votre campus, plus fluide.</p><h1>Vos démarches avancent.<br>Vous aussi.</h1><p class="intro">Un seul espace pour déposer vos demandes, échanger avec la scolarité et suivre chaque étape.</p><div class="login-steps"><div><b>01</b><span>Déposez votre demande</span></div><div><b>02</b><span>Suivez son traitement</span></div><div><b>03</b><span>Recevez une réponse</span></div></div></div>
    <p class="login-foot">Digitalisation des demandes administratives étudiantes<br>Projet de transformation digitale · Université / École d’ingénieurs</p>
  </section>
  <section class="login-panel" data-od-id="authentication-panel"><div class="login-form"><span class="login-type">Espace étudiant &amp; administration</span><h2>Bienvenue sur UniFlow.</h2><p class="muted">Connectez-vous avec votre compte établissement.</p>
    <form id="login-form" data-od-id="login-form"><div class="field"><label for="login-email">Adresse e-mail</label><input type="email" id="login-email" name="email" placeholder="prenom.nom@ecole.fr" autocomplete="username" required maxlength="254" data-od-id="login-email"></div><div class="field"><label for="login-password">Mot de passe</label><input id="login-password" name="password" type="password" autocomplete="current-password" placeholder="Votre mot de passe" required maxlength="200" data-od-id="login-password"></div><p class="error" role="alert" tabindex="-1" id="login-error" style="margin-top:16px"></p><button type="submit" id="login-submit" class="btn btn-primary" style="margin-top:24px" data-od-id="login-submit">Se connecter</button></form>
    <p class="tiny" style="margin-top:14px">Les comptes sont créés par la scolarité. Pour un accès ou un mot de passe perdu, contactez votre administrateur.</p>
    <section class="demo-accounts" data-od-id="demo-accounts"><p class="eyebrow">Découvrir le prototype</p><p class="tiny">Ouvrez une session de démonstration avec des données d’exemple. Ce mode fonctionne uniquement dans votre navigateur.</p><div class="row"><button class="btn" data-demo-user="USR-INES" data-od-id="demo-student">Espace étudiant</button><button class="btn" data-demo-user="USR-SAMIRA" data-od-id="demo-admin">Espace administration</button></div><div class="row"><button class="btn btn-ghost" data-demo-user="USR-YANIS">Autre étudiant</button><button class="btn btn-ghost" id="reset-demo">Réinitialiser la démo</button></div></section>
    <div class="notice"><strong>Deux modes distincts.</strong> La démonstration ne protège pas les données sensibles. Le serveur local fournit l’authentification et les permissions par rôle. Aucune connexion Glide ni notification e-mail n’est active.</div>
  </div></section>
</div>'''
pages={
 'index.html':('login','Connexion'),
 'espace-etudiant.html':('dashboard','Tableau de bord étudiant'),
 'nouvelle-demande.html':('new','Nouvelle demande'),
 'mes-demandes.html':('requests','Mes demandes'),
 'notifications.html':('notifications','Notifications'),
 'profil.html':('profile','Mon profil'),
 'tableau-de-bord.html':('admin','Tableau de bord administration'),
 'file-traitement.html':('queue','Toutes les demandes'),
 'statistiques.html':('stats','Statistiques'),
 'utilisateurs.html':('users','Gestion des utilisateurs'),
}
for filename,(page,title) in pages.items():
 body=login if page=='login' else '<div id="app"><p class="loading" role="status">Chargement de votre espace UniFlow…</p></div>'
 html=f'''<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="oklch(0.265 0.052 251)"><meta name="description" content="UniFlow — Digitalisation des demandes administratives étudiantes."><title>{title} · UniFlow</title>
<style>
{css}
</style></head>
<body data-page="{page}">
{body}
<script>
{js}
</script></body></html>
'''
 (root/filename).write_text(html,encoding='utf-8')
print('10 pages UniFlow autonomes générées.')
