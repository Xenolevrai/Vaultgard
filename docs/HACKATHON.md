# Secure Horizons — règles officielles et position de VaultGuard

Source : guide Notion « Candidate Guide — Track Guidance (EN) » et page « Track 1 — Fintech Security: Guardians of
Value », lus le 10 oct 2026. Emails organisateurs (Fuji, AWS) et `../AWS Participant Guide - Secure Horizons (PDF).pdf`.

## Cadre
- Hackathon **blue team** : chaque projet couvre au moins une fonction du NIST CSF 2.0, idéalement **Detect** ou **Respond**.
- Référentiels attendus : MITRE ATT&CK, MITRE ATLAS, MITRE D3FEND, OWASP Top 10 Agentic.
- Équipes de 5 max. Choix de track confirmable jusqu'au checkpoint de samedi 18h30.
- **« The core of your project must be developed between Saturday 11:30 and Sunday 12:00 »** ; bibliothèques,
  frameworks, modèles et API existants autorisés. VaultGuard v3 existait avant : **à clarifier avec un organisateur**
  (voir « Points ouverts »).
- Éthique : aucune action contre un système réel, aucune donnée personnelle réelle, **zéro secret dans le dépôt** (vérifié par le jury).

## Calendrier
| Quand | Quoi |
|---|---|
| Sam. 11h30 | Début du hacking |
| Sam. 18h30 | Checkpoint (formulaire problème / solution / stack) |
| Dim. 10h00 | Atelier de coaching pitch |
| **Dim. 12h00** | **Gel et dépôt des livrables** |
| Dim. 13h00–14h30 | Round 1 par track : pitch **5 min** + 2 min de questions, jury de 3 experts |
| Dim. 15h25–16h10 | Finale (2 équipes par track) : 3 min + 3 min de questions |

## Livrables (avant dimanche 12h00)
| Livrable | État |
|---|---|
| Dépôt Git accessible au jury, README (problème, architecture, installation, limites connues) | dépôt privé : donner l'accès au jury ; limites connues écrites dans le README |
| Vidéo de démo 2 à 3 min | à faire |
| Pitch deck, 8 slides max (problème, cible, solution, démo, business model, équipe) | à faire |
| Fiche de défense, 1 page (scénario, fonctions NIST CSF, techniques ATT&CK/ATLAS/OWASP, métriques, limites) | à faire |
| Track 1 : PoC de bout en bout, de la détection à la réponse | fait (boîte mail → verdict → fichier de virements scellé sur Fuji, `/app` menu « Factures reçues » ; aussi `examples/agent_factures.py`) |
| Track 1 : playbook de réponse (qui est alerté, quoi est automatique, quoi reste humain, comment c'est documenté) | à écrire |
| Track 1 : slide « conformité » (DORA, LCB-FT, MiCA, AI Act ; comment un auditeur vérifie) | à faire |
| Adresse du contrat dans le dépôt (demande Avalanche) | fait (README) |

## Grille d'évaluation Track 1
| Critère | Poids | Ce que VaultGuard montre |
|---|---|---|
| Efficacité de détection (précision, faux positifs, délai) | 30 % | Jeu d'essai de 45 mails (`docs/METRIQUES.md`, reproductible) : 33 fraudes/anomalies arrêtées sur 33 (0 passée), 12 factures honnêtes sur 12 sans fausse alerte, décision en 21 ms en médiane. C'est notre propre jeu d'essai, pas du trafic réel : à dire au jury. |
| Qualité de la réponse (proportionnée, actionnable) | 20 % | réponse graduée : payer / attente humaine / blocage / quarantaine de la clé / gel du coffre |
| Faisabilité et intégration | 20 % | API `/v1` + SDK, contrat déployé sur Fuji, 148 tests |
| Conformité et explicabilité | 15 % | raisons en clair avec référence OWASP, journal chaîné, rapport scellé on-chain, export CSV |
| Pitch et démo | 15 % | — |

Conseils des organisateurs : un seul scénario traité parfaitement ; montrer des chiffres ; préparer la réponse à
« si votre modèle se trompe, qui est responsable ? » (réponse VaultGuard : la perte maximale est bornée par le
contrat, et tout montant sensible passe par un humain).

## Où VaultGuard se place
Axe 3 de la Track 1, **« Supervision and containment of financial AI agents »** — les pistes citées sont déjà là :
journal de chaque action avec la chaîne d'autorité (mandat de l'utilisateur vs document reçu), détection des
transactions hors périmètre, clé d'agent révocable et expirante, kill switch automatique (disjoncteur, appât),
validation humaine. Touche aussi l'axe 4 (surveillance d'un contrat sur Fuji, pause, rapport).
Fonctions NIST CSF : Identify, Protect, Detect, Respond. Risques OWASP : LLM01, LLM02, ASI01, ASI02, ASI03, ASI10.

Données, argent réel, confiance, légalité (DORA, LCB-FT, MiCA, AI Act, RGPD) et concurrence : voir
`CONFIANCE-ARGENT-LEGAL.md`, matière première de la slide conformité et de la fiche de défense.

## Points ouverts
1. Règle « cœur développé pendant l'événement » : demander à un organisateur ce qui est acceptable et le dire
   honnêtement au jury (ce qui a été fait avant, ce qui a été fait pendant).
2. Métriques : mesurer taux de détection, faux positifs et temps de décision sur un jeu de factures synthétiques.
3. Compte AWS de l'équipe (Bedrock, `us-east-1`, supprimé à la fin, pas de production) : non utilisé pour l'instant.
