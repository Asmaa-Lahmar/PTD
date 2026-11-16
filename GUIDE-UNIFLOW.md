# UniFlow — fonctionnement et déploiement

## Résultat livré

Application en français, dix écrans HTML autonomes, sans dépendance externe. Deux modes sont distincts :

- **Démonstration locale** : depuis `index.html`, les boutons étudiant, autre étudiant et administration ouvrent des jeux de données explicitement fictifs et persistés dans ce navigateur. Une session de démonstration est propre à l’onglet. Ce mode n’assure aucune confidentialité contre l’inspection du navigateur et ne doit contenir aucune donnée réelle.
- **Serveur local** : authentification par mot de passe, sessions côté serveur, base SQLite persistante, vérification des rôles et de la propriété des demandes pour chaque opération. Les comptes et demandes de démonstration du navigateur ne sont pas importés dans cette base.

Ce livrable n’est pas une application publiée dans Glide. Aucun projet Glide, abonnement, table distante, workflow Glide ou envoi d’e-mail n’a été créé depuis cette session.

## Démarrage du serveur

Depuis le dossier du projet, avec Python 3.10 ou version ultérieure :

```powershell
python serveur/uniflow.py --port 8765
```

Ouvrir **http://127.0.0.1:8765**. Au premier démarrage, quatre comptes de test sont créés avec des mots de passe aléatoires. Leurs identifiants figurent dans `serveur/comptes-locaux.txt`, fichier exclu des ressources accessibles par HTTP. La base est `serveur/uniflow.sqlite`. Ne publiez ni la base ni ce fichier de comptes. Les mots de passe sont stockés sous forme d’empreinte PBKDF2-SHA256 avec sel unique ; le fichier de comptes ne sert qu’au premier accès local.

La base serveur commence sans demande. Les statistiques augmentent après des dépôts effectifs. Les boutons de démonstration restent accessibles pour la soutenance, avec une bannière rappelant leurs limites.

Pour vérifier les permissions et le parcours complet sur une base temporaire :

```powershell
python serveur/test_uniflow.py
```

Pour régénérer les pages autonomes après une modification des sources communes :

```powershell
python serveur/generer_pages.py
```

## Écrans

| Écran | Fichier | Accès |
|---|---|---|
| Connexion | index.html | Public |
| Accueil étudiant | espace-etudiant.html | Étudiant |
| Dépôt | nouvelle-demande.html | Étudiant |
| Suivi et détail | mes-demandes.html | Étudiant propriétaire |
| Notifications | notifications.html | Utilisateur connecté, destinataire uniquement |
| Profil | profil.html | Utilisateur connecté, son propre profil |
| Pilotage | tableau-de-bord.html | Administration |
| Gestion des demandes | file-traitement.html | Administration |
| Statistiques | statistiques.html | Administration |
| Gestion des accès | utilisateurs.html | Administration |

Le détail s’ouvre dans un dialogue accessible depuis la liste ou une notification. Une URL avec `?id=...` ouvre directement ce détail après vérification des droits. Les anciens fichiers `-v2` sont des sauvegardes ; ils ne sont pas servis par le serveur UniFlow.

## Tables et relations

La base locale comporte quatre tables métier et une table technique de sessions. La définition SQL complète est dans `serveur/uniflow.py`.

| Table demandée | Table locale | Champs |
|---|---|---|
| Users | users | id, name, email unique, role, photo, status ; salt et password techniques |
| Requests | requests | id, student_id, type, description, document, submitted_at, updated_at, status, comment, assigned_id, decision_at ; decision_by, completed_at additionnels |
| Request History | history | id, request_id, previous_status, new_status, comment, changed_by, changed_at |
| Notifications | notifications | id, recipient_id, request_id, message, created_at, read |
| Sessions | sessions | empreinte du jeton, user_id, csrf, expires |

Relations :

- `requests.student_id → users.id` : un étudiant, plusieurs demandes.
- `requests.assigned_id → users.id` : agent affecté, nécessairement un administrateur actif au moment de l’affectation.
- `requests.decision_by → users.id` : auteur de la décision.
- `history.request_id → requests.id` et `history.changed_by → users.id`.
- `notifications.recipient_id → users.id` et `notifications.request_id → requests.id`.
- `sessions.user_id → users.id`.

Le nom et l’e-mail étudiants des demandes sont récupérés par jointure avec Users. Ils ne sont jamais acceptés comme identité depuis le formulaire. Les justificatifs PDF/PNG/JPEG sont réellement conservés et téléchargeables, limités à 3 Mo. Les photos de profil sont facultatives (1 Mo). Les fichiers sont intégrés aux données de ce prototype ; pour un déploiement à plus grande échelle, utiliser un stockage privé avec contrôle d’accès et analyse des fichiers.

