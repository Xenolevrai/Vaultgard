# Sécurité — audit et architecture de VaultGuard (6 octobre 2026)

Méthode : on a attaqué la plateforme depuis Kali Linux (nmap, ffuf, curl, sqlmap, Slither, Bandit) pour lister les failles
réelles, corrigé chaque vulnérabilité selon le principe de défense en profondeur, puis rejoué chaque attaque pour prouver qu'elle est bloquée. Le rejeu est automatisé :
`bash scripts/security-audit.sh` (ou `lanceurs/AUDIT-SECURITE.bat`) → `docs/audit-latest.txt`.

Résultat actuel : **29/29 vérifications d'intrusion OK (0 échec)**, Slither et Bandit sans alerte moyenne/haute,
pip-audit sans dépendance vulnérable, 33 tests contrat (dont fuzz + invariants), 147 tests Python complets, 4 tests de parité
sur blockchain locale.

---

## 1. Ce qui a été trouvé sur la v1, et corrigé en v2

| Gravité | Faille (v1) | Preuve d'exploitation | Correction (v2) | Test de non-régression |
|---|---|---|---|---|
| Critique | **CSRF** : aucune authentification ; n'importe quel site visité par l'owner pouvait geler/valider via `fetch` en `text/plain` | `curl -X POST /api/pause -H "Origin: https://evil.example" -H "Content-Type: text/plain"` → 200 | Session serveur (cookie HttpOnly, SameSite=Strict) + jeton CSRF obligatoire + `Content-Type: application/json` obligatoire + vérification de l'`Origin` | `test_server.test_csrf_*`, audit §2 |
| Critique | **DNS rebinding** : en-tête `Host` non vérifié | `curl -H "Host: evil.example" /api/state` → 200 | Liste blanche `ALLOWED_HOSTS` → 421 | `test_dns_rebinding_host_rejected` |
| Haute | **Index négatif** : `{"id": -1}` validait le dernier paiement en attente (indexation Python) | `POST /api/approve {"id":-1}` → `Executed` | Validation stricte (entier ≥ 0, pas booléen) côté API **et** dans `MockChain` | `test_pending_rules`, `test_input_validation` |
| Haute | **Déni de service mémoire** : `Content-Length` géant lu en mémoire | `Content-Length: 99999999999` → `MemoryError` | Corps limité à 16 Ko (413), sockets avec timeout 15 s (anti slowloris), 64 requêtes simultanées max, état borné (sessions LRU, events, journal tournant) | `test_body_size_limits` |
| Moyenne | **Exposition réseau** : écoute sur `0.0.0.0` (tout le Wi-Fi du hackathon) | nmap depuis le LAN | Écoute `127.0.0.1` par défaut ; en `0.0.0.0` sans mot de passe, actions admin désactivées | audit §1 |
| Moyenne | **Fuite d'erreurs internes** (`JSONDecodeError: ...`) | `POST` avec `xx` | Messages génériques + référence ; détail uniquement dans le journal serveur | `test_invalid_json_no_leak` |
| Moyenne | **Aucune limitation de débit** (300 requêtes/300 OK, coût LLM illimité) | boucle curl | Seau à jetons par IP et par catégorie ; connexion : 5 essais / 5 min | `test_login_bruteforce_limited`, audit §7 |
| Moyenne | **NaN / inf** acceptés comme montant (comparaisons toujours fausses → contournement des plafonds en simulation) | `amount: NaN` | `parse_amount()` : nombre fini > 0 ; JSON `NaN` refusé | `test_invalid_inputs_blocked` |
| Moyenne | **Obfuscation** : `ign​ore`, homoglyphes cyrilliques, base64 passaient les filtres | scénario `obfuscated` | Normalisation NFKC + suppression des caractères invisibles + homoglyphes + décodage base64 | `test_obfuscation_detected` |
| Moyenne | **Masquage incomplet** : clé privée sans `0x`, phrase mnémonique, JWT non masqués | memo `key=abab…` | Motifs ajoutés | `test_redaction` |
| Faible | Pas d'en-têtes de sécurité, bannière `Python/3.13` | `curl -I` | CSP à nonce, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, COOP/CORP, HSTS en prod, `Server: VaultGuard` | `test_dashboard_security_headers` |
| Faible | Journal d'audit sans limite de taille | — | Rotation à 5 Mo | — |

### Contrat Avalanche (v1 → v2)
| Gravité | Problème | Correction |
|---|---|---|
| Haute | `approve()` ne revérifiait rien : un destinataire retiré ou un coffre gelé pouvait encore être payé | `approve` revérifie pause, liste blanche, appât, token ; le montant compte dans la dépense du jour |
| Haute | Paiements en attente illimités et éternels (spam, validations oubliées) | Maximum 10 en attente (`TooManyPending`), expiration 3 jours (`PendingExpired`) |
| Moyenne | ERC20 sans code : `call` vers une adresse vide « réussit » silencieusement | `setLimits` et `_transfer` exigent du code (`NotAContract`) |
| Moyenne | Pas de transfert de propriété sécurisé | Transfert en deux étapes (`transferOwnership` / `acceptOwnership`) |
| Faible | Pas de vérification d'adresse nulle, `withdraw` sans event, memo illimité, montant 0 | `ZeroAddress`, event `Withdrawn`, memo ≤ 140 octets, `ZeroAmount` |
| Info | Réentrance signalée par Slither (le pattern CEI protégeait déjà) | Verrou `nonReentrant` explicite + test d'attaque réel `test_ReentrancyBlocked` |

