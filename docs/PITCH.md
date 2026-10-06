# Pitch VaultGuard (3 min + 2 min Q&A)

## Structure (chronométrée)
| Temps | Qui | Contenu |
|---|---|---|
| 0:00–0:30 | Orateur 1 | **Accroche** : « Demain, votre comptable sera un agent IA. Il lit vos factures et il a la clé du coffre. Que se passe-t-il quand une facture lui parle ? » |
| 0:30–1:00 | Orateur 1 | **Problème** : injection de prompt (n°1 OWASP LLM 2025, au cœur du risque n°1 OWASP Agentic 2026), fraude au changement de RIB, adresses sosies. Un LLM ne distingue pas fiablement donnée et instruction : aucun prompt ne règle ça. |
| 1:00–2:15 | Orateur 2 | **Démo live** (script ci-dessous). |
| 2:15–2:45 | Orateur 1 | **Pourquoi c'est solide** : 2 couches indépendantes. Le pare-feu comprend le contexte ; le contrat Avalanche garantit une perte maximale **bornée et vérifiable**, même si l'IA ET le serveur sont piratés. Et on s'est attaqués nous-mêmes : 19 attaques rejouées automatiquement, toutes bloquées. |
| 2:45–3:00 | Orateur 1 | **Vision** : la brique de contrôle interne de toute entreprise qui donne un budget à un agent. « Ne faites pas confiance au LLM. Bornez-le. » |

## Script de démo (http://localhost:8000, bouton « Mode présentation » pour le projecteur)
1. Onglet **Comparer** → « Tout comparer » : le tableau rouge/vert dit tout en 10 secondes.
2. Onglet **Démonstration**, mode « Aucune protection » → « Instruction cachée » : −0.09 AVAX. Montrer le commentaire caché.
3. Même situation en « VaultGuard complet » : arrêté, et le fournisseur est quand même payé. Ouvrir « Détails techniques ».
4. **Adresse appât** : l'IA manipulée vise l'adresse piège → coffre gelé instantanément.
5. **Agent compromis qui insiste** en « Contrat seul » : sans aucun pare-feu, le contrat se gèle tout seul (disjoncteur).
6. **Bac à sable** : « Essayez de nous pirater » → inviter un juré à taper sa propre facture piégée.
7. Onglet **Coffre** (vrai coffre Fuji) : règles on-chain, lien Snowtrace, « Rapport scellé » + « Sceller sur la blockchain ».

**Plan B** si le Wi-Fi tombe : tout fonctionne hors-ligne (simulation fidèle au contrat, prouvée par un test de parité). Vidéo de 60 s en secours.

## Ce qui est nouveau (à dire)
- **Adresses appâts (honeytokens) pour agents IA** : une adresse que seul un agent manipulé paierait → gel immédiat.
- **Disjoncteur on-chain** : trop de refus → pause automatique, sans dépendre d'aucun serveur.
- **Délai anti-changement de RIB** inscrit dans le contrat : un nouveau fournisseur n'est payable qu'après 24 h.
- **Guardian** : un robot de surveillance peut geler, jamais dégeler ni dépenser.
- **Rapports d'audit scellés on-chain** : l'empreinte SHA-256 du rapport est ancrée sur Avalanche.
- **Owner jamais sur le serveur** : les validations se signent dans Core Wallet.

## Arguments par membre du jury
- **Team1 / Avalanche** : contrat déployé sur Fuji (C-Chain), events = audit public, finalité ~1 s, frais minimes.
  Extensions : L1 Avalanche dédiée avec allowlist native, ICM (Interchain Messaging) pour une politique multi-chaînes,
  paiements en stablecoin (USDC) déjà supportés par le contrat (ERC20).
- **KPMG** : contrôle interne « 4 yeux », séparation des pouvoirs (agent ≠ guardian ≠ owner), journal immuable +
  rapports scellés, cartographie OWASP, perte maximale chiffrée = appétit au risque, audit de sécurité avant/après
  (docs/SECURITE.md).
- **KRYPTOSPHERE** : vrai code, ~90 tests (fuzzing + invariants), audit Slither/Bandit, démo live, open source,
  prêt à déployer (Docker + HTTPS).

## Questions probables du jury
- *« Les regex d'injection, c'est contournable ? »* → Oui, c'est un signal parmi d'autres (on normalise déjà les
  caractères invisibles, homoglyphes et base64). Les règles fortes sont la **provenance**, l'**appât** et le **contrat**,
  qui ne dépendent pas du texte. Extension : un LLM-juge.
- *« Et si l'attaquant pirate le serveur ? »* → Il obtient la clé de l'agent (bornée, expirante) et celle du guardian
  (qui ne peut que geler). Pas celle de l'owner. Perte maximale = plafond journalier, avec le disjoncteur en plus.
- *« Pourquoi la blockchain ? »* → Une garantie que même l'opérateur ne peut pas contourner discrètement, et un audit public.
- *« Coût ? »* → ~50–130k gas par paiement : quelques centimes sur Avalanche.
- *« Différence avec un multisig Safe ? »* → Un multisig exige un humain pour tout. Nous laissons l'agent autonome
  sous le seuil et ajoutons la compréhension du contexte. L'owner de VaultGuard peut d'ailleurs être un Safe.
- *« Comment savez-vous que c'est sûr ? »* → On s'est attaqués avec Kali : une douzaine de failles trouvées sur notre v1,
  toutes corrigées et rejouées automatiquement à chaque modification (`security-audit.sh`).
- *« Business model ? »* → SDK open-core + offre entreprise (audit, politiques avancées, conformité).
