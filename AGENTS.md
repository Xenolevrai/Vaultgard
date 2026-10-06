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
| `agent/server.py` | API durcie (sessions, CSRF, Host/Origin, limites, en-têtes, bac à sable par visiteur, admin par mot de passe). |
| `agent/abi/AgentVault.json` | ABI exportée (`scripts/export-abi.sh`) : la prod n'a pas besoin de Foundry. |
| `agent/test_vaultguard.py`, `test_server.py`, `test_parity.py` | Unitaires + fonctionnels / sécurité API / parité simulation↔contrat sur anvil. |
| `dashboard/index.html` | 5 onglets : Démonstration, Comparer, Bac à sable, Coffre, Comprendre. CSP à nonce, signature Core Wallet. |
| `scripts/` | `setup`, `test-all [--full]`, `security-audit`, `doctor`, `create-wallets`, `deploy-fuji`, `local-chain`, `balances`, `export-abi`, `rehearse-deploy`, `build-guide.ps1`. |
| `Dockerfile`, `deploy/` | Production : image non-root + docker-compose avec Caddy (HTTPS auto). |
| `.github/workflows/ci.yml` | CI : tests complets + pip-audit + détection de secrets commités. |
| `docs/` | `PITCH.md`, `PLAN.md`, `SECURITE.md` (audit avant/après), `MISE_EN_PRODUCTION.md`, `guide.html` (→ PDF). |

**3 modes de démo** : `naive` (aucune protection → perte), `contract` (couche 2 seule), `full` (VaultGuard).

## 4. Commandes
Windows (double-clic) : `LANCER-DASHBOARD.bat`, `LANCER-TESTS.bat` (complet), `AUDIT-SECURITE.bat`, `DIAGNOSTIC.bat`.
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
- [x] Audit de sécurité : v1 attaquée depuis Kali, failles corrigées, `security-audit.sh` 19/19, Slither/Bandit/pip-audit propres (docs/SECURITE.md)
- [x] Dashboard v2 (5 onglets, grand public + détails techniques, mode présentation, signature Core Wallet) — testé dans Chrome
- [x] Production : Dockerfile non-root, docker-compose + Caddy HTTPS, CI GitHub, `doctor.sh`, docs/MISE_EN_PRODUCTION.md (image Docker non construite localement : démon Docker arrêté dans Kali)
- [x] Wallets de test dans `agent/.env` : Owner 0xD8e58B7aa74cE5707B117515a0d6ee1e65F863E5, Agent 0xB0EAffb186B576dF58Edf3f4953033AE2Dc20f6d, Guardian 0x2EC47230c69278a2D6715a95454F2f4dc1cBa325, Supplier 0xd92B1525628baA7AB228796FD49304Ef1435a234, Nouveau 0x8AE704D42082EfbdAbc338D740c9984669049f18, Appât 0xF5Fd6fDA3eC0391E9763D8cD3f9663d0056F65E4
- [ ] **v3 produit multi-clients** (`docs/SPEC-V3-PRODUIT.md`, workflow `/build-v3`) :
  - [x] Étape 1 persistance SQLite · [x] 2 comptes/2FA · [x] 3 espaces clients · [ ] 4 API agents `/v1` ·
    [ ] 5 admin plateforme · [ ] 6 site public · [ ] 7 design · [ ] 8 tests + audit
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
    `agent/test_layout.py` est cassé (importe `get_db`, inexistant) et non lancé : à réécrire ou supprimer à l'étape 7.
- [ ] Faucet Fuji sur Owner puis `bash scripts/deploy-fuji.sh` + `doctor.sh` + vérification sur Snowtrace
- [ ] Premier commit + dépôt GitHub (CI verte)
- [ ] Slides + vidéo de secours
- [ ] Mode `--llm` testé avec une vraie clé API
- [ ] Backlog jour J : voir `docs/PLAN.md`

## 7. Idées d'extension
LLM-juge en plus des motifs · politique par destinataire (plafond fournisseur) · paiements USDC dans la démo ·
alertes (email/Slack) sur `CanaryAlert`/`CircuitBreakerTripped` · fenêtre glissante au lieu du jour calendaire ·
owner multisig Safe · ICM/Teleporter Avalanche (politique multi-chaînes) · L1 Avalanche dédiée avec allowlist native ·
rapport d'audit PDF signé.