---

## 2. Architecture de sécurité v3 Multi-Organisation (Étapes 1 à 8)

La version 3 transforme VaultGuard en plateforme multi-tenants sécurisée intégrant des garde-fous stricts :

### Étape 1 : Persistance et intégrité de l'audit
- **Montants entiers exacts** : montants stockés sous forme entière en nAVAX (gwei), interdisant tout artefact de conversion ou arrondi de nombre à virgule flottante.
- **Triggers SQLite append-only** : triggers SQL `audit_no_update` et `audit_no_delete` bloquant formellement toute tentative de modification ou suppression directe en base.
- **Chaîne cryptographique SHA-256** : chaque entrée d'audit calcule le hash du bloc précédent (`previous_hash`) ; un vérificateur d'intégrité détecte les corruptions en ligne ou les modifications hors-ligne.

### Étape 2 : Authentification et 2FA
- **Hachage scrypt fort** : stockage avec sel unique de 16 octets (`hash_password` / `verify_password`).
- **2FA TOTP RFC 6238** : TOTP avec secret chiffré en base, fenêtre temporelle stricte de ±1 pas de 30 secondes, codes de secours à usage unique hachés.
- **Protection anti-énumération** : réponse générique `Identifiants invalides` pour les adresses existantes et inconnues, avec temporisation scrypt constante via `DUMMY_PASSWORD_HASH` pour neutraliser les attaques temporelles.
- **Verrouillage de compte** : 5 échecs consécutifs entraînent un blocage automatique de 15 minutes (`locked_until`).

### Étape 3 : Isolation multi-tenant et politiques d'approbation
- **Anti-IDOR strict** : le tenant ID (`org_id`) est obligatoirement dérivé de la session serveur ou du jeton Bearer validé en base. Les requêtes ciblant une ressource d'une autre organisation renvoient systématiquement `404` (pas de `403` pour ne pas divulguer l'existence des identifiants).
- **Règles et plafonds bornés** : contrôle des tiers autorisés, des plafonds par transaction et journaliers par organisation, indépendamment des autres locataires.

### Étape 4 : Concurrence, quarantaine et protection CSV
- **Verrou par organisation (`org_locks`)** : exclusion mutuelle par threading lock dédié par `org_id` empêchant les doubles dépenses concurrentes.
- **Quarantaine permanente** : une détection d'injection, de tentative hostile ou de ciblage d'adresse appât place immédiatement le compte en quarantaine sans expiration.
- **Protection injection CSV (CWE-1236)** : échappement des caractères dangereux (`=`, `+`, `-`, `@`, `\t`, `\r`) par préfixe apostrophe `'` lors de l'export du journal d'audit.

### Étape 5 : Espace d'administration furtif
- **Mode stealth 404** : `/admin` et `/api/admin/*` renvoient un code `404 Not Found` strict à tout utilisateur non-authentifié ou dépourvu du rôle super-admin avec 2FA validée.
- **Revalidation continue** : le statut d'administrateur est re-vérifié en base de données à chaque requête HTTP.
- **Garde-fous opérationnels** : interdiction formelle pour un super-admin de se désactiver ou suspendre lui-même ; protection absolue du dernier super-admin actif ; révocation globale de toutes les sessions actives en base en cas d'incident.
- **Opérations atomiques** : modifications d'état par `UPDATE ... WHERE <condition>` avec validation explicite du nombre de lignes affectées (`rowcount == 1`).

### Étape 6 : Durcissement des pages publiques et isolation de la démo
- **Content-Security-Policy stricte** : génération d'un nonce cryptographique aléatoire unique par requête HTTP (`'nonce-...'`). Aucun style ou script en ligne n'est exécuté sans ce nonce.
- **Aucune ressource tierce** : pas de CDN, pas de polices externes Google Fonts, pas de pixels de traçage. Toutes les ressources sont hébergées localement.
- **Séparation stricte démo / production** : l'ancienne interface de simulation tourne de façon isolée sur `/demo`, l'API de paiement tourne sur `/v1/*`, et la console sur `/app`.

### Étape 7 : Serveur statique durci et interface robuste
- **Liste blanche explicite des fichiers statiques** : `server.py` utilise un dictionnaire de hachage strict pour servir les fichiers statiques, éliminant tout risque de path-traversal (`../`).
- **Suppression intégrale des attributs `style=` et `on*=`** : conformité intégrale avec la CSP bloqueuse, remplacée par des classes sémantiques réutilisables.
- **Zéro débordement (390 px à 1440 px)** : application de `overflow-wrap: anywhere` sur tous les identifiants, hash et adresses blockchain ; `min-width: 0` sur les conteneurs flex/grid.

