# SecureHorizons-Prep

Préparation du hackathon **Secure Horizons** (10–11 oct 2026, ESSEC Cergy, 36 h). Équipe d'Ozgun sur la
**Track 1 « Guardians of Value »** (sécurité financière / actifs numériques — jury Team1 Avalanche, KPMG, KRYPTOSPHERE).

- `vaultguard/` → **le projet** (pare-feu de paiements pour agents IA sur Avalanche). Son contexte complet est dans
  `vaultguard/AGENTS.md` (+ `vaultguard/CLAUDE.md`). Travailler depuis ce dossier de préférence.
- `GUIDE-VAULTGUARD.pdf` → guide complet pour Ozgun (actions, entraînement, démo). Source : `vaultguard/docs/guide.html`, régénérer avec `vaultguard/scripts/build-guide.ps1`.
- `secure-agent-kit/` → ancien prototype générique (garde-fou d'outils pour agent IA) dont VaultGuard reprend les idées.
- `1-A-LIRE/` → OWASP Top 10 LLM 2025, OWASP Agentic 2026, Agentic Threats & Mitigations (références du pitch).

État (6 oct 2026) : **v3 produit multi-clients terminée** (8 étapes construites par Antigravity, revues et durcies par
Claude), dépôt privé GitHub `Xenolevrai/SecureHorizon` à jour, CI verte. Sécurité : `vaultguard/docs/SECURITE.md`,
audit `scripts/security-audit.sh` (29/29).

**Hackathon en cours (10-11 oct 2026). État au 10 oct après-midi :** contrat `AgentVault` déployé sur Fuji
(`0x30c9A13FACf3Be404C1Ea0333D31165Fe1f0d793`), `CHAIN=web3`, tests 148 + audit 29/29 verts. Parcours de A à Z
disponible de deux façons : fichiers de factures (`vaultguard/TRAITER-FACTURES.bat`) et vraie boîte mail IMAP
(`vaultguard/LIRE-MAILS.bat`, config `vaultguard/examples/.env.mail`) — détails dans `vaultguard/docs/PARCOURS-A-Z.md`.
Les règles officielles (guide Notion + Track 1) sont résumées dans **`vaultguard/docs/HACKATHON.md` : le lire en
premier**, puis `vaultguard/AGENTS.md` §8 et §6.

**10 oct soir — demandes de l'équipe traitées** (commit `1c08384`, poussé) : zéro conservation (la base ne garde que
des empreintes SHA-256 des factures), lecteur de factures multi-formats côté client (`vaultguard/sdk/invoice_reader.py`),
contrôle de cohérence des prix, boîte mail dédiée, factures en euros (règlement de démo en AVAX, en réel EURC).
Réponses de l'équipe sur blockchain / confiance / argent réel / légalité / marché :
**`vaultguard/docs/CONFIANCE-ARGENT-LEGAL.md`**. Ajoutés ensuite : preuve de paiement et recherche « facture déjà
payée ? », tableau de bord `/app` réécrit en langage simple, `docs/INSTALLATION-CLIENT.md` (mise en place chez une
entreprise) et `docs/EXPLIQUER-SIMPLEMENT.md` (pitch simple, lien avec le sujet : axe 3 de la Track 1, pas hors
sujet). 174 tests + audit 29/29 verts. Le dépôt GitHub contient aussi une
copie du dossier parent dans `vaultguard/preparation/`. Ligne de l'équipe : rester centré Track 1 / Avalanche.

**10 oct, fin de journée — nouvelle direction de l'équipe : la boîte de dépôt des factures.** Chaque entreprise
reçoit une adresse mail fournie par nous, y transfère ses factures ; seuls les expéditeurs qu'elle a autorisés (et
prouvés par SPF/DKIM/DMARC) sont lus ; VaultGuard répond « bonne à payer / à vérifier / refusée ». Aucun paiement et
pas d'Avalanche dans ce parcours pour l'instant ; le fournisseur doit toucher des **euros** sur son IBAN (virement,
ou EURC sur Avalanche reconverti par un prestataire agréé : étape suivante, non construite ; Avalanche = registre de
preuves). Construit et testé : `vaultguard/agent/inbox.py`, `vaultguard/agent/mail_agent.py`, menu « 2. Factures
reçues » de `/app`, `vaultguard/ENVOYER-FACTURES-DEMO.bat`. **Lire `vaultguard/docs/BOITE-FACTURES.md`** (essai en
3 minutes, image du vigile devant la boîte aux lettres) et `vaultguard/docs/METRIQUES.md` (chiffres de détection).
Le projet précédent (coffre Avalanche, API `/v1`) est conservé. Restent à faire par Ozgun : brancher une boîte Gmail
de test, **dégeler le coffre Fuji** (gelé, voir AGENTS.md §6) s'il veut montrer le parcours Avalanche.

**Gel des livrables : dimanche 11 oct 12h00.** Restent : vidéo 2-3 min, deck 8 slides (dont slide conformité), fiche
de défense 1 page, playbook de réponse, accès du jury au dépôt, métriques chiffrées, et
demander à un organisateur comment s'applique la règle « cœur du projet développé pendant l'événement » (VaultGuard
existait avant le 10 oct — point de vigilance signalé à Ozgun, pas encore tranché).
`AWS Participant Guide - Secure Horizons (PDF).pdf` : compte AWS d'équipe (Bedrock, `us-east-1`, pas de production),
non utilisé pour l'instant.

**À savoir pour la prochaine session :** la base de démo locale a été recréée le 10 oct au soir et Ozgun essaie le
parcours avec `vaultguard/docs/ESSAYER.md` (`TRAITER-FACTURES.bat`, `REJOUER-MAILS.bat`, `RECREER-DEMO.bat`). Lui
demander d'abord ce qu'il a observé. L'équipe trouve le projet dur à expliquer : parler simplement, sans jargon.
Manque principal face à la grille : les chiffres de détection (30 %). Point faible à assumer au pitch : en réel le fournisseur reçoit des EURC sur un portefeuille, pas un
virement bancaire.

Ozgun alterne entre Claude Code et **Antigravity** (règles dans `vaultguard/.agent/`). En début de session : lire
`vaultguard/AGENTS.md` §8 puis §6 ; en fin de session : mettre §6 à jour.
