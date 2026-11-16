# Portail Scolarité — application complète

Les écrans HTML du portail (index, nouvelle demande, mes demandes, notifications, profil, file de traitement, tableau de bord, statistiques) sont désormais servis par un vrai serveur avec base de données. L'interface est inchangée.

## Démarrer

Python 3.10 ou plus, aucune dépendance à installer.

```powershell
python serveur/portail.py
```

ou double-cliquez sur `demarrer-portail.bat`, puis ouvrez **http://127.0.0.1:8766**.

Au premier démarrage, des comptes de démonstration sont créés avec des mots de passe aléatoires, affichés dans la console et enregistrés dans `serveur/donnees/comptes-demo.txt` :

| Compte | Espace |
|---|---|
| ines.benali@etu.universite.fr | Étudiant (avec demandes d'exemple) |
| yanis.martin@etu.universite.fr | Étudiant (aucune demande) |
| samira.haddad@universite.fr, julien.durand@…, claire.lefevre@…, moussa.ndiaye@… | Back-office scolarité |

L'espace étudiant et le back-office ont des sessions séparées : vous pouvez être connecté·e aux deux dans deux onglets du même navigateur. Ils se mettent à jour en direct.

## Ce que fait le serveur

- **Authentification** : mot de passe (PBKDF2-SHA256), sessions de 8 h côté serveur, cookies HttpOnly SameSite=Strict, limitation des tentatives, déconnexion.
- **Rôles** : un étudiant ne voit et ne modifie que ses demandes, ses notifications et son profil ; seuls les agents accèdent au back-office et changent les statuts. Les pages sont protégées côté serveur.
- **Workflow** : dépôt validé champ par champ (mêmes règles que le formulaire), acheminement automatique vers le service, délai cible en jours ouvrés, prise en charge, complément, relance (une par jour), reprise, transfert, prête, refus motivé. Transitions contrôlées, conflits détectés si deux agents agissent en même temps.
- **Notifications** : créées pour l'étudiant concerné à chaque étape ; lecture et préférences enregistrées.
- **Pièces justificatives** : PDF, JPEG ou PNG (5 Mo maximum, type vérifié sur le contenu), stockées dans `serveur/donnees/fichiers/`, téléchargeables par leur propriétaire et par les agents (section « Pièces jointes »).
- **Données** : SQLite dans `serveur/donnees/portail.sqlite`. Ne publiez pas le dossier `serveur/donnees`.

## Administration

```powershell
python serveur/portail.py compte --email prenom.nom@etu.universite.fr --nom "Prénom Nom" --role etudiant --numero E21400999 --formation "Master 1 Finance"
python serveur/portail.py compte --email agent@universite.fr --nom "Prénom Nom" --role agent --service centrale
python serveur/portail.py mot-de-passe --email prenom.nom@etu.universite.fr
python serveur/portail.py desactiver --email prenom.nom@etu.universite.fr
python serveur/portail.py reinitialiser          # recrée les demandes de démonstration
python serveur/portail.py --sans-demo            # premier démarrage sans comptes ni données d'exemple
python serveur/portail.py --port 9000
```

Le bouton « Réinitialiser les données de démonstration » de l'accueil fonctionne pour un agent connecté, uniquement sur une installation de démonstration.

## Tests

```powershell
python serveur/test_portail.py
```

54 vérifications de bout en bout sur une base temporaire : authentification, cloisonnement entre étudiants, dépôt et validation, pièces jointes, workflow complet, notifications, profil, protections CSRF et limitation des connexions.

## Modifications apportées au front

L'apparence n'a pas changé. Ajouts et corrections :

- `assets/portail.js` : le stockage localStorage est remplacé par l'API ; les écrans gardent les mêmes appels `P.*`.
- `connexion.html` (nouveau) : page de connexion dans le style du portail.
- Bouton « Se déconnecter » : profil étudiant et barre latérale du back-office.
- Section « Pièces jointes » dans le détail d'une demande (étudiant et agent).
- **Bug corrigé** (nouvelle demande) : seul le nom du justificatif était conservé, jamais le fichier. Le fichier est maintenant envoyé, et reste sélectionné même quand le formulaire se réaffiche.
- **Bug corrigé** (nouvelle demande) : après un échec d'envoi, le bouton restait bloqué.
- **Bug corrigé** (tableau de bord) : une période invalide mémorisée dans le navigateur faisait planter la page.
- **Bug corrigé** (mes demandes) : le message « Complément envoyé » s'affichait même si l'envoi échouait.
- **Bug corrigé** (mises à jour en direct) : un rafraîchissement pouvait effacer une réponse en cours de saisie. Il est maintenant différé.
- Les noms, formations et agents venant de la base sont échappés à l'affichage.

Les originaux sont dans `sauvegarde-portail-avant-serveur/`. L'ancien serveur `serveur/uniflow.py` concerne l'ancienne interface UniFlow (`sauvegarde-uniflow/`) et n'est pas utilisé par ce portail.

## Avant une mise en production

Ce serveur écoute sur 127.0.0.1. Pour de vrais utilisateurs, placez-le derrière un proxy HTTPS (option `--cookies-secure`), branchez l'envoi réel des e-mails et SMS (aujourd'hui, seules les notifications internes sont envoyées), organisez les sauvegardes de `serveur/donnees` et faites une revue de sécurité.
