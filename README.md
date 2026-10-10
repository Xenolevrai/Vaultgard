# VaultGuard

**Pare-feu de paiements pour agents IA, sur Avalanche.** Hackathon Secure Horizons 2026 — Track 1 « Guardians of Value ».

Un agent IA qui paie des factures peut être manipulé par une instruction cachée dans un document (injection de
prompt), une adresse sosie ou une fausse demande de changement de RIB. VaultGuard le borne en deux couches
indépendantes :

1. **Pare-feu off-chain** : comprend le contexte avant de signer. D'où vient l'adresse ? Est-ce le mandat de
   l'utilisateur ? Le texte cache-t-il des instructions, même camouflées ? Un secret va-t-il fuiter dans le memo ?
2. **Coffre on-chain** (`AgentVault`, Avalanche C-Chain) : liste blanche avec délai d'activation, plafonds par
   transaction et par jour, validation humaine, adresses appâts qui gèlent le coffre, disjoncteur automatique,
   clé d'agent expirante, guardian, journal et rapports d'audit scellés. Ces règles tiennent même si l'IA **et**
   le serveur sont compromis.

> « Ne faites pas confiance au LLM. Bornez-le. »

## Déploiement Fuji
Contrat `AgentVault` : [`0x30c9A13FACf3Be404C1Ea0333D31165Fe1f0d793`](https://testnet.snowtrace.io/address/0x30c9A13FACf3Be404C1Ea0333D31165Fe1f0d793)
(Avalanche Fuji C-Chain, testnet, bloc 59263971).

## Démarrer
Windows : double-clic sur `LANCER-DASHBOARD.bat` → démo sur http://localhost:8000/demo (accueil sur http://localhost:8000).

Kali / Linux :
```bash
bash scripts/setup.sh            # une fois
bash scripts/test-all.sh --full  # contrat, agent, API, parité blockchain, analyse statique
bash scripts/security-audit.sh   # attaques rejouées sur 127.0.0.1 -> docs/audit-latest.txt
bash scripts/doctor.sh           # diagnostic de la configuration
cd agent && ~/.venvs/vaultguard/bin/python server.py
```

## Parcours de A à Z (factures)
Une entreprise, un agent IA, cinq factures dont trois piégées : `TRAITER-FACTURES.bat` (ou
`python3 examples/agent_factures.py --pause`), puis http://localhost:8000/app. Explications : `docs/PARCOURS-A-Z.md`.

## Tests et sécurité
| Suite | Contenu |
|---|---|
| Foundry | 32 tests (unitaires, réentrance, token non standard, contrôle d'accès) + 2 fuzz + 4 invariants (8 192 appels d'un agent compromis) |
| Python | 35 tests pare-feu / simulation / scénarios + 17 tests de sécurité de l'API (CSRF, DNS rebinding, DoS, validation, sessions, brute force) |
| Parité | 4 tests sur blockchain locale : la simulation prend exactement les mêmes décisions que le contrat + bout en bout |
| Audit | 19 attaques rejouées, Slither, Bandit, pip-audit — voir `docs/SECURITE.md` |

## Production
`Dockerfile` (non-root) + `deploy/docker-compose.yml` (Caddy, HTTPS automatique) + CI GitHub.
Guide : `docs/MISE_EN_PRODUCTION.md`. En production, la clé owner n'est jamais sur le serveur : l'owner signe avec Core Wallet.

## Documentation
`AGENTS.md` (contexte technique) · `docs/HACKATHON.md` (règles, livrables, grille) · `docs/PARCOURS-A-Z.md` · `docs/PITCH.md` · `docs/SECURITE.md` · `docs/MISE_EN_PRODUCTION.md` · `docs/PLAN.md` ·
guide complet : `../GUIDE-VAULTGUARD.pdf`.

Réseau de test uniquement. Contrat non audité par un tiers : ne pas utiliser avec de vrais fonds.
