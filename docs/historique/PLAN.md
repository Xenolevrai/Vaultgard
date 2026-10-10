# Plan VaultGuard

## Avant le hackathon (lun 5 → ven 9 oct)
- [ ] Inscription confirmée avant **mar 6 oct 00:00** · Discord + WhatsApp rejoints
- [ ] Repo GitHub privé créé, coéquipiers invités, chacun a lancé `bash scripts/setup.sh` + `bash scripts/test-all.sh`
- [ ] Wallets de testnet créés (Core Wallet), AVAX de test récupérés, contrat déployé sur Fuji
- [ ] Mode `--llm` testé avec une vraie clé API
- [ ] BeforeHack **jeu 8 oct 19h** (Maison des ESSEC) : valider l'idée avec des mentors Team1/KPMG, vérifier le règlement (code pré-existant autorisé ?)
- [ ] Chacun relit `docs/PITCH.md` et connaît la démo

## Répartition des rôles (à adapter à l'équipe)
| Rôle | Périmètre |
|---|---|
| Smart contracts | `contracts/` — nouvelles règles, déploiement Fuji, vérification Snowtrace |
| Agent & sécurité IA | `agent/firewall.py`, `scenarios.py`, LLM-juge, nouvelles attaques |
| Front / démo | `dashboard/` — UX, connexion Core Wallet pour l'owner, vidéo de secours |
| Pitch / business | slides, chiffres marché, Q&A, conformité (angle KPMG) |

## Pendant les 36 h (sam 10 9h → dim 11 17h)
| Créneau | Objectif |
|---|---|
| Sam 9h–11h | Lire les sujets/règles précis, adapter l'histoire au jury, choisir 2–3 extensions du backlog |
| Sam 11h–19h | Développer les extensions (1 par personne), tests verts en continu |
| Sam 19h–23h | Intégration, déploiement Fuji de la version finale, démo bout en bout |
| Sam 23h–dim 8h | Polish UI + slides ; **dormir au moins 4 h par rotation** |
| Dim 8h–12h | Gel des fonctionnalités à 10h, répétitions du pitch ×3, vidéo de secours |
| Dim 12h–17h | Soumission (README, lien repo, vidéo, adresse du contrat), pitch |

## Backlog d'extensions (par rapport impact jury / effort)
1. ⭐ **Paiements USDC (ERC20)** dans la démo — déjà supporté par le contrat, ajouter un MockERC20 au déploiement + sélection du token. *Effort : faible. Jury : Avalanche, KPMG.*
2. ⭐ **LLM-juge** dans le pare-feu : un 2e modèle évalue « cette action correspond-elle à la demande de l'utilisateur ? ». *Effort : faible. Jury : tous.*
3. ⭐ **Délai de grâce (timelock) sur les nouveaux destinataires** : un destinataire ajouté n'est payable qu'après 24 h → contre la fraude au RIB. *Effort : moyen (contrat + MockChain + test).*
4. **Rapport d'audit exportable** (CSV/PDF) depuis les events on-chain + `audit.jsonl`. *Jury : KPMG.*
5. **Signature owner depuis le navigateur (Core Wallet)** pour Approuver/Rejeter/Kill switch. *Jury : Avalanche.*
6. **Plafond par destinataire** et **liste noire** (adresses de scam connues).
7. **Multisig owner** (2 validateurs sur 3) pour les gros montants.
8. **Avalanche L1 / ICM** : discours de vision (politique appliquée cross-chain) — slide plutôt que code.

## Checklist de soumission
- [ ] README à jour (adresse Fuji, captures, commandes)
- [ ] `bash scripts/test-all.sh` vert sur le commit final
- [ ] Aucun secret dans le repo (`git log -p | grep -i private` → rien)
- [ ] Vidéo de démo ≤ 2 min
- [ ] Slides exportées en PDF
