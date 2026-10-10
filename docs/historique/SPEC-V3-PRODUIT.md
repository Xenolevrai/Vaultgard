# Cahier des charges — VaultGuard v3 (produit commercialisable)

Objectif : transformer la démo en plateforme multi-clients. Une entreprise crée un compte, branche ses agents IA par
clé API, et chaque paiement passe par le pare-feu puis par son coffre Avalanche. Le cœur on-chain (AgentVault) reste
la garantie finale : ne jamais le contourner.

Contraintes : Python stdlib + `web3` + `python-dotenv` (pas de framework web), SQLite, pages HTML/CSS/JS sans build ni CDN,
mêmes règles de sécurité et de design qu'AGENTS.md. Chaque étape se termine par `bash scripts/test-all.sh --full` vert.

## Étape 1 — Persistance (`agent/db.py`)
- SQLite, une connexion par thread, WAL, clés étrangères, requêtes **toujours paramétrées**.
- Tables : utilisateurs, organisations, appartenances (rôle), invitations, sessions, clés API, fournisseurs,
  demandes de paiement, journal d'audit, événements de connexion.
- Ne stocker que des **empreintes** pour les secrets : mot de passe (scrypt, déjà dans `server.py`), jeton de session,
  clé API et jeton d'invitation (SHA-256).
- Chemin de la base : variable `DB_PATH` (défaut `data/vaultguard.db`, dossier gitignoré ; en Docker : `/data`).
- Tests : création du schéma, migrations idempotentes.

## Étape 2 — Comptes et connexion (`agent/auth.py`)
- Inscription (désactivable : `SIGNUP_OPEN=0` → invitation seulement) : crée l'utilisateur + son organisation (rôle owner).
- Mot de passe ≥ 12 caractères, refus d'une petite liste de mots de passe courants.
- Connexion : verrouillage après 5 échecs (15 min), message identique que l'email existe ou non.
- Double authentification TOTP (RFC 6238, implémentée en stdlib : HMAC-SHA1, 6 chiffres, 30 s, fenêtre ±1) :
  activation avec code de vérification, clé affichée en base32 + lien `otpauth://`.
- Sessions côté serveur (cookie HttpOnly, SameSite=Strict, Secure en prod), nouvelle session à la connexion, expiration
  d'inactivité 2 h, « déconnecter toutes mes sessions ».
- Changement de mot de passe (ancien requis), invitation par lien à usage unique (expire en 7 jours).
- Commande `python3 server.py --create-admin` : crée le super-administrateur de la plateforme.

## Étape 3 — Espaces clients (organisations)
Rôles : **owner** (tout), **admin** (tout sauf supprimer l'organisation / changer l'owner), **approver** (valider ou refuser
les paiements), **viewer** (lecture). Un utilisateur peut appartenir à plusieurs organisations et changer d'organisation active.
Chaque requête vérifie que la ressource appartient à l'organisation active (tests anti-IDOR obligatoires : un client ne
doit jamais voir ni modifier les données d'un autre).

Pages de l'espace client (`/app`) :
1. **Vue d'ensemble** : paiements du jour, bloqués, en attente, montant protégé, état du coffre (actif/gelé), alertes.
2. **Paiements** : liste filtrable ; détail = demande de l'utilisateur, documents lus, verdict du pare-feu (phrase claire +
   détails techniques), décision du contrat, lien Snowtrace ; boutons Valider / Rejeter (approver+).
3. **Agents et clés API** : créer une clé (affichée **une seule fois**), nommer, révoquer, voir la dernière utilisation ;
   clé mise en **quarantaine automatique** après N blocages en 1 h ou au premier appât touché.
4. **Fournisseurs** : carnet d'adresses ; un ajout n'est payable qu'après le délai (24 h par défaut), comme on-chain.
5. **Politique** : plafonds, seuil de validation humaine, délai, disjoncteur (simulation) ; en mode Avalanche, lecture des
   valeurs on-chain + lien vers le contrat.
