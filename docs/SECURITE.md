# Sécurité — audit de VaultGuard (6 octobre 2026)

Méthode : on a d'abord attaqué la v1 depuis Kali Linux (nmap, ffuf, curl, Slither, Bandit) pour lister les failles
réelles, puis tout corrigé, puis rejoué chaque attaque pour prouver qu'elle est bloquée. Le rejeu est automatisé :
`bash scripts/security-audit.sh` (ou `AUDIT-SECURITE.bat`) → `docs/audit-latest.txt`.

Résultat actuel : **19/19 vérifications d'intrusion OK**, Slither et Bandit sans alerte moyenne/haute,
pip-audit sans dépendance vulnérable, 33 tests contrat (dont fuzz + invariants), 52 tests Python, 4 tests de parité
sur blockchain locale.

## 1. Ce qui a été trouvé sur la v1, et corrigé

| Gravité | Faille (v1) | Preuve d'exploitation | Correction (v2) | Test de non-régression |
|---|---|---|---|---|
| Critique | **CSRF** : aucune authentification ; n'importe quel site visité par l'owner pouvait geler/valider via `fetch` en `text/plain` | `curl -X POST /api/pause -H "Origin: https://evil.example" -H "Content-Type: text/plain"` → 200 | Session serveur (cookie HttpOnly, SameSite=Strict) + jeton CSRF obligatoire + `Content-Type: application/json` obligatoire + vérification de l'`Origin` | `test_server.test_csrf_*`, audit §2 |
| Critique | **DNS rebinding** : en-tête `Host` non vérifié | `curl -H "Host: evil.example" /api/state` → 200 | Liste blanche `ALLOWED_HOSTS` → 421 | `test_dns_rebinding_host_rejected` |
| Haute | **Index négatif** : `{"id": -1}` validait le dernier paiement en attente (indexation Python) | `POST /api/approve {"id":-1}` → `Executed` | Validation stricte (entier ≥ 0, pas booléen) côté API **et** dans `MockChain` | `test_pending_rules`, `test_input_validation` |
| Haute | **Déni de service mémoire** : `Content-Length` géant lu en mémoire | `Content-Length: 99999999999` → `MemoryError` | Corps limité à 16 Ko (413), sockets avec timeout 15 s (anti slowloris), 64 requêtes simultanées max, état borné (sessions LRU, events, journal tournant) | `test_body_size_limits` |
| Moyenne | **Exposition réseau** : écoute sur `0.0.0.0` (tout le Wi-Fi du hackathon) | nmap depuis le LAN | Écoute `127.0.0.1` par défaut ; en `0.0.0.0` sans mot de passe, actions admin désactivées | audit §1 |
| Moyenne | **Fuite d'erreurs internes** (`JSONDecodeError: ...`) | `POST` avec `xx` | Messages génériques + référence ; détail uniquement dans le journal serveur | `test_invalid_json_no_leak` |
| Moyenne | **Aucune limitation de débit** (300 requêtes/300 OK, coût LLM illimité) | boucle curl | Seau à jetons par IP et par catégorie ; connexion : 5 essais / 5 min | `test_login_bruteforce_limited`, audit §5 |
| Moyenne | **NaN / inf** acceptés comme montant (comparaisons toujours fausses → contournement des plafonds en simulation) | `amount: NaN` | `parse_amount()` : nombre fini > 0 ; JSON `NaN` refusé | `test_invalid_inputs_blocked` |
| Moyenne | **Obfuscation** : `ign​ore`, homoglyphes cyrilliques, base64 passaient les filtres | scénario `obfuscated` | Normalisation NFKC + suppression des caractères invisibles + homoglyphes + décodage base64 | `test_obfuscation_detected` |
| Moyenne | **Masquage incomplet** : clé privée sans `0x`, phrase mnémonique, JWT non masqués | memo `key=abab…` | Motifs ajoutés | `test_redaction` |
| Faible | Pas d'en-têtes de sécurité, bannière `Python/3.13` | `curl -I` | CSP à nonce, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, COOP/CORP, HSTS en prod, `Server: VaultGuard` | `test_dashboard_security_headers` |
| Faible | Journal d'audit sans limite de taille | — | Rotation à 5 Mo | — |

