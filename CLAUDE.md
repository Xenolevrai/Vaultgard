@AGENTS.md

## Spécifique à Claude Code
- Exécuter les commandes du projet dans Kali via PowerShell : `wsl -d kali-linux --cd /mnt/c/Users/ozgun/Bureau/SecureHorizons-Prep/vaultguard -- bash -lc "<cmd>"`.
  Attention : dans `bash -lc "..."` lancé depuis PowerShell, éviter `$var` (PowerShell l'interpole) et `#` (commentaire bash) — préférer un script `.sh`.
  Ne pas passer de chemins `/mnt/...` via l'outil Bash (Git Bash les réécrit) — ou préfixer `MSYS_NO_PATHCONV=1`.
  Fichiers écrits depuis Python Windows : `newline="\n"` (sinon CRLF, et les `.sh` cassent). Les gros heredocs dans
  l'outil Bash échouent parfois sur les guillemets : préférer l'outil Write.
- Après une modif : `bash scripts/test-all.sh --full`, et `bash scripts/security-audit.sh` si l'API ou le dashboard changent.
- Python avec web3 : `~/.venvs/vaultguard/bin/python` ; Foundry : `~/.foundry/bin/forge`.
- Le dashboard tourne sur http://localhost:8000 et peut être vérifié avec Claude in Chrome.
- **Depuis le 10 oct au soir : front et back fusionnés.** L'interface est `dashboard/workspace/` (servie sur `/app`,
  design du collègue Kanan, branchée sur `/api/app/*`) ; l'ancienne est sur `/app/classique`. Lire `docs/ETAT.md`
  (fait / pas fait) avant tout. Ne jamais remettre de style ou de script en ligne dans une page (CSP, test
  `test_layout`), ni de fonction d'interface sans équivalent serveur. Les `.bat` sont dans `lanceurs/`.
- Ozgun utilise aussi **Antigravity** sur ce projet : relire `git log` / l'état dans AGENTS.md §6 en début de session, et mettre §6 à jour en fin de tâche.
- Économie de tokens : lire seulement les parties utiles, pas de sous-agents sauf demande.
- **Hackathon en cours (10-11 oct), gel dim. 12h00.** En début de session : lire `docs/HACKATHON.md` (règles
  officielles, livrables, grille Track 1), puis la direction actuelle ci-dessous, puis AGENTS.md §6 si besoin de
  détail. Reste : vidéo, deck, fiche de défense, playbook, slide conformité (métriques faites).
- Règles qui tiennent depuis le 10 oct, quelle que soit la direction du pitch : zéro conservation du texte des
  factures (seulement des empreintes SHA-256) ; `/app` en langage simple, sans jargon (utilisateurs non
  informaticiens) ; rester centré Track 1 / Avalanche ; factures en euros (AVAX = jeton de démo). Détails :
  `docs/CONFIANCE-ARGENT-LEGAL.md`, `docs/EXPLIQUER-SIMPLEMENT.md`, `docs/INSTALLATION-CLIENT.md`.
