# Pitch VaultGuard (5 min + 2 min de questions au round 1)

## Direction du 10 oct au soir : la fraude à la facture électronique (à pitcher en premier)
Retour des juges : « votre solution existe déjà, démarquez-vous ». Réponse : **on ne pitche plus le paiement de
factures, on pitche la détection des fraudes que les autres ne voient pas.** Détail, preuves et sources :
`DETECTION-FRAUDE.md`.

| Temps | Contenu |
|---|---|
| 0:00–0:40 | **Accroche.** « Le 17 juin et le 9 septembre 2026, la Cour de cassation a jugé deux fraudes au faux RIB : 103 000 € et 365 000 € partis sur le compte d'un escroc. Dans les deux cas, la facture avait l'air vraie. » |
| 0:40–1:30 | **Le problème nouveau.** Depuis le 1er septembre 2026, toute entreprise reçoit des factures électroniques. Une facture électronique, c'est deux documents en un : la page que l'humain regarde, et les données que le logiciel paie. Personne ne vérifie qu'ils disent la même chose. Image : un chèque dont les chiffres et les lettres diffèrent. |
| 1:30–3:30 | **Démo** : `lanceurs/ENVOYER-FRAUDES-DEMO.bat` (facture normale payée ; compte différent dans les données → refusée ; PDF retouché ; nom sosie ; doublon maquillé), puis le fichier de virements d'un autre logiciel → « N'envoyez pas ce fichier ». |
| 3:30–4:20 | **Les chiffres.** 25 fraudes reconstruites à partir de cas publiés : notre propre version d'hier en laissait payer 7 sur 17 ; aujourd'hui 0, sans fausse alerte sur les factures honnêtes piégeuses. 70 mails au total, ~20 ms par mail. Dire que c'est notre jeu d'essai. |
| 4:20–5:00 | **Pourquoi nous.** Les autres vérifient « ce compte appartient-il à cette société ? ». Nous vérifions « ce document dit-il la même chose à l'humain et à la machine ? », nous contrôlons le fichier juste avant la banque, et un compte refusé chez un client prévient les autres. Preuve de chaque lot scellée sur Avalanche. |

Questions probables sur cette direction :
- *« Pennylane ne le fait pas déjà ? »* — D'après ce qu'ils publient, ils lisent et paient ; les vérificateurs d'IBAN
  (Trustpair, Sis ID) répondent à « ce compte est-il à cette société ». Aucun ne compare la page et les données
  d'une même facture, à notre connaissance. On ne les remplace pas : on se place devant eux, et on contrôle leur
  fichier de virements.
- *« Vos chiffres sont sur vos propres données ? »* — Oui, et on le dit : il n'existe pas de base publique de vraies
  factures frauduleuses. Chaque cas reproduit une fraude publiée, source à l'appui. Le chiffre honnête est le
  « avant / après » sur notre propre outil.
- *« Et si un client signale un compte honnête ? »* — Un signalement ne produit qu'une demande de vérification, jamais
  un refus, et jamais sur un compte déjà dans le carnet de l'entreprise.
- *« Où est Avalanche ? »* — Registre de preuves : l'empreinte de chaque fichier de virements est scellée sur notre
  contrat Fuji. Elle prouve ce qui a été contrôlé et quand, sans que nous puissions la réécrire.

Le reste de ce document décrit le pitch précédent (pare-feu d'agents IA, coffre Avalanche) : à garder en réserve
pour les questions, pas pour le déroulé.

## Positionnement (à dire tôt, avant que le jury le pense à notre place)
Des outils comme Pennylane, Libeo ou Spendesk paient déjà des factures automatiquement. Nous ne sommes pas un
concurrent de plus sur ce marché : **VaultGuard est le contrôleur de sécurité qui se place devant le paiement**,
pour n'importe quel agent IA ou outil qui tient le chéquier. Plus un outil automatise, plus une fausse facture
passe vite si personne ne vérifie *qui a demandé le paiement et pourquoi* — c'est précisément le sujet de la
Track 1, axe 3 (supervision des agents IA financiers). Le parcours « boîte mail → virement » de cette démo est une
démonstration de bout en bout ; le produit vendable est la couche de contrôle, qui se branche derrière Pennylane,
derrière l'outil du client, ou en autonome comme ici.

## Structure (chronométrée)
| Temps | Qui | Contenu |
|---|---|---|
| 0:00–0:30 | Orateur 1 | **Accroche** : « Demain, votre comptable sera un agent IA. Il lit vos factures et il a la clé du coffre. Que se passe-t-il quand une facture lui parle ? » |
| 0:30–1:00 | Orateur 1 | **Problème** : injection de prompt (n°1 OWASP LLM 2025, au cœur du risque n°1 OWASP Agentic 2026), fraude au changement de RIB, adresses sosies. Un LLM ne distingue pas fiablement donnée et instruction : aucun prompt ne règle ça. Positionnement ci-dessus en une phrase. |
| 1:00–2:15 | Orateur 2 | **Démo live** (script ci-dessous). |
| 2:15–2:45 | Orateur 1 | **Pourquoi c'est solide** : 2 couches indépendantes. Le pare-feu comprend le contexte ; le contrat Avalanche garantit une perte maximale **bornée et vérifiable**, même si l'IA ET le serveur sont piratés. Chiffré sur 45 mails d'essai : 33 fraudes/anomalies arrêtées sur 33, 0 fausse alerte sur 12 factures honnêtes (`docs/METRIQUES.md`). |
| 2:45–3:00 | Orateur 1 | **Vision** : la brique de contrôle interne de toute entreprise qui donne un budget à un agent. « Ne faites pas confiance au LLM. Bornez-le. » |

## Script de démo — parcours boîte mail (recommandé, répond directement à l'axe 3)
http://localhost:8000/app, menu « 2. Factures reçues » (connecté en client de démo).
1. Montrer l'adresse de dépôt : chaque entreprise a la sienne, part aléatoire non devinable.
2. `lanceurs/ENVOYER-FACTURES-DEMO.bat` : déposer le mail normal (payé), celui au RIB changé (refusé : « ce n'est pas le
   compte enregistré »), celui à instructions cachées (refusé), celui d'un expéditeur imité (jamais ouvert, compteur
   « écarté sans être lu »). Ouvrir « Détail » sur un refus : raison en clair, aucune donnée de la facture recopiée.
