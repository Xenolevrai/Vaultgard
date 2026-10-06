# Mise en production de VaultGuard

Trois niveaux, du plus simple au plus sérieux. Pour le hackathon, le **niveau 1** suffit ; le **niveau 2** donne une
URL publique à montrer au jury ; le **niveau 3** est ce qu'il faudrait pour de vrais fonds.

---

## Niveau 1 — Démo locale sur Avalanche Fuji (hackathon)
1. `bash scripts/create-wallets.sh` (déjà fait).
2. Faucet Fuji sur l'adresse Owner (≈ 1 AVAX de test).
3. `bash scripts/deploy-fuji.sh` → déploie, configure (liste blanche, délai, appât, guardian, disjoncteur), finance.
4. Dans `agent/.env` : `CHAIN=web3`.
5. `bash scripts/doctor.sh` → 0 erreur.
6. `LANCER-DASHBOARD.bat` → onglet Coffre → « Vrai coffre » : contrat visible sur Snowtrace.

---

## Niveau 2 — URL publique (VPS + Docker + HTTPS)
Il faut un petit serveur Linux (VPS, ~5 €/mois : OVH, Scaleway, Hetzner…) et un nom de domaine (ou sous-domaine)
qui pointe vers son IP (enregistrement DNS de type A).

### 1. Préparation du serveur et déploiement
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git sqlite3
git clone https://github.com/<ton-compte>/vaultguard.git && cd vaultguard
cp .env.example deploy/.env.prod && nano deploy/.env.prod
```

### 2. Configuration des variables d'environnement (`deploy/.env.prod`)
```ini
CHAIN=web3
RPC_URL=https://api.avax-test.network/ext/bc/C/rpc
VAULT_ADDRESS=0x...            # adresse du contrat déployé sur Fuji
DEPLOY_BLOCK=...
AGENT_PRIVATE_KEY=0x...        # clé de l'agent (bornée par le contrat)
GUARDIAN_PRIVATE_KEY=0x...     # ne peut que geler : sans risque sur le serveur
OWNER_PRIVATE_KEY=             # VIDE : l'owner signe depuis Core Wallet dans le navigateur
SUPPLIER_ADDRESS=... NEW_SUPPLIER_ADDRESS=... CANARY_ADDRESS=...
ALLOWED_HOSTS=vaultguard.mondomaine.fr
COOKIE_SECURE=1
TRUST_PROXY=1
DB_PATH=/var/lib/vaultguard/vaultguard.db
```

### 3. Persistance de la base de données (`DB_PATH`)
La base SQLite contient les comptes utilisateurs, organisations, clés API hachées et le journal d'audit append-only.
- Configurez `DB_PATH=/var/lib/vaultguard/vaultguard.db`.
- Permissions strictes sur le fichier et son répertoire :
  ```bash
  sudo mkdir -p /var/lib/vaultguard
  sudo chown -R 1000:1000 /var/lib/vaultguard
  sudo chmod 700 /var/lib/vaultguard
  ```
- Dans `docker-compose.yml`, assurez-vous de monter le volume `/var/lib/vaultguard:/var/lib/vaultguard` pour préserver les données lors des mises à jour d'images.

### 4. Création du premier super-administrateur (`--create-admin`)
Pour initialiser le compte d'administration sans interface web non-sécurisée :
```bash
DB_PATH=/var/lib/vaultguard/vaultguard.db python3 agent/server.py --create-admin
```
La commande interactive demande :
1. L'email du super-administrateur.
2. Un mot de passe fort (≥ 12 caractères).
3. L'enrôlement 2FA obligatoire (génération du secret TOTP RFC 6238 et affichage des codes de secours).

Ce compte permet ensuite d'accéder à l'espace furtif `/admin`.

### 5. Lancement avec Caddy (HTTPS automatique)
```bash
chmod 600 deploy/.env.prod
cd deploy && DOMAIN=vaultguard.mondomaine.fr docker compose up -d --build
docker compose logs -f vaultguard      # vérifier le bon démarrage
```
Pare-feu du serveur : `sudo ufw allow 22,80,443/tcp && sudo ufw enable`.

---

## 3. Exploitation et maintenance en production

### Sauvegarde à chaud SQLite (`sqlite3 .backup`)
Ne jamais copier directement un fichier `.db` SQLite en cours d'écriture (risque de base corrompue en mode WAL). Utilisez la commande officielle de sauvegarde à chaud transactionnelle :
```bash
sqlite3 /var/lib/vaultguard/vaultguard.db ".backup '/var/backups/vaultguard/vg_$(date +%Y%m%d_%H%M%S).db'"
```
Exemple de cron quotidien (`/etc/cron.daily/vaultguard-backup`) :
```bash
#!/bin/bash
set -e
BACKUP_DIR="/var/backups/vaultguard"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/vg_$(date +%Y%m%d_%H%M%S).db"
sqlite3 /var/lib/vaultguard/vaultguard.db ".backup '$BACKUP_FILE'"
chmod 600 "$BACKUP_FILE"
# Rétention 30 jours
find "$BACKUP_DIR" -name "vg_*.db" -mtime +30 -delete
```

### Rotation des clés

#### 1. Rotation de la clé agent (on-chain)
1. Générer une nouvelle paire de clés pour l'agent (`cast wallet new` ou script).
2. L'owner appelle `setAgent(nouvelle_adresse, expiration_timestamp)` sur le contrat Avalanche.
3. Mettre à jour `AGENT_PRIVATE_KEY` dans `deploy/.env.prod`.
4. Redémarrer le conteneur : `docker compose restart vaultguard`.

#### 2. Rotation des clés API des organisations
1. Les organisations créent une nouvelle clé API depuis la console `/app` (ou via l'API).
2. Remplacer la clé dans les agents et scripts clients.
3. Révoquer l'ancienne clé depuis `/app` : la révocation prend effet immédiatement (`is_active = 0`, renvoie `401 Unauthorized` sur `/v1/*`).

#### 3. Rotation de la clé Guardian
1. L'owner appelle `setGuardian(nouveau_guardian)` on-chain.
2. Mettre à jour `GUARDIAN_PRIVATE_KEY` dans l'environnement et redémarrer le serveur.

#### 4. Révocation des sessions en cas d'urgence
Depuis `/admin`, le super-administrateur peut déclencher :
- La suspension immédiate d'une organisation compromise (coupe instantanément l'accès à `/v1` et `/app`).
- La déconnexion générale (« Déconnecter partout ») qui supprime toutes les sessions en base de données.

---

## Niveau 3 — Mainnet avec de vrais fonds (après le hackathon)
À ne faire qu'après :
1. **Audit externe du contrat** par une société spécialisée.
2. **Owner = multisig** (Safe sur Avalanche C-Chain, 2 signataires sur 3) : `transferOwnership(safe)` puis `acceptOwnership()` depuis le Safe.
3. Clés agent/guardian dans un coffre de secrets (AWS KMS, GCP Secret Manager, Vault HashiCorp) ; rotation régulière (`setAgent` avec expiration).
4. Plafonds réalistes, délai nouveau fournisseur ≥ 24 h, disjoncteur activé.
5. Supervision : alerte (email/Slack/PagerDuty) sur les events `PaymentBlocked`, `CanaryAlert`, `CircuitBreakerTripped`.
6. RPC dédié redondant (QuickNode, Alchemy, Ava Labs privé) et `RPC_URL=https://api.avax.network/ext/bc/C/rpc` (chainId 43114).

---

## Ce qu'il ne faut jamais faire
- Mettre `OWNER_PRIVATE_KEY` sur un serveur exposé.
- Lancer le serveur en `HOST=0.0.0.0` sans configuration de reverse-proxy et variables sécurisées.
- Commiter un `.env` ou une base de données avec des données sensibles.
- Utiliser les clés Anvil (publiques) en environnement de test connecté ou en production.
- Effectuer des copies brutes du fichier `.db` sans passer par `.backup`.
