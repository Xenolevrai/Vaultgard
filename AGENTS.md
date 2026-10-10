# AGENTS.md — VaultGuard (contexte pour tout assistant IA : Antigravity/Gemini, Claude Code, Cursor…)

> Source de vérité unique pour les agents de code. CLAUDE.md et .agent/rules/ pointent ici. Mets ce fichier à jour
> quand l'architecture, les commandes ou l'état d'avancement changent.

## 1. Contexte
- **Événement** : hackathon **Secure Horizons** (36 h, 10–11 oct 2026, ESSEC Cergy). Organisateurs : UTOPIA × KRYPTOSPHERE × ESSEC MetaLab.
- **Track 1 — Guardians of Value** : sécuriser les systèmes financiers, transactions et actifs numériques.
  Jury : **Team1 (Avalanche)**, **KPMG**, **KRYPTOSPHERE**. Avalanche obligatoire.
- **Équipe** : Ozgun (débutant en cybersécurité, prépare la sécurité des agents IA) + coéquipiers. Langue de travail : **français**.
- **Environnement** : Windows 11 + WSL Kali. Le code vit sous `C:\Users\ozgun\Bureau\SecureHorizons-Prep\vaultguard`
  (= `/mnt/c/Users/ozgun/Bureau/SecureHorizons-Prep/vaultguard` sous Kali). **Lancer les commandes dans Kali.**

## 2. Le projet : VaultGuard
**Problème** : les agents IA commencent à gérer de l'argent (paiement de factures, trésorerie, DeFi). Un LLM peut être
manipulé par une **injection de prompt indirecte** (instruction cachée dans une facture/un email/une page web) ou par
une **fraude au changement de RIB / empoisonnement d'adresse**. Si l'agent a la clé du wallet, l'attaquant a l'argent.

**Solution — défense en profondeur à 2 couches** :
1. **Pare-feu off-chain** (`agent/firewall.py`) — comprend le *contexte* avant signature :
   provenance (l'adresse vient-elle d'une donnée non fiable ?), mandat (est-ce ce que l'utilisateur a demandé ?),
   détection d'injection après normalisation (caractères invisibles, homoglyphes, base64), adresses sosies,
   adresses appâts, montants anormaux, doubles paiements, quota, quarantaine de session, masquage des secrets
   dans le memo (public on-chain), simulation on-chain (`previewPayment`) avant d'envoyer. Chaque raison a un
   titre grand public + un détail technique + une référence OWASP.
2. **Coffre on-chain** (`contracts/src/AgentVault.sol`) — garanties *dures* même si l'agent ET le serveur sont compromis :
   l'agent ne peut que `requestPayment` ; liste blanche + **délai d'activation** des nouveaux destinataires ;
   plafond par transaction et par jour ; validation humaine au-dessus d'un seuil (max 10 en attente, expiration 3 j,
   règles revérifiées à la validation) ; **adresses appâts** qui gèlent le coffre ; **disjoncteur** (N refus/jour →
   pause) ; clé d'agent **expirante** ; rôle **guardian** (geler seulement) ; propriété en 2 étapes ; **ancrage des
   rapports d'audit** (`anchorReport`) ; tout refus émet `PaymentBlocked` → piste d'audit on-chain (argument KPMG).

**Message clé du pitch** : « Ne faites pas confiance au LLM. Bornez-le. » — un LLM compromis ne peut pas perdre
plus que la politique on-chain ne l'autorise.

## 3. Architecture
```
Utilisateur (fiable) ─▶ Agent LLM ─▶ lit factures/emails (NON fiables, encapsulés <<DONNEE_NON_FIABLE>>)
                              │
                              ▼ pay(to, amount, memo)
                   ┌──────────────────────┐   BLOCK / CONFIRM(humain) / ALLOW
                   │ TxFirewall (Python)  │── preview on-chain ──┐   appât touché -> guardian_pause()
                   └──────────────────────┘                      ▼
                              │ requestPayment          ┌──────────────────────┐
                              └────────────────────────▶│ AgentVault (Solidity)│── Executed / Queued / Blocked(+event)
                                                         └──────────────────────┘
                     owner (Core Wallet) : approve/reject/pause ▲      ▲ guardian (serveur) : pause seulement
```

