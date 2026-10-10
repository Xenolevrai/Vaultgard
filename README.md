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
Une entreprise, un agent IA, huit factures (texte, XML, PDF Factur-X) dont trois piégées et une au prix anormal :
`TRAITER-FACTURES.bat` (ou `python3 examples/agent_factures.py --pause`), puis http://localhost:8000/app.
Explications : `docs/PARCOURS-A-Z.md`.

## Données du client
VaultGuard ne conserve aucun texte de facture ni de consigne : analyse en mémoire, puis empreinte SHA-256 seulement.
Pas de service d'IA tiers : le pare-feu est un moteur de règles, le lecteur de factures (`sdk/invoice_reader.py`)
tourne chez le client. Argent réel, confiance, légalité, marché : `docs/CONFIANCE-ARGENT-LEGAL.md`.

## Limites connues
- Réseau de test uniquement ; contrat non audité par un tiers.
- Les factures sont en euros mais la démo règle en AVAX de test (taux fictif) ; le règlement en euro numérique
  (EURC) et la conversion vers un virement SEPA ne sont pas construits.
- PDF scannés, chiffrés ou à polices exotiques : non lus, renvoyés à un humain. Images : OCR `tesseract` optionnel.
- Le contrôle des prix s'appuie sur une liste tenue par le client : il attrape les erreurs, pas un agent
  entièrement compromis. Les bornes dures sont celles du contrat.
- Sur une chaîne publique, adresses et montants sont visibles : une L1 Avalanche dédiée est la réponse prévue.
- Le texte des factures transite en mémoire sur le serveur : pour l'éviter, installer VaultGuard chez le client.
- Pas de filtrage des listes de sanctions, pas de connecteur vers une plateforme de facturation agréée.

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
`AGENTS.md` (contexte technique) · `docs/HACKATHON.md` (règles, livrables, grille) · `docs/PARCOURS-A-Z.md` · `docs/CONFIANCE-ARGENT-LEGAL.md` · `docs/PITCH.md` · `docs/SECURITE.md` · `docs/MISE_EN_PRODUCTION.md` · `docs/PLAN.md` ·
guide complet : `../GUIDE-VAULTGUARD.pdf`.

Réseau de test uniquement. Contrat non audité par un tiers : ne pas utiliser avec de vrais fonds.