### Étape 8 : Batterie d'attaques dynamiques automatisées (Kali Linux)
- Rejeu dynamique dans `scripts/security-audit.sh` sur `127.0.0.1` :
  1. Énumération d'utilisateurs testée et bloquée (messages uniformes, timing constant).
  2. Force brute bloquée (verrouillage de compte après 5 essais).
  3. Tentatives d'accès croisé (IDOR) rejetées en `404`.
  4. Clés API Bearer révoquées bloquées en `401`.
  5. Sondes `/admin` rejetées en `404` furtif.
  6. Audit dynamique sqlmap sur `/api/auth/login` confirmant l'absence de paramètre injectable.
  7. Limitation de débit vérifiée (429 sur salve rapide).
  8. Analyse statique des contrats (Slither : 0 alerte critique/haute/moyenne).
  9. Analyse statique Python (Bandit : 0 alerte moyenne/haute).
  10. Analyse des dépendances (pip-audit : 0 vulnérabilité connue).

### Étape 9 : Boîte de dépôt des factures (10 octobre 2026)
Une adresse mail par organisation reçoit les factures (`agent/mail_agent.py`, `agent/inbox.py`, détail dans
`docs/BOITE-FACTURES.md`). Menaces traitées :
- **Expéditeur inconnu** : seuls les en-têtes sont téléchargés ; le corps n'est lu que si l'expéditeur figure dans la
  liste de confiance de l'organisation destinataire. Sinon le mail est effacé sans être ouvert.
- **Adresse d'expéditeur imitée** : exigence d'un résultat DMARC, DKIM ou SPF valide et aligné sur le domaine de
  l'expéditeur, lu dans le seul premier en-tête `Authentication-Results` et seulement s'il porte le nom de notre
  serveur de réception (un en-tête fabriqué par l'expéditeur est plus bas ou porte un autre nom).
- **Isolation entre clients** : l'alias de l'adresse désigne l'organisation ; la liste de confiance, les fournisseurs
  et les factures sont filtrés par `org_id` ; un identifiant d'une autre organisation renvoie `404`.
- **Fraude au changement de RIB** : l'IBAN n'est jamais repris de la facture ; il est comparé à celui enregistré
  (clé de contrôle ISO 13616 vérifiée). Tous les IBAN du document sont relevés, y compris dans le texte invisible.
- **Injection indirecte** (OWASP LLM01) : le contenu du mail est une donnée ; les motifs d'instructions cachées,
  d'encodage et d'homoglyphes entraînent un refus ou un contrôle humain.
- **Réponse automatique** : elle ne recopie rien du mail reçu (pas de relais de contenu d'attaquant), porte
  `Auto-Submitted`, et aucun mail automatique reçu n'obtient de réponse (pas de boucle).
- **Saturation** : 60 contrôles par heure et par organisation, 20 traces de mails écartés par heure, 10 Mo par mail.
- **Zéro conservation** : ni mail ni facture en base ; test `test_no_invoice_text_reaches_the_database`.

Bogue de disponibilité corrigé à cette occasion : une écriture SQL refusée laissait une transaction ouverte et le
verrou d'écriture pris (toutes les requêtes suivantes en erreur 500). `db.execute` annule maintenant la transaction.

---

## 3. Faux positifs assumés (outils)
- Slither `arbitrary-send-eth` : les destinataires sont en liste blanche (c'est le but du contrat).
- Slither `reentrancy-*` : verrou `nonReentrant` + checks-effects-interactions, prouvé par `test_ReentrancyBlocked`.
- Slither `incorrect-equality` / `timestamp` : comparaison de numéros de jour ; un validateur ne décale l'horloge que de quelques secondes.
- Bandit B105 sur les motifs regex de détection de secrets (ce ne sont pas des mots de passe codés en dur).

---

## 4. Risques résiduels (en connaissance de cause)
- **Owner compromis** = perte possible : en production, l'owner doit être un **multisig** (Safe sur Avalanche) ou un wallet matériel. Le transfert en deux étapes le permet sans redéployer.
- **Fenêtre journalière calendaire** : un agent compromis peut dépenser 2 × le plafond autour de minuit UTC. Borné et documenté.
- **Contournement des motifs NLP** : la détection d'injection par expressions régulières reste contournable par une formulation inconnue, c'est pourquoi la couche 2 (le smart contract Avalanche) impose les plafonds et listes blanches de manière totalement découplée.
- **Boîte de dépôt** : la messagerie réellement piratée d'un employé autorisé permet de déposer des factures (borné par le contrôle de l'IBAN, le seuil et le délai d'activation) ; la connexion à une vraie boîte (Gmail) n'a pas encore été essayée ; la boîte de démonstration locale fait confiance à l'en-tête de contrôle porté par le fichier (elle n'est active qu'en écoute locale et sans boîte configurée).
- **Audit tiers formel** : recommandé avant mise en production avec de forts volumes financiers.
