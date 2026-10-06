---
description: Mettre VaultGuard en ligne (VPS + Docker + HTTPS)
---

Suivre `docs/MISE_EN_PRODUCTION.md`, niveau 2. Points de contrôle :
1. `python3 agent/server.py --hash-password` → `ADMIN_PASSWORD_HASH` dans `deploy/.env.prod`.
2. `OWNER_PRIVATE_KEY` VIDE sur le serveur ; `ALLOWED_HOSTS` = le domaine.
3. `cd deploy && DOMAIN=<domaine> docker compose up -d --build`, puis `curl https://<domaine>/healthz`.
4. Vérifier les en-têtes : `curl -I https://<domaine>/` (CSP, HSTS, X-Frame-Options).