- **Direction actuelle (10 oct, tard) : détection de fraude à la facture, positionnée comme module anti-fraude
  branché sur Pennylane (add-on), pas comme concurrent.** Historique complet (boîte mail → fraude électronique →
  mini-plateforme de facturation → add-on Pennylane) dans AGENTS.md §6 ; ne pas le relire en entier, juste la fin.
  **Lire en premier `docs/DETECTION-FRAUDE.md`**, puis `docs/PITCH.md` (déroulé en tête, remplace l'ancien).
  - Contrôles anti-fraude : `agent/fraud.py`, `agent/test_fraud.py`, `examples/fraudes_reelles.py` (25 cas sourcés :
    2 arrêts Cour de cassation 2026, La Banque Postale, DGCCRF, Supervizor, DAF Magazine), `transfers.audit_file`
    (contrôle d'un fichier de virements venu de n'importe quel logiciel). Démo : `lanceurs/ENVOYER-FRAUDES-DEMO.bat`.
  - Mini-plateforme de facturation (`agent/einvoice.py`, menu « 3. Factures émises », 11 tests) : émettre une
    facture électronique vers une autre entreprise par son SIREN, remise déjà contrôlée. Démo :
    `lanceurs/PREPARER-PLATEFORME-DEMO.bat`. Passée au second plan derrière l'angle « add-on Pennylane », gardée comme
    démonstration du principe « page + données produites ensemble ».
  - **Connecteur Pennylane non construit.** Vérifié dans leur doc API v2 (officielle, pas testée en vrai) :
    `GET /supplier_invoices` renvoie `public_file_url` (PDF) et `e_invoicing.source_file_url` (XML d'origine) —
    exactement ce que `fraud.layers` compare ; `GET /suppliers` donne `iban`/`reg_no`/`vat_number` ;
    `PUT .../e_invoice_status` (`approved`/`disputed`/`refused` + motif) permet d'écrire notre verdict dans
    Pennylane. Jeton : compte Essential+, rôle admin, bac à sable via « Test environment » ; intégration publique
    = OAuth 2.0 via integrations@pennylane.com. **Demander à l'équipe si quelqu'un a un compte Pennylane avant de
    construire le connecteur** ; sinon il ne peut être testé que contre un simulateur écrit d'après la doc.
  - Toute nouvelle règle de fraude : un cas dans `fraudes_reelles.corpus()` avec sa source, et une facture honnête
    qui lui ressemble. Ne jamais annoncer « 100 % » sans dire que le jeu d'essai est le nôtre ; le chiffre à citer
    est l'avant/après (7 fraudes payées sur 17 → 0, `docs/METRIQUES.md`).
  - Reste ouvert : la Track 1 ne cite explicitement que les axes 3 et 4 dans nos notes ; vérifier qu'un axe couvre
    bien la fraude aux paiements (pas trouvé de liste complète des axes dans le dossier).
- Le site tournant en local (`lanceurs/LANCER-DASHBOARD.bat`) utilise `CHAIN=web3` : un clic sur « Préparer le fichier de
  virements » ou « Sceller sur Avalanche » envoie une vraie transaction de test sur Fuji. Prévenir avant d'y toucher.
- Après une modification de `agent/*.py`, le site lancé par `lanceurs/LANCER-DASHBOARD.bat` doit être relancé pour la prendre
  en compte. Tester l'agent de factures sur une instance isolée (`DB_PATH` temporaire, autre `PORT`) : chaque refus
  compte pour le disjoncteur de la base de démo (clé en quarantaine à 5 refus en 1 h). Recréer la base de démo
  seulement si Ozgun le demande (`lanceurs/RECREER-DEMO.bat`, site arrêté : les identifiants changent).
- Démo locale : base de démo via `scripts/seed-demo-local.py`, serveur via `lanceurs/LANCER-DASHBOARD.bat` (port 8000).
  Ne jamais lire à voix haute / afficher `agent/data/COMPTES-DEMO.txt` ni `agent/.env` : renvoyer Ozgun au fichier.
- Vérifications de sécurité : passer par `scripts/security-audit.sh` et `scripts/test-all.sh --full` (contrôles
  existants, sur 127.0.0.1) et par la relecture de code, plutôt que d'enchaîner des outils d'attaque ad hoc en
  direct : ces sessions ont été coupées plusieurs fois par un filtre automatique.
- Chrome (Claude in Chrome) : le CAPTCHA des faucets, la création de wallet et l'approbation dans l'extension Core
  sont faits par Ozgun ; Claude peut ouvrir les pages, préremplir l'adresse publique Owner et vérifier GitHub Actions.
- Git : **le dépôt de travail est désormais `vg` = github.com/Xenolevrai/Vaultgard** (branche `main` ; `feat/dashboard`
  = front d'origine de Kanan). `origin` = github.com/Xenolevrai/SecureHorizon n'est plus qu'une sauvegarde.
  Pas de compte Pennylane dans l'équipe : ne pas construire le connecteur (voir `docs/ETAT.md` § « Sans Pennylane »). Avant chaque commit, vérifier
  qu'aucune valeur de `agent/.env` n'est indexée (script de comparaison, sans afficher les valeurs).