3. **Payer en euros** : « Préparer le fichier de virements » → fichier SEPA téléchargeable, empreinte scellée sur
   Avalanche (vrai contrat Fuji si `CHAIN=web3`, lien vers l'explorateur).
4. « Cette facture a-t-elle déjà été payée ? » : preuve copiable, sans recopier la facture.

## Script de démo — scénarios d'attaque (secours, si le temps presse)
http://localhost:8000/demo, bouton « Mode présentation » pour le projecteur.
1. Onglet **Comparer** → « Tout comparer » : le tableau rouge/vert dit tout en 10 secondes.
2. Onglet **Démonstration**, mode « Aucune protection » → « Instruction cachée » : −0.09 AVAX. Montrer le commentaire caché.
3. Même situation en « VaultGuard complet » : arrêté, et le fournisseur est quand même payé. Ouvrir « Détails techniques ».
4. **Adresse appât** : l'IA manipulée vise l'adresse piège → coffre gelé instantanément.
5. **Agent compromis qui insiste** en « Contrat seul » : sans aucun pare-feu, le contrat se gèle tout seul (disjoncteur).
6. **Bac à sable** : « Essayez de nous pirater » → inviter un juré à taper sa propre facture piégée.
7. Onglet **Coffre** (vrai coffre Fuji) : règles on-chain, lien Snowtrace, « Rapport scellé » + « Sceller sur la blockchain ».

**Plan B** si le Wi-Fi tombe : tout fonctionne hors-ligne (simulation fidèle au contrat, prouvée par un test de parité ;
boîte mail = dossier local, coffre simulé). Vidéo de 60 s en secours.

## Ce qui est nouveau (à dire)
- **Boîte de dépôt par entreprise** : adresse non devinable, expéditeurs de confiance, exigence SPF/DKIM/DMARC —
  un mail non autorisé ou imité n'est jamais ouvert.
- **Paiement en euros, sans crypto pour le client** : fichier de virements SEPA, validé une fois par l'entreprise
  dans sa banque ; VaultGuard ne détient jamais l'argent. Avalanche sert à sceller la preuve, pas à faire circuler
  la monnaie côté client.
- **Mentions légales et facture électronique** : SIREN/TVA vérifiés, option de contrôle via l'annuaire public des
  entreprises de l'État.
- **Adresses appâts (honeytokens) pour agents IA** : une adresse que seul un agent manipulé paierait → gel immédiat.
- **Disjoncteur on-chain** : trop de refus → pause automatique, sans dépendre d'aucun serveur.
- **Délai anti-changement de RIB** (facture comme coffre) : un nouveau fournisseur n'est payable/habituel qu'après
  un délai (24 h).
- **Rapports d'audit scellés on-chain** : l'empreinte SHA-256 du rapport, et maintenant celle de chaque fichier de
  virements, est ancrée sur Avalanche.

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
- *« En quoi c'est différent de Pennylane / Libeo / Spendesk ? »* → Eux automatisent le paiement ; nous vérifions
  *qui* a demandé le paiement et *pourquoi* avant qu'il parte, en particulier quand c'est un agent IA qui lit les
  factures. Nous ne stockons pas les factures (zéro conservation), et la preuve est scellée sur une blockchain que
  nous ne contrôlons pas seuls. Nous sommes complémentaires, pas concurrents : la couche se branche derrière leur outil.
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
