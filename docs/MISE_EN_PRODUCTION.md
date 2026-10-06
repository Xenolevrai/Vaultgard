# Mise en production de VaultGuard

Trois niveaux, du plus simple au plus sérieux. Pour le hackathon, le **niveau 1** suffit ; le **niveau 2** donne une
URL publique à montrer au jury ; le **niveau 3** est ce qu'il faudrait pour de vrais fonds.

## Niveau 1 — Démo locale sur Avalanche Fuji (hackathon)
1. `bash scripts/create-wallets.sh` (déjà fait).
2. Faucet Fuji sur l'adresse Owner (≈ 1 AVAX de test).
3. `bash scripts/deploy-fuji.sh` → déploie, configure (liste blanche, délai, appât, guardian, disjoncteur), finance.
4. Dans `agent/.env` : `CHAIN=web3`.
5. `bash scripts/doctor.sh` → 0 erreur.
6. `LANCER-DASHBOARD.bat` → onglet Coffre → « Vrai coffre » : contrat visible sur Snowtrace.

## Niveau 2 — URL publique (VPS + Docker + HTTPS)
Il faut : un petit serveur Linux (VPS, ~5 €/mois : OVH, Scaleway, Hetzner…) et un nom de domaine (ou sous-domaine)
qui pointe vers son IP (enregistrement DNS de type A).

Sur le serveur :
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
git clone https://github.com/<ton-compte>/vaultguard.git && cd vaultguard
python3 agent/server.py --hash-password          # tape un mot de passe admin (12+ caractères) -> copie la ligne
cp .env.example deploy/.env.prod && nano deploy/.env.prod
```
Dans `deploy/.env.prod` :
```
CHAIN=web3
RPC_URL=https://api.avax-test.network/ext/bc/C/rpc
VAULT_ADDRESS=0x...            # celui de deploy-fuji
DEPLOY_BLOCK=...
AGENT_PRIVATE_KEY=0x...        # clé de l'agent (bornée par le contrat)
GUARDIAN_PRIVATE_KEY=0x...     # ne peut que geler : sans risque sur le serveur
OWNER_PRIVATE_KEY=             # VIDE : l'owner signe depuis Core Wallet dans le navigateur
SUPPLIER_ADDRESS=... NEW_SUPPLIER_ADDRESS=... CANARY_ADDRESS=...
ALLOWED_HOSTS=vaultguard.mondomaine.fr
ADMIN_PASSWORD_HASH=scrypt$...
```
Puis :
```bash
chmod 600 deploy/.env.prod
cd deploy && DOMAIN=vaultguard.mondomaine.fr docker compose up -d --build
docker compose logs -f vaultguard      # vérifier
```
Caddy obtient le certificat HTTPS tout seul. Pare-feu du serveur : `sudo ufw allow 22,80,443/tcp && sudo ufw enable`.

Ce que voient les gens :
- **Visiteur** : démonstration, comparaison, bac à sable (chacun le sien, simulé), lecture seule.
- **Admin** (bouton « Connexion admin ») : vrai coffre, validation des paiements (signature Core Wallet), gel, ancrage d'audit.

Mise à jour : `git pull && cd deploy && docker compose up -d --build`.

Alternative sans VPS (démo seulement) : Render / Railway / Fly.io acceptent le `Dockerfile` tel quel ; définir les
mêmes variables d'environnement dans leur interface, `TRUST_PROXY=1`, `COOKIE_SECURE=1`.

## Niveau 3 — Mainnet avec de vrais fonds (après le hackathon)
À ne faire qu'après :
1. **Audit externe du contrat** par une société spécialisée.
2. **Owner = multisig** (Safe sur Avalanche C-Chain, 2 signataires sur 3) : `transferOwnership(safe)` puis
   `acceptOwnership()` depuis le Safe.
3. Clés agent/guardian dans un coffre de secrets (pas un fichier) ; rotation régulière (`setAgent` avec expiration).
4. Plafonds réalistes, délai nouveau fournisseur ≥ 24 h, disjoncteur activé.
5. Supervision : alerte (email/Slack) sur les events `PaymentBlocked`, `CanaryAlert`, `CircuitBreakerTripped`.
6. RPC dédié (pas le RPC public) et `RPC_URL=https://api.avax.network/ext/bc/C/rpc` (chainId 43114) ;
   `deploy-fuji.sh` attend 10 s et prévient s'il détecte le mainnet.

## Ce qu'il ne faut jamais faire
- Mettre `OWNER_PRIVATE_KEY` sur un serveur exposé.
- Lancer le serveur en `HOST=0.0.0.0` sans `ADMIN_PASSWORD_HASH`.
- Commiter un `.env` (le CI le vérifie).
- Utiliser les clés anvil (publiques) ailleurs qu'en local.