## Permissions effectives côté serveur

| Action | Étudiant | Administration |
|---|---|---|
| Voir ses demandes | Oui | Toutes les demandes |
| Voir celles d’un autre étudiant | Refus HTTP 403 sur opération, absence de lignes dans la réponse de lecture | Oui |
| Déposer une demande | Oui, identité issue de la session | Non |
| Changer un statut / affecter / décider | Non, refus HTTP 403 | Oui, transitions validées |
| Modifier le commentaire administratif | Non | Oui |
| Répondre à un complément | Sa demande, au statut complément uniquement | Non |
| Consulter une notification | Ses notifications uniquement | Ses notifications uniquement |
| Changer son nom / sa photo | Oui | Oui |
| Changer son propre rôle | Non | Non |
| Gérer un autre compte | Non | Rôle et suspension, avec restrictions sur les comptes liés à des dossiers |

Les pages administratives elles-mêmes sont refusées côté HTTP aux étudiants. Les anciennes versions, scripts serveur, comptes et base ne sont pas exposés par le serveur. Les cookies sont HttpOnly, SameSite=Strict, expirent après huit heures et renvoient à une session serveur. Les actions authentifiées demandent un jeton CSRF. La déconnexion et la suspension révoquent les sessions. Le serveur limite les tentatives de connexion. Les requêtes SQL sont paramétrées.

Ce serveur est **un prototype local**, lié uniquement à `127.0.0.1`. Avant toute exposition à des utilisateurs réels : hébergement HTTPS, cookie Secure, gestion institutionnelle des comptes et mots de passe, sauvegardes, politique de conservation, journalisation d’exploitation et revue de sécurité. Aucun changement d’hébergement ni publication n’a été effectué.

## Statuts et automatisations implémentés

1. Dépôt : identifiant UUID unique, dates serveur, En attente, historique initial, notification étudiant et administrations actives. L’enregistrement des données, de l’historique et des notifications est transactionnel.
2. Affectation : agent actif validé, date de modification et historique mis à jour, notification à l’étudiant.
3. Complément : commentaire obligatoire, statut Informations complémentaires demandées, notification à l’étudiant. Sa réponse est historisée et remet la demande En cours de traitement ; le commentaire administratif ne peut pas être écrasé par cette réponse.
4. Acceptation/refus : explication obligatoire, date de décision et administrateur responsable conservés, notification étudiante.
5. Clôture : seule une demande Acceptée peut passer à Terminée ; date de fin enregistrée.
6. Lecture : seules les notifications du destinataire peuvent être marquées lues.
7. Alertes : une demande encore En attente après cinq jours calendaires porte un signalement visible. Il s’agit d’un repérage au chargement, pas d’une relance planifiée.
8. Actualisation : les écrans de lecture vérifient les nouvelles données toutes les quinze secondes lorsqu’ils sont visibles. Aucun rafraîchissement automatique ne remplace un formulaire en cours de saisie ou un détail ouvert.

Transitions : En attente → En cours / Complément / Acceptée / Refusée ; En cours → Complément / Acceptée / Refusée ; Complément → En cours / Refusée ; Acceptée → Terminée. Refusée et Terminée sont finales. Une réponse étudiante n’est permise que pour son propre dossier en attente de complément.

Les indicateurs et graphiques comptent les demandes du périmètre filtré. « Acceptées » comprend les demandes terminées, qui ont nécessairement été acceptées. Le délai moyen mesure les jours calendaires entre dépôt et décision ; en l’absence de décision horodatée, il affiche « Non disponible ».

## Transposition dans Glide : configuration manuelle restante

Les indications suivantes concernent un projet Glide à configurer dans votre compte. Les fonctionnalités et intégrations disponibles doivent être vérifiées sur l’offre réellement utilisée.

### Données et profils

Créer quatre Glide Tables : Users, Requests, Request History, Notifications, avec les champs du cahier des charges. Utiliser un Row ID unique pour chaque table. Configurer Users comme table de profils et la colonne Role comme rôle, avec les valeurs Étudiant et Administrateur. Ne pas permettre aux utilisateurs de renseigner ou d’éditer leur rôle. Restreindre l’accès à une liste d’utilisateurs autorisés et désactiver l’inscription libre si l’établissement contrôle les comptes.

