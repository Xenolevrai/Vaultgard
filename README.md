# VaultGuard

**Le contrôle des factures avant paiement.** Hackathon Secure Horizons 2026 — Track 1 « Guardians of Value ».

Depuis le 1er septembre 2026, une facture électronique contient deux choses : une page PDF que l'humain lit, et
des données XML que les logiciels lisent. Personne ne vérifie qu'elles disent la même chose. VaultGuard contrôle
chaque facture avant qu'elle soit payée : compte bancaire changé, page et données qui se contredisent, PDF
retouché, faux fournisseur, doublon maquillé, instructions cachées pour tromper un assistant automatique. Quand
il doute, il demande l'accord d'une personne. Il prépare ensuite le fichier de virements que l'entreprise envoie
elle-même à sa banque : VaultGuard ne déplace pas l'argent.

**Ce qui est fait et ce qui ne l'est pas : [`docs/ETAT.md`](docs/ETAT.md).** L'idée et les fraudes réelles qui la
justifient : [`docs/DETECTION-FRAUDE.md`](docs/DETECTION-FRAUDE.md).

## Démarrer
Windows : double-clic sur `lanceurs/LANCER-DASHBOARD.bat`, puis http://localhost:8000/app
(identifiants de démonstration dans `agent/data/COMPTES-DEMO.txt`, créés par `lanceurs/RECREER-DEMO.bat`).

Kali / Linux :
```bash
bash scripts/setup.sh                                   # une fois
cd agent && ~/.venvs/vaultguard/bin/python ../scripts/seed-demo-local.py   # base de démonstration
~/.venvs/vaultguard/bin/python server.py                # http://localhost:8000
```

Démonstrations : `lanceurs/ENVOYER-FRAUDES-DEMO.bat` (sept mails, dont six fraudes) et
`lanceurs/PREPARER-PLATEFORME-DEMO.bat` (émettre une facture d'une entreprise à une autre).

## Organisation du dépôt
| Dossier | Contenu |
|---|---|
| `agent/` | Le serveur (Python, bibliothèque standard) : API, comptes, contrôles anti-fraude, boîte de dépôt, virements, facturation, tests `test_*.py` |
| `dashboard/workspace/` | L'interface de travail servie sur `/app` (`index.html`, `app.js`, `charts.js`, `styles.css`), sans dépendance |
| `dashboard/` (autres fichiers) | Site public, connexion, inscription, administration de la plateforme, ancienne interface (`/app/classique`) |
| `sdk/` | Lecteur de factures (PDF, XML, mail, image, bureautique) et client de l'API `/v1` |
| `contracts/` | Contrat `AgentVault` (Solidity, Foundry) : coffre et preuves sur Avalanche |
| `examples/` | Factures et mails de démonstration, corpus de fraudes reconstruites depuis des cas publiés |
| `scripts/` | Installation, tests, audit de sécurité, métriques, déploiement |
| `lanceurs/` | Fichiers `.bat` à double-cliquer sous Windows |
| `docs/` | Documentation ([index](docs/README.md)) |
| `deploy/`, `Dockerfile` | Mise en ligne (Caddy, HTTPS) |
| `archive/maquette-front/` | Maquette d'origine du front-end, gardée pour mémoire |
| `preparation/` | Références OWASP et ancien prototype d'avant le hackathon |

## Avalanche
Contrat `AgentVault` : [`0x30c9A13FACf3Be404C1Ea0333D31165Fe1f0d793`](https://testnet.snowtrace.io/address/0x30c9A13FACf3Be404C1Ea0333D31165Fe1f0d793)
(Avalanche Fuji C-Chain, réseau de test, bloc 59263971). L'empreinte de chaque fichier de virements y est inscrite :
une preuve datée de ce qui a été validé, sans aucune donnée de facture. Le même contrat borne les paiements d'un
assistant automatique (liste blanche, plafonds, validation humaine, gel) par l'API `/v1`.

## Données du client
Aucun texte de facture n'est conservé : lecture en mémoire, puis verdict, montant, numéro, quatre derniers
caractères du compte et empreintes SHA-256. Pas de service d'IA tiers : les contrôles sont des règles, le lecteur
de factures tourne sur le serveur de l'entreprise. Détails : `docs/CONFIANCE-ARGENT-LEGAL.md`.

## Tests et sécurité
```bash
bash scripts/test-all.sh --full   # contrat (Foundry), serveur (unittest), parité sur blockchain locale, Slither, Bandit
bash scripts/security-audit.sh    # attaques rejouées sur 127.0.0.1 -> docs/audit-latest.txt
bash scripts/doctor.sh            # diagnostic de la configuration
```
Les chiffres de détection (`docs/METRIQUES.md`) viennent de notre propre jeu d'essai, pas de trafic réel.

## Limites connues
- Réseau de test uniquement ; contrat non audité par un tiers. Ne pas utiliser avec de vrais fonds.
- VaultGuard n'est pas une plateforme de facturation agréée ; aucun connecteur vers un logiciel de comptabilité
  (Pennylane compris) n'est construit.
- PDF scannés, chiffrés ou à polices exotiques : non lus, renvoyés à une personne. Images : OCR optionnel.
- Le numéro SIREN d'une entreprise est déclaré par elle, pas encore vérifié.
- Le site public et l'ancienne interface présentent encore l'ancien sujet du projet.
- La liste complète est dans `docs/ETAT.md`.