### Contrat (v1 → v2)
| Gravité | Problème | Correction |
|---|---|---|
| Haute | `approve()` ne revérifiait rien : un destinataire retiré ou un coffre gelé pouvait encore être payé | `approve` revérifie pause, liste blanche, appât, token ; le montant compte dans la dépense du jour |
| Haute | Paiements en attente illimités et éternels (spam, validations oubliées) | Maximum 10 en attente (`TooManyPending`), expiration 3 jours (`PendingExpired`) |
| Moyenne | ERC20 sans code : `call` vers une adresse vide « réussit » silencieusement | `setLimits` et `_transfer` exigent du code (`NotAContract`) |
| Moyenne | Pas de transfert de propriété sécurisé | Transfert en deux étapes (`transferOwnership` / `acceptOwnership`) |
| Faible | Pas de vérification d'adresse nulle, `withdraw` sans event, memo illimité, montant 0 | `ZeroAddress`, event `Withdrawn`, memo ≤ 140 octets, `ZeroAmount` |
| Info | Réentrance signalée par Slither (le pattern CEI protégeait déjà) | Verrou `nonReentrant` explicite + test d'attaque réel `test_ReentrancyBlocked` |

## 2. Nouvelles défenses (au-delà des corrections)
- **Délai d'activation des nouveaux destinataires** (24 h) : la fraude au changement de RIB a le temps d'être détectée.
- **Adresses appâts (canary / honeytoken)** : une adresse jamais utilisée légitimement ; la toucher gèle le coffre.
- **Disjoncteur on-chain** : 5 refus dans la journée → pause automatique, même si le serveur est compromis.
- **Clé d'agent à durée de vie limitée** (30 jours) : une clé volée finit par ne plus servir.
- **Rôle guardian** : peut geler, jamais dégeler ni dépenser → sa clé peut rester sur le serveur sans risque.
- **Owner hors serveur** : en production, l'owner signe depuis Core Wallet ; le serveur n'a jamais sa clé.
- **Quarantaine de session** (pare-feu) : 2 blocages → plus aucun paiement de la session.
- **Mandat** : un paiement à un fournisseur connu mais non mentionné dans la demande utilisateur demande confirmation.
- **Rapports d'audit scellés** : SHA-256 du rapport ancré on-chain (`anchorReport`) ; export CSV protégé contre
  l'injection de formule (CWE-1236).
- **Bac à sable par visiteur** : un visiteur public ne touche jamais au vrai coffre ni au LLM payant.

## 3. Faux positifs assumés (outils)
- Slither `arbitrary-send-eth` : les destinataires sont en liste blanche (c'est le but du contrat).
- Slither `reentrancy-*` : verrou `nonReentrant` + checks-effects-interactions, prouvé par `test_ReentrancyBlocked`.
- Slither `incorrect-equality` / `timestamp` : comparaison de numéros de jour ; un validateur ne décale l'horloge que
  de quelques secondes.
- Bandit B105 sur les motifs regex de détection de secrets (ce ne sont pas des mots de passe).

## 4. Risques résiduels (en connaissance de cause)
- **Owner compromis** = perte possible : en production, l'owner doit être un **multisig** (Safe sur Avalanche) ou
  un wallet matériel. Le transfert en deux étapes le permet sans redéployer.
- **Fenêtre journalière calendaire** : un agent compromis peut dépenser 2 × le plafond autour de minuit UTC.
  Borné et documenté ; une fenêtre glissante coûterait plus de gas.
- La détection d'injection par motifs reste contournable par une formulation nouvelle : c'est pourquoi la couche 2
  (on-chain) ne dépend PAS de la couche 1. Piste : LLM-juge en plus des motifs.
- Le contrat n'a pas été audité par un tiers : obligatoire avant un mainnet avec de vrais fonds.

## 5. À refaire à chaque évolution
1. `bash scripts/test-all.sh --full` (tout doit être vert).
2. `bash scripts/security-audit.sh` (0 échec).
3. Toute nouvelle règle : test contrat + règle dans `MockChain` + test de parité.