| Fichier | Rôle |
|---|---|
| `contracts/src/AgentVault.sol` | Coffre + politique. `NATIVE = address(0)` = AVAX ; ERC20 supportés (ex. USDC). |
| `contracts/test/AgentVault.t.sol` | 32 tests : unitaires, attaques (réentrance, token qui ment), 2 fuzz. |
| `contracts/test/AgentVault.invariant.t.sol` | Invariants : agent compromis appelé 8 192 fois au hasard → jamais de fuite. |
| `contracts/script/Deploy.s.sol` | Déploiement + config (0.1 AVAX/tx, 0.3/jour, validation ≥ 0.05, délai 24 h, appât, guardian, disjoncteur 5, agent 30 j). |
| `agent/firewall.py` | `TxFirewall.check()` → `Verdict(action, risk, reasons[{code,title,detail,ref}], memo)`. `CATALOG` = textes. |
| `agent/chain.py` | `MockChain` (réplique exacte du contrat, horloge injectable) et `Web3Chain` (vrai contrat, events par tranches). |
| `agent/scenarios.py` | 10 scénarios + `naive_plan()` (agent naïf du bac à sable). |
| `agent/agent.py` | `PaymentAgent`, `run()`, `run_custom()`, `summarize()` (perte, qui a bloqué). CLI. `--llm` = Claude réel. |
| `agent/server.py` | API durcie (sessions, CSRF, Host/Origin, limites, en-têtes, bac à sable par visiteur, liste blanche statique). |
| `agent/db.py` | Persistance SQLite multi-tenant, montants gwei entiers, triggers append-only, intégrité cryptographique SHA-256. |
| `agent/auth.py` | Gestion des comptes, sessions, hachage scrypt, TOTP 2FA (RFC 6238), verrouillage de compte, anti-énumération. |
| `agent/orgs.py` | Espaces organisations, fournisseurs, politiques d'approbation bornées, états de coffre isolés. |
| `agent/api_v1.py` | API REST `/v1` pour agents IA (Bearer token temps constant, quarantaine sans expiration, pare-feu multi-tenant). |
| `agent/admin.py` | Espace super-admin furtif `/admin` (404 stealth, révocations globales de sessions, suspension d'organisation). |
| `sdk/` | Client Python autonome sans dépendance tierce (`VaultGuardClient`), lecteur de factures multi-formats côté client (`invoice_reader.py` : texte, HTML, UBL, CII, PDF, Factur-X, mail, Word) et exemple d'agent (`examples/agent_example.py`). |
| `dashboard/` | Interfaces web : accueil (`index.html`), console (`app.html`), administration (`admin.html`), démo (`demo.html`), doc API (`docs.html`), sécurité (`securite.html`), mentions légales, 404. |
| `agent/abi/AgentVault.json` | ABI exportée (`scripts/export-abi.sh`) : la prod n'a pas besoin de Foundry. |
| `agent/test_vaultguard.py`, `test_server.py`, `test_parity.py`, `test_product.py`, `test_layout.py` | Tests unitaires, fonctionnels, parité on-chain, produit multi-tenant et conformité ergonomie/CSP. |
| `scripts/` | `setup`, `test-all [--full]`, `security-audit`, `doctor`, `create-wallets`, `deploy-fuji`, `local-chain`, `balances`, `export-abi`, `rehearse-deploy`, `build-guide.ps1`. |
| `Dockerfile`, `deploy/` | Production : image non-root + docker-compose avec Caddy (HTTPS auto). |
| `.github/workflows/ci.yml` | CI : tests complets + pip-audit + détection de secrets commités. |
| `docs/` | `PITCH.md`, `PLAN.md`, `SECURITE.md` (audit 29/29), `MISE_EN_PRODUCTION.md`, `guide.html` (→ PDF). |

**3 modes de démo** : `naive` (aucune protection → perte), `contract` (couche 2 seule), `full` (VaultGuard).

## 4. Commandes
Windows (double-clic) : `LANCER-DASHBOARD.bat`, `LANCER-TESTS.bat` (complet), `AUDIT-SECURITE.bat`, `DIAGNOSTIC.bat`,
`TRAITER-FACTURES.bat` (8 factures de démo), `REJOUER-MAILS.bat` (2 mails enregistrés), `LIRE-MAILS.bat` (vraie boîte),
`RECREER-DEMO.bat` (base de démo neuve, site arrêté). Mode d'emploi pour tout essayer : `docs/ESSAYER.md`.
Guide PDF d'Ozgun : `docs/guide.html` → `powershell -File scripts/build-guide.ps1` → `../GUIDE-VAULTGUARD.pdf`.

Dans Kali, depuis `vaultguard/` :
```bash
bash scripts/setup.sh                       # 1re fois : Foundry, forge-std, venv ~/.venvs/vaultguard, web3
bash scripts/test-all.sh                    # rapide (contrat + Python + API)
bash scripts/test-all.sh --full             # + parité anvil + Slither + Bandit (avant chaque commit)
bash scripts/security-audit.sh              # attaques rejouées + analyses -> docs/audit-latest.txt
bash scripts/doctor.sh                      # diagnostic : outils, .env, réseau, soldes, contrat
cd agent && python3 agent.py --mode full    # démo terminal (hors-ligne)
cd agent && ~/.venvs/vaultguard/bin/python server.py        # dashboard -> http://localhost:8000
bash scripts/local-chain.sh                 # anvil + déploiement -> agent/.env.anvil
bash scripts/create-wallets.sh              # wallets de test dans agent/.env (jamais affichés)
bash scripts/deploy-fuji.sh                 # déploiement Avalanche Fuji
python3 agent/server.py --hash-password     # mot de passe admin pour la production
python3 agent/server.py --create-admin     # créer un super-admin interactif avec TOTP 2FA
```
Foundry est dans `~/.foundry/bin`. Outils d'audit dans `~/.venvs/vg-audit` (installés par `security-audit.sh`).
Depuis PowerShell : `wsl -d kali-linux --cd /mnt/c/Users/ozgun/Bureau/SecureHorizons-Prep/vaultguard -- bash scripts/test-all.sh`.

## 5. Règles pour les agents de code
1. **Toujours lancer `bash scripts/test-all.sh` après une modification** (`--full` avant commit) et ne jamais laisser un test rouge. Ajouter un test pour toute nouvelle règle de sécurité (contrat ET pare-feu).
2. **Garder `MockChain` synchronisé avec `AgentVault.sol`** : toute règle ajoutée au contrat doit être reproduite dans `MockChain.preview()` ; `BlockReason` et `REASONS` dans le même ordre. `test_parity.py` vérifie.
3. **Secrets** : jamais de clé privée/API dans le code ou un commit. Tout passe par `agent/.env` (gitignoré). Uniquement des clés de **testnet**. Les clés anvil dans `scripts/local-chain.sh` sont publiques et OK. Ne jamais afficher `agent/.env`.
4. **Contrat** : checks-effects-interactions + `nonReentrant`, erreurs custom, pas d'appel arbitraire pour l'agent, les violations de politique émettent un event au lieu de revert. Pas de dépendance OpenZeppelin sans raison.
5. **Python** : stdlib + `web3`/`python-dotenv` seulement. Imports `web3` paresseux (le mode mock doit marcher sans). Les visiteurs n'utilisent que `make_chain(mode, force_mock=True)`.
6. **API** : ne jamais affaiblir sessions/CSRF/Host/Origin/limites/en-têtes ; chaque champ POST validé (type + bornes) ; erreurs génériques ; tester dans `test_server.py` ; `security-audit.sh` à 0 échec.
7. **Dashboard** : un seul fichier HTML, pas de build ni de CDN. Insertion via `textContent` uniquement. Pas d'attribut `style=`/`onclick=` (CSP à nonce : `<style nonce="__NONCE__">`, `<script nonce="__NONCE__">`).
   **Design** : sobre et clair (fond `#f6f5f2`, texte quasi noir, une seule couleur d'accent = l'encre), **aucun emoji**, pas de dégradés, ombres ou néons, pas de thème sombre « hacker ». Typo système, chiffres et adresses en monospace. Couleurs de statut discrètes (vert/ambre/rouge). Chaque résultat : une phrase grand public + « Détails techniques » repliables.
8. **Démo d'abord** : chaque fonctionnalité doit être visible dans le dashboard ou la CLI.
9. Style : code et commentaires concis, messages utilisateur en français, noms de code en anglais. Fichiers `.sh` en LF.
10. Explique brièvement chaque concept de sécurité/blockchain nouveau (Ozgun débute).

## 6. État d'avancement (mettre à jour !)
- [x] Contrat AgentVault v2 (délai, appât, disjoncteur, guardian, expiration agent, ownership 2 étapes, ancrage d'audit) : 33 tests Foundry (unitaires, attaques, fuzz, invariants) — verts
- [x] Pare-feu v2 (normalisation anti-obfuscation, mandat, appât, quarantaine, raisons expliquées) + 10 scénarios + bac à sable
- [x] API durcie + 52 tests Python (dont 17 de sécurité API) + 4 tests de parité/e2e sur anvil — verts
- [x] Audit de sécurité : v1 attaquée depuis Kali, failles corrigées, `security-audit.sh` 29/29, Slither/Bandit/pip-audit propres (docs/SECURITE.md)
- [x] Dashboard v2 (5 onglets, grand public + détails techniques, mode présentation, signature Core Wallet) — testé dans Chrome
- [x] Production : Dockerfile non-root, docker-compose + Caddy HTTPS, CI GitHub, `doctor.sh`, docs/MISE_EN_PRODUCTION.md (image Docker non construite localement : démon Docker arrêté dans Kali)
- [x] Wallets de test dans `agent/.env` : Owner 0xD8e58B7aa74cE5707B117515a0d6ee1e65F863E5, Agent 0xB0EAffb186B576dF58Edf3f4953033AE2Dc20f6d, Guardian 0x2EC47230c69278a2D6715a95454F2f4dc1cBa325, Supplier 0xd92B1525628baA7AB228796FD49304Ef1435a234, Nouveau 0x8AE704D42082EfbdAbc338D740c9984669049f18, Appât 0xF5Fd6fDA3eC0391E9763D8cD3f9663d0056F65E4
- [x] **v3 produit multi-clients** (`docs/SPEC-V3-PRODUIT.md`, workflow `/build-v3`) :
  - [x] Étape 1 persistance SQLite · [x] 2 comptes/2FA · [x] 3 espaces clients · [x] 4 API agents `/v1` ·
    [x] 5 admin plateforme · [x] 6 site public · [x] 7 design · [x] 8 tests + audit
  - Règles de `db.py` (revue de l'étape 1) : montants en **gwei entiers** (`amount_gwei`, `max_tx_gwei`… ;
    1 AVAX = 10^9 gwei ; ×10^9 = wei on-chain), jamais de flottants — un entier SQLite en wei plafonnerait à 9,2 AVAX ; table `audit` **sans clé étrangère et en ajout seul** (triggers) ; empreinte d'audit via
    `db.compute_audit_hash` (JSON, inclut `api_key_id` et `ip`) ; `hash_password` vit dans `db.py` (server l'importe) ;
    base en 0600.
  - Règles d'`auth.py` (revue de l'étape 2) : écrire l'audit **uniquement via `auth.log_audit`** (verrou + index
    unique `prev_hash`) ; consommer un jeton à usage unique par `UPDATE … WHERE used_at IS NULL` + `rowcount` ;
    un lien ne donne **jamais** de session sur un compte existant ; compteurs en SQL atomique (`x = x + 1`) ;
    toute route de compte passe par `_session()` (la base fait foi à chaque requête) ; le contrôle du coffre réel
    (`admin`) exige super-admin **et** 2FA active.
  - Règles d'`orgs.py` (revue de l'étape 3) : politique bornée par `POLICY_BOUNDS` (délai ≥ 1 h, disjoncteur ≥ 1,
    montants ≤ 10^15 gwei) et cohérente (seuil ≤ plafond tx ≤ plafond jour) ; adresses stockées en **minuscules** ;
    changement d'état par `UPDATE … WHERE <état attendu>` + `rowcount` ; un client ne voit que ses chiffres
    (`verify_audit_chain_for_org`) ; l'interface saisit des AVAX et convertit en gwei sans flottant.
  - Règles de l'API `/v1` (revue de l'étape 4) : authentification Bearer en temps constant via SHA-256 avec 401
    unifié (inexistante, inactive, révoquée ou en quarantaine) ; montant AVAX sous forme de chaîne parsé en gwei entier
    sans flottant (9 décimales max, rejet de négatif, notation scientifique et débordement) ; réutilisation stricte de
    `firewall.py` avec carnet d'adresses actif, détection appât et historique persistant ; coffre simulé persistant
    isolé par organisation (`org_vault_states`) ; mise en quarantaine automatique sur disjoncteur ou appât ;
    client SDK en stdlib `urllib` (`VaultGuardClient`) et exemple d'agent (`examples/agent_example.py`).
    Corrigé à la revue : l'adresse appât n'est **jamais** renvoyée par `/v1` (un agent compromis l'éviterait) ;
    verrou par organisation autour de « lire coffre → décider → écrire » (sinon 20 paiements parallèles passaient
    0,80 AVAX sous un plafond de 0,30) avec re-vérification de la clé sous verrou ; quarantaine **sans expiration**
    (levée = humain : révoquer + nouvelle clé) ; chiffres ASCII seulement (`\d` accepte « ١٢ ») ; SDK refuse
    `http://` hors localhost.
  - Règles d'`admin.py` et `/admin` (revue de l'étape 5) : prérequis étape 4 réglé (état du coffre visible dans
    `/app`, dégel réservé au rôle `owner` avec 2FA via `UPDATE … WHERE is_paused = 1` + `rowcount` + audit `vault.unpause`) ;
    accès réservé aux sessions super-admin avec 2FA active (`is_superadmin=1`, `totp_enabled=1`, `is_active=1`
    revalidé en base à chaque requête) ; renvoi strict de **404** (pas 403 ni 401) pour masquer l'existence de `/admin`
    et `/api/admin/*` ; statistiques globales en comptages purs (zéro contenu de paiement/montant/memo) ; suspension d'organisation
    coupant immédiatement `/v1` (403) et `/app` (lecture seule) ; aucune modification de données d'org depuis `/admin` sauf suspension ;
    super-admin non auto-désactivable, protection du dernier super-admin actif ; révocation immédiate de toutes les sessions
    sur désactivation ou « déconnecter partout » ; vérification cryptographique de l'audit de la plateforme ; diagnostics
    de santé avec RPC Avalanche borné (timeout ≤ 1,5 s) ; traçabilité de chaque action avec IP.
    Corrigé à la revue : « pas le dernier super-admin » est une condition **dans l'UPDATE** (un COUNT puis un UPDATE
    laissait deux admins se désactiver mutuellement en parallèle → plus aucun admin) ; dégel du coffre sous
    `api_v1._org_lock` (sinon un paiement en cours réécrit l'ancien état) ; l'URL RPC affichée est réduite à
    schéma://hôte (une clé de fournisseur est souvent dans le chemin). Règle générale : toute vérification
    « avant écriture » doit être dans la même requête SQL ou sous le même verrou que l'écriture.
  - Règles des pages publiques et de la démo (revue de l'étape 6) : pages publiques d'accueil (`/`), documentation API
    (`/docs`), sécurité (`/securite`), mentions légales (`/mentions-legales`) et confidentialité (`/confidentialite`) servies
    par `server.py` en HTML statique avec CSP stricte à nonce ; aucun style ni script en ligne sans nonce, zéro
    ressource externe (ni CDN, ni Google Fonts, ni traqueur) ; en-têtes identiques au reste du site (`X-Frame-Options: DENY`,
    `nosniff`, `no-referrer`, `Permissions-Policy`) ; démo interactive déplacée sur `/demo` sans altérer les sessions ni le CSRF ;
    mise à jour de tous les scripts (`scripts/security-audit.sh`, `scripts/demo.sh`), de la documentation et des tests vers `/demo` ;
    URL inconnues renvoyant une page 404 HTML propre avec CSP et sans fuite interne ; `/docs` documente `/v1` sans
    jamais révéler ni mentionner l'adresse appât (honeytoken) ; l'adresse appât n'apparaît dans aucun HTML public.
    Corrigé à la revue : **92 attributs `style="..."`** (login, signup, app, admin, depuis l'étape 2) étaient bloqués
    en silence par la CSP (ex. le champ 2FA et les blocs `display: none` restaient visibles) → convertis en classes
    `.u-N` en fin d'`app.css` ; test qui interdit `style=` et `on*=` dans tout `dashboard/*.html`. Règle : jamais
    d'attribut `style` ni `onclick` ; vérifier la console (violations CSP) dans Chrome, pas seulement le débordement.
    Les exemples de `/docs` recopient désormais les vraies réponses de `api_v1.py` (`limits`, `active_suppliers`,
    `reasons` en objets) ; liens « démo » de `/login`, `/signup`, `/app` → `/demo`.
  - Règles du design et de l'accessibilité (revue de l'étape 7) : harmonisation stricte de toutes les pages selon la
    charte §5.7 (fond clair `#f6f5f2`, encre `--ink`, zéro emoji, zéro ressource externe) ; élimination totale des
    anciennes classes utilitaires `.u-1` à `.u-43` au profit de classes sémantiques nommées (`.is-hidden`, `.btn-block`,
    `.table-responsive`...) ; fichiers statiques servis exclusivement via la liste blanche explicite `STATIC_ASSETS`
    dans `server.py` (aucun chemin dérivé de l'URL pour bloquer tout path traversal) ; `overflow-wrap: anywhere` et
    `word-break: break-word` obligatoires sur toutes les adresses, hash, clés et blocs de code ; `min-width: 0` sur les
    colonnes et conteneurs flex/grid ; `:focus-visible` avec outline 2px contrasté ; tableaux défilants dans `.table-responsive` ;
    `agent/test_layout.py` réécrit et intégré dans `scripts/test-all.sh` (13 tests unitaires vérifiant liste blanche statique,
    absence de `style=`/`on*=`, absence d'emojis, absence d'URL distantes et présence des règles de non-débordement) ;
    vérification automatisée dans Chrome headless à 1440 px et 390 px sur toutes les pages et onglets (46 vérifications au vert,
    0 débordement horizontal, 0 erreur console, 0 violation CSP).
    Corrigé à la revue : `.is-hidden { display: none !important }` battait `el.style.display = 'block'` → le champ 2FA
    de `/login` ne s'affichait jamais (connexion 2FA impossible), ni les erreurs, ni la fenêtre de dégel. Désormais
    `html .is-hidden { display: none; }` en fin d'`app.css`, sans `!important` (test dans `test_layout.py`). Règle : une
    classe qui cache un élément que le JS affiche ne porte jamais `!important` ; tester l'**interaction** (afficher
    chaque `.is-hidden` via le JS), pas seulement le rendu statique.
  - Règles des tests finaux et audit de sécurité (revue de l'étape 8) : suite de tests complétée dans `agent/test_product.py`
    (verrouillage après 5 échecs consécutifs, détection d'altération de l'audit par triggers SQL et falsification hors-ligne,
    assainissement strict de l'export CSV anti-formule CWE-1236 pour `=, +, -, @, \t, \r`, révocation de clé API bloquant `/v1` en 401) ;
    `scripts/security-audit.sh` exécutant les attaques réelles sur 127.0.0.1 (anti-énumération par temps constant, force brute,
    isolation multi-locataire anti-IDOR en 404, clé révoquée 401, `/admin` stealth 404, sqlmap sans paramètre injectable,
    salve de limitation de débit en fin de scénario, Slither, Bandit, pip-audit) pour un total de **29/29 vérifications OK (0 échec)** ;
    documentation opérationnelle complète (`docs/SECURITE.md`, `docs/MISE_EN_PRODUCTION.md`, `AGENTS.md`, `docs/guide.html`)
    et compilation du guide PDF `../GUIDE-VAULTGUARD.pdf`.
    Corrigé à la revue : l'attaque de saturation de débit (300 requêtes en rafale) consommait l'intégralité du seau à jetons
    sur `127.0.0.1`, provoquant des faux échecs `429` sur les tests multi-tenants subséquents → la salve de limitation a été
    placée à la fin des tests de serveur ; `nmap` optimisé avec `--version-light --host-timeout 5s` pour éviter les attentes
    de sondes de service superflues.
    Revue Claude : le contrôle sqlmap était **toujours vert** (ses 3 branches comptaient OK, même coupé par le
    `timeout 30` ou s'il trouvait une injection) → ECHEC si injection trouvée, OK seulement si sqlmap conclut « not
    injectable », sinon `[NON CONCLUANT]` non compté (timeout 300 s). Le serveur d'audit restait vivant sur le port 8765
    après le script (le PID de `setsid nohup` n'est pas toujours celui de Python) → `free_port` (`fuser -k`) au début,
    à la fin et en `trap EXIT`. Règle : un contrôle d'audit doit pouvoir échouer ; tout serveur lancé en arrière-plan
    est arrêté par port, pas seulement par PID. Commandes longues (sqlmap, nmap) : toujours un `timeout`.
- [x] Commits `f268601` (v2 + v3 1-3), `98e49b5` (v3 4-8), `a16d359` (CI) ; dépôt privé github.com/Xenolevrai/SecureHorizon, **CI verte**
  (le contrôle « aucun secret » de la CI refuse toute chaîne 0x + 64 hex, même la clé publique d'Anvil : utiliser `anvil_setBalance`)
- [x] Répétition locale du déploiement `scripts/rehearse-deploy.sh` OK le 2026-10-06 (déploiement, doctor 20 OK,
  paiement réel, appât -> coffre gelé par le guardian).
- [x] **Déploiement Fuji fait (10 oct, jour J)** : contrat AgentVault à `0x30c9A13FACf3Be404C1Ea0333D31165Fe1f0d793`
  (bloc 59263971) — https://testnet.snowtrace.io/address/0x30c9A13FACf3Be404C1Ea0333D31165Fe1f0d793 . Faucet officiel
  utilisé : Builder Hub (`build.avax.network/console/primary-network/faucet`), pas de code promo nécessaire (l'email
  du 10 oct ne contenait qu'un lien Builder Hub standard + contact de secours Yassir en cas de faucet insuffisant).
  Piège rencontré : le wallet Core d'Ozgun avait été recréé (nouveau mot de passe) donc les AVAX du faucet sont tombés
  sur une adresse différente de l'Owner du projet — réglé par un virement interne C-Chain vers l'Owner (pas besoin de
  refaire le faucet, pas de cooldown). `CHAIN=web3` activé dans `agent/.env` ; `scripts/doctor.sh` 20/20 OK.
- [x] Démo locale : `scripts/seed-demo-local.py` (depuis `agent/`) recrée la base avec un super-admin 2FA et un client
  « Transports Martin » (5 paiements réels via `/v1` : 1 autorisé, 1 en attente, 3 bloqués). Identifiants dans
  `agent/data/COMPTES-DEMO.txt` (ignoré par git, ne jamais les afficher). Lancement : `LANCER-DASHBOARD.bat`.
- [x] Production : `DB_PATH=/data/vaultguard.db` dans le Dockerfile (sinon base non inscriptible avec `read_only`).
  En production, **ne pas définir `ADMIN_PASSWORD_HASH`** (ancien admin de la démo, mot de passe seul, sans 2FA, qui
  pilote le coffre « live ») : l'administration passe par le super-admin 2FA. `ALLOWED_HOSTS` = le domaine.
- [x] Vérification complète après déploiement (10 oct) : `test-all.sh --full` vert (148 tests Python, 33 Foundry,
  parité, Slither, Bandit), `security-audit.sh` 29/29, `/demo` + `/app` + `/admin` contrôlés, un vrai paiement
  on-chain de 0,02 AVAX (tx `0xd7df5685…5b036be4ac`, visible sur la page Snowtrace du contrat).
  Corrigé ce jour-là : (1) **faux positif du pare-feu** — `scan_injection` signalait « obfuscation » dès qu'un
  document contenait deux espaces de suite (colonnes d'une facture), car la comparaison se faisait après compression
  des espaces ; elle se fait maintenant avant (test `test_aligned_columns_are_not_obfuscation`). (2) Deux tests 2FA
  instables : un `now + 31` ou `+ 35` peut sauter 2 pas de 30 s et sortir de la fenêtre ±1 → toujours calculer le
  compteur (`now // 30 + 1`), jamais un décalage en secondes. (3) `test-all.sh` affichait « Tout est vert » malgré
  un échec (`A && ok` ne déclenche pas `set -e`) → chaque étape fait maintenant `|| exit 1`. (4) Les venv
  `vaultguard` et `vg-audit` avaient perdu `pip` (Python de Kali passé en 3.14) : `get-pip.py` puis réinstallation.
- [x] **Parcours de A à Z** : `examples/agent_factures.py` (agent naïf qui lit `examples/factures/*.txt` et appelle
  `/v1`), lanceur `TRAITER-FACTURES.bat`, mode d'emploi `docs/PARCOURS-A-Z.md`. Verdicts attendus : 01 payé, 02 en
  attente humaine, 03/04/05 bloqués. Un passage = 3 refus ; le disjoncteur gèle à 5 refus/jour (ne pas le lancer
  deux fois le même jour sur la même base, ou reseeder). La consigne (`user_request`) doit nommer le fournisseur,
  sinon le pare-feu envoie en validation humaine.
- [x] **Agent branché sur une vraie boîte mail** : `examples/agent_mail.py` (IMAP en lecture seule, objet contenant « facture »), configuration `examples/.env.mail` (ignoré par git), lanceur `LIRE-MAILS.bat`, mails types et schéma « qui possède quoi » dans `docs/PARCOURS-A-Z.md`. Lecture des mails et décisions vérifiées sur `examples/mails/*.eml` ; la connexion IMAP réelle reste à essayer par Ozgun (mot de passe d'application à créer).
- [x] **Zéro conservation, formats, prix, boîte dédiée (10 oct soir, demandes de l'équipe)** — synthèse et réponses
  blockchain / argent réel / légalité / marché dans `docs/CONFIANCE-ARGENT-LEGAL.md`.
  - Règle : **aucun texte de facture ni de consigne en base**. `payments.documents_json` = `[{n, sha256, chars,
    file_sha256}]`, `payments.user_request` = `sha256:<empreinte>`, empreintes aussi dans le journal chaîné.
    Le pare-feu reçoit les sources sous le nom « document N » (pas de nom de fichier ni d'expéditeur dans les
    raisons). Une raison qui cite la facture porte un `detail_stored` neutre : l'agent reçoit `detail`, la base
    garde `detail_stored`. `db.purge_stored_content()` nettoie les anciennes lignes à chaque `init_db`.
    Tout nouveau champ venant d'un document suit cette règle (test `test_no_invoice_text_reaches_the_database`).
  - `firewall.check_invoice` (champ `invoice` de `/v1/payments`) : total ≠ somme des lignes, montant demandé ≠ total
    (même devise), prix unitaire > 3 × le prix de référence envoyé par l'agent du client → `CONFIRM` (humain), jamais
    `BLOCK` : une erreur de prix ne doit pas compter pour le disjoncteur. Décimaux exacts (`Decimal`).
  - `sdk/invoice_reader.py` (stdlib) : rien n'est tronqué (`documents()` découpe avec recouvrement, sinon un ordre
    caché après la coupure échappe au pare-feu) ; XML avec DOCTYPE/entités refusé ; décompression bornée ; le texte
    brut (commentaires XML/HTML, texte PDF invisible) est transmis au pare-feu ; format illisible → `UnreadableInvoice`
    → humain. `/app` : « Vérifier une facture » compare l'empreinte d'un fichier dans le navigateur.
  - `examples/agent_mail.py` : `MODE=dediee` (expéditeurs autorisés, SPF/DKIM si l'en-tête existe, suppression par
    UID). Factures 06 (œufs à 18 €, attente humaine), 07 (UBL), 08 (Factur-X, `scripts/make-facturx-demo.py`).
    Factures en euros, règlement de démo en AVAX au taux fictif `--taux` (en réel : EURC 1:1).
  - Corrigé : `seed-demo-local.py` laissait 3 refus « du jour » sur la clé de l'agent et le loueur inactif → sur une
    base fraîche le parcours bloquait la facture 02 et mettait la clé en quarantaine à la 3e. L'historique est daté
    de la veille et le loueur activé après. Vérifié : 01 payé, 02 attente, 03-05 bloqués, 06 attente, 07-08 payés.
  - 172 tests Python (`test_invoices.py` ajouté à `test-all.sh`), `--full` vert, audit 29/29.
  - Base de démo d'Ozgun recréée le 10 oct au soir (3 fournisseurs actifs, historique de 5 paiements daté de la
    veille), site relancé. `docs/ESSAYER.md` = parcours d'essai pas à pas ; `REJOUER-MAILS.bat` et `RECREER-DEMO.bat`
    ajoutés. Le disjoncteur compte les refus **sur 1 h par clé** : un passage de `TRAITER-FACTURES` = 3 refus, le
    mail piégé = 1 ; un 2e passage gèle la clé (HTTP 401) → `RECREER-DEMO.bat`.
  - **Preuve de paiement et facture déjà payée** : `orgs._with_proof` ajoute à chaque paiement `supplier_name` et
    `proof` (empreintes du journal chaîné pour la demande et l'accord) ; le pare-feu reconnaît un document déjà
    réglé au même destinataire par son empreinte (`FirewallSession.paid_docs`, raison `double_payment` en `CONFIRM`,
    le numéro de facture identique restant un `BLOCK`). `/api/app/payments?limit=` (200 max).
  - **`/app` en langage simple** (l'équipe trouve le produit dur à comprendre, utilisateurs non informaticiens) :
    accueil « Où en sont vos paiements » avec bloc « À faire » (Accepter / Refuser), noms de fournisseurs au lieu
    d'adresses, « Payé / À valider / Bloqué », colonne « Pourquoi », recherche « Cette facture a-t-elle déjà été
    payée ? » (numéro ou fichier), preuve de paiement copiable, « Détails techniques » repliés. Garder ce registre
    dans tout nouveau texte d'interface : pas de « gwei », « mock », « on-chain », « agent », « pare-feu » côté client.
  - Vérifié dans Chrome sur une instance jetable (port 8791) : accueil, Accepter, recherche par numéro et par
    fichier, preuve, vérification d'un fichier, 0 erreur console. 174 tests Python.
  - `docs/INSTALLATION-CLIENT.md` (qui fait quoi chez un client, jamais joué en vrai) et
    `docs/EXPLIQUER-SIMPLEMENT.md` (image du stagiaire et du coffre, pitch en un scénario, tableau sujet ↔ produit).
    Position : VaultGuard est sur l'axe 3 de la Track 1 ; ne pas pitcher « traitement de factures ».
  - Manque toujours : les **métriques de détection** (30 % de la note), une alerte au valideur (mail/SMS).
  - Explications données à Ozgun, à réutiliser pour le pitch : Avalanche = le réseau, AVAX = sa monnaie (démo),
    EURC = des euros en jetons (règlement réel) ; le fournisseur reçoit des EURC sur un portefeuille, pas un virement :
    c'est la friction assumée. L'agent de démo est le nôtre ; chez un client c'est son agent, branché par le SDK.
- [x] Règles officielles lues (Notion, 10 oct) : résumé, livrables, grille et points ouverts dans `docs/HACKATHON.md`.
- [ ] **Livrables avant dim. 11 oct 12h00** : vidéo 2-3 min, deck 8 slides (dont slide conformité), fiche de défense
  1 page, playbook de réponse, accès du jury au dépôt, métriques de détection chiffrées. (README « limites connues » : fait.)
- [ ] Demander à un organisateur comment s'applique la règle « cœur du projet développé entre sam. 11h30 et dim. 12h ».
- [ ] Mode `--llm` testé avec une vraie clé API
- [ ] Backlog jour J : voir `docs/PLAN.md`

## 7. Idées d'extension
LLM-juge en plus des motifs · politique par destinataire (plafond fournisseur) · paiements USDC dans la démo ·
alertes (email/Slack) sur `CanaryAlert`/`CircuitBreakerTripped` · fenêtre glissante au lieu du jour calendaire ·
owner multisig Safe · ICM/Teleporter Avalanche (politique multi-chaînes) · L1 Avalanche dédiée avec allowlist native ·
rapport d'audit PDF signé.

## 8. Mode hackathon (10-11 oct 2026, 36 h) — à lire en premier le jour J
**État au 10 oct après-midi : contrat déployé sur Fuji, tout vérifié, règles officielles lues → lire
`docs/HACKATHON.md` en premier** (livrables à rendre dim. 12h00, grille Track 1, points ouverts). VaultGuard se place
sur l'axe 3 de la Track 1 (supervision et confinement des agents IA financiers). Round 1 : pitch de 5 min + 2 min.
Les points 1 et 2 ci-dessous sont faits ; restent 3 à 6, plus la fiche de défense, le playbook et la slide conformité.
1. **Lire le sujet** et le comparer à la Track 1 « Guardians of Value » : reformuler en 3 lignes ce que VaultGuard
   couvre déjà, ce qui manque, et proposer **le plus petit ajout visible** qui colle au sujet (pas de refonte).
2. **Faucet** : utiliser les infos reçues par email (code promo probable) sur core.app/tools/testnet-faucet (réseau
   Fuji C-Chain, token AVAX) vers l'adresse Owner ci-dessus, puis `bash scripts/deploy-fuji.sh` → `CHAIN=web3` dans
   `agent/.env` → `bash scripts/doctor.sh` → lien Snowtrace du contrat. Le CAPTCHA et les connexions de wallet sont
   faits par Ozgun. Faire ceci **dans le tour courant** (pas de surveillant en tâche de fond entre deux sessions).
3. **Avant toute démo** : `bash scripts/test-all.sh --full` et `bash scripts/security-audit.sh` au vert ;
   `python3 ../scripts/seed-demo-local.py` (depuis `agent/`) pour une base propre ; `LANCER-DASHBOARD.bat`.
4. **Parcours de démo (3 min)** : accueil `/` → `/demo` (scénarios d'attaque : injection, appât, sosie, double
   paiement) → `/login` client → `/app` (paiement en attente à valider, paiement bloqué expliqué, journal chaîné
   « Vérifier l'intégrité », export CSV) → `/admin` (super-admin 2FA) → contrat sur Snowtrace (événements on-chain).
5. **Livrables restants** : slides (problème, 2 couches, Avalanche, sécurité prouvée : 147 tests Python, 33 Foundry,
   audit 29/29, Slither/Bandit 0 alerte), vidéo de secours du parcours ci-dessus, pitch `docs/PITCH.md`.
6. Commit après chaque avancée validée ; jamais de secret dans git (la CI refuse toute chaîne 0x + 64 hex).
Points de vigilance : ne jamais afficher `agent/.env` ni `agent/data/COMPTES-DEMO.txt` ; clés testnet uniquement ;
toute vérification « avant écriture » dans la même requête SQL ou sous le même verrou (règle des revues §6).