Créer les relations User ID ↔ Student User ID, User ID ↔ Assigned Staff ID, Request ID ↔ Request ID de l’historique et des notifications, User ID ↔ Recipient User ID. Les noms et adresses de Requests doivent provenir de l’identité connectée et des relations, jamais d’un choix d’étudiant dans un formulaire.

### Protection des lignes : indispensable

Les conditions de visibilité et les filtres ne protègent pas les données. Configurer des **Row Owners** :

- Requests : Student Email comme propriétaire et une seconde colonne propriétaire avec le rôle Administrateur. Les valeurs doivent être fixées par des actions de confiance, non modifiables par l’étudiant.
- Request History : recopier l’e-mail propriétaire de la demande et la valeur de rôle Administrateur sur chaque nouvelle ligne ; marquer ces colonnes comme Row Owners.
- Notifications : recopier l’e-mail du destinataire dans une colonne Row Owner ; aucune visibilité globale requise.
- Users : e-mail propriétaire et rôle Administrateur si la gestion complète des comptes est nécessaire. Séparer les profils publics des informations privées si un annuaire partagé est souhaité.

Vérifier ensuite, avec deux comptes étudiants distincts et un administrateur, que les lignes non autorisées ne sont pas téléchargées. Ne pas confondre l’affichage masqué avec l’accès sécurisé.

### Formulaires, actions et workflows

- Formulaire de dépôt : Type, Description, Supporting Document ; colonnes automatiques identité, statut, dates. Après soumission, ajouter l’historique et les notifications, puis ouvrir le détail avec confirmation.
- Mise à jour admin : garder l’ancien statut dans une variable avant modification ; valider rôle, transition et commentaire ; écrire le nouveau statut, l’auteur, l’affectation et les dates ; créer l’historique et la notification.
- Réponse au complément : vérifier propriétaire + statut ; ajouter l’historique, remettre En cours et notifier le service.
- Décision : commentaire obligatoire ; inscrire Decision Date et un champ supplémentaire Decision By pour conserver l’auteur.
- Dépassement : colonne calculée sur Submission Date et Status ; un Scheduled Workflow peut ensuite envoyer une relance selon les capacités du forfait.
- E-mail : connecter une action d’envoi ou un service autorisé par l’établissement. Ne jamais afficher « E-mail envoyé » avant confirmation effective de l’intégration. En l’absence d’intégration, conserver les notifications internes (alternative déjà réalisée ici).
- Les déclencheurs planifiés, intégrations, quotas d’exécution et domaines e-mail admis dépendent de l’offre Glide et doivent être validés avant publication. Aucun tarif ou droit de forfait précis n’est supposé.

### Sources officielles consultées

- [Glide : rôles et Row Owners](https://help.glideapps.com/en/articles/11025531-the-glide-glossary)
- [Glide : sécurité](https://www.glideapps.com/security-center)
- [Glide : workflows](https://www.glideapps.com/classic/workflows)
- [Glide : intégrations et consommation](https://help.glideapps.com/en/articles/9421192-how-am-i-charged-for-integration-usage)
- [Glide : offres actuelles](https://www.glideapps.com/pricing)

## Scénario de soutenance

1. Ouvrir la démonstration étudiant et déposer une Réclamation administrative avec description et justificatif.
2. Vérifier l’apparition dans Mes demandes et la confirmation dans Notifications.
3. Ouvrir une autre session d’administration ; rechercher la référence et affecter le dossier.
4. Demander un complément avec un message explicite.
5. Revenir à l’étudiant, consulter la notification et répondre.
6. Accepter avec une explication puis terminer le dossier ; vérifier l’historique et les graphiques.
7. Ouvrir l’autre étudiant : il ne voit pas cette demande dans son espace. Pour démontrer une véritable protection des lignes et des opérations, utiliser les comptes du serveur local et les tests HTTP, et non la démonstration navigateur.

## Changement du mot de passe

Depuis **Mon profil → Sécurité du compte**, chaque utilisateur connect? au serveur peut changer son propre mot de passe. Le mot de passe actuel est vérifié ; le nouveau doit être différent et comporter entre 12 et 200 caractères. La confirmation est contrôlée dans le formulaire. Le serveur renouvelle le sel et l’empreinte PBKDF2 et révoque les autres sessions du compte, tout en conservant la session actuelle. Le jeton CSRF est obligatoire. Aucun mot de passe n?est modifié dans le fichier initial de comptes : après un changement, utiliser le nouveau mot de passe.

Ce formulaire est remplac? par une explication en démonstration. La récupération d?un mot de passe oublié reste ? organiser avec la scolarité ; aucun e-mail de réinitialisation n?est envoyé.