6. **Journal d'audit** : chaque action (connexion, clé créée, paiement, validation, changement de règle) ; **chaîné par hash**
   (chaque ligne contient l'empreinte de la précédente) ; bouton « Vérifier l'intégrité » ; export CSV protégé (CWE-1236) ;
   « Sceller sur Avalanche » (`anchorReport`).
7. **Équipe** : membres, rôles, invitations.
8. **Intégration** : exemple de code pour brancher un agent (Python et curl), adresse appât propre à l'organisation.
9. **Paramètres** : nom, réseau (Simulation / Avalanche Fuji + adresse du coffre), mot de passe, 2FA, sessions.

## Étape 4 — API pour les agents IA (`/v1`)
Authentification par `Authorization: Bearer <clé>`, sans cookie (donc pas de CSRF), limitation de débit par clé.
- `POST /v1/payments` `{to, amount, memo, user_request, documents:[{source, content}]}` → `{id, decision, reasons, chain}`.
  `decision` ∈ `allowed` | `pending_review` | `blocked`. En simulation : exécution sur le coffre simulé de l'organisation
  (état persistant en base). En mode Avalanche : la clé de l'agent reste chez le client ; il signe `requestPayment`
  lui-même après `allowed` (la plateforme ne détient jamais de clé privée client).
- `GET /v1/payments/{id}` : statut (l'agent attend une validation humaine).
- `GET /v1/policy` : fournisseurs actifs et limites.
- Le pare-feu utilise les données de l'organisation : carnet = fournisseurs, historique = paiements passés (anomalie de
  montant), doubles paiements sur tout l'historique, quota par clé et par heure.
- Fournir `sdk/vaultguard_client.py` (client Python minimal) + un exemple d'agent.

## Étape 5 — Espace administrateur de la plateforme (`/admin`, super-admin uniquement, 2FA obligatoire)
Statistiques globales, liste des organisations (suspendre/réactiver), utilisateurs (désactiver, déconnecter partout),
événements de sécurité (échecs de connexion, quarantaines, appâts), journal d'audit de la plateforme, santé
(base, RPC Avalanche, version).

## Étape 6 — Site public
Page d'accueil (le problème, les 2 couches, Avalanche, sécurité prouvée, appel à l'action « Créer un compte » /
« Voir la démo »), page Documentation API, page Sécurité (résumé de docs/SECURITE.md), mentions légales et
politique de confidentialité (modèles à compléter), la démo actuelle accessible sur `/demo`.

## Étape 7 — Design (s'applique à toutes les pages)
Charte d'AGENTS.md §5.7 ; CSS et JS en fichiers statiques servis par le serveur (liste blanche de fichiers, CSP `'self'`) ;
mise en page à barre latérale pour `/app` et `/admin` ; tableaux qui défilent horizontalement sur mobile ; **aucun texte ne
dépasse de son cadre** (adresses et hash : `overflow-wrap:anywhere`, colonnes `min-width:0`) ; vérifier chaque page dans
Chrome à 1440 px et 390 px de large.

## Étape 8 — Tests et audit
- `agent/test_product.py` : inscription, connexion, verrouillage, 2FA, sessions, rôles, **isolation entre clients**,
  clés API (création, révocation, quarantaine), `/v1/payments` (10 scénarios via l'API), journal chaîné (altération
  détectée), export CSV, admin réservé au super-admin.
- `scripts/security-audit.sh` : ajouter énumération d'utilisateurs, force brute, accès croisé entre organisations,
  clé API révoquée, accès `/admin` sans droits, injection SQL (sqlmap sur `/api/auth/login` en local).
- Mettre à jour `docs/SECURITE.md`, `docs/MISE_EN_PRODUCTION.md` (sauvegarde de la base, `DB_PATH`, création de
  l'admin), AGENTS.md §3, §4 et §6, et le guide PDF.

## Avant une vraie commercialisation (hors code)
Structure juridique, CGU/CGV et politique de confidentialité relues par un juriste (RGPD : registre, DPA, hébergement UE),
audit externe du contrat et pentest externe, assurance, support client, supervision 24/7.
