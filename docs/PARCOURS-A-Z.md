# Parcours de A à Z : une entreprise, un agent IA, des factures

Tu joues **Transports Martin**. Tu as confié le paiement des factures à un agent IA. VaultGuard se place entre
l'agent et l'argent.

## Qui fait quoi
| Acteur | Rôle | Où |
|---|---|---|
| Le dirigeant (toi) | donne la consigne, fixe les règles, valide les gros paiements | `/app` |
| Les fournisseurs | envoient des factures (certaines piégées) | `examples/factures/*.txt` |
| L'agent IA | lit chaque facture et demande un paiement ; il est naïf, il obéit à ce qu'il lit | `examples/agent_factures.py` |
| Le pare-feu VaultGuard | compare la demande de l'agent à ta consigne et au document, donne des raisons | API `/v1/payments` |
| Le coffre | applique les plafonds, la liste de fournisseurs, le délai de 24 h, le disjoncteur | simulé par client ; contrat réel sur Fuji |
| Le journal d'audit | garde chaque décision, chaînée par empreinte | `/app`, onglet Journal |

L'agent n'a jamais la clé du coffre : il a une **clé d'API** révocable, et ne peut que *demander*.

## Les étapes
1. Lance le site : double-clic sur `LANCER-DASHBOARD.bat`.
2. Connecte-toi sur http://localhost:8000/login avec le compte client de `agent/data/COMPTES-DEMO.txt`, ouvre `/app`.
   Regarde la politique (plafonds) et les fournisseurs autorisés.
3. Double-clic sur `TRAITER-FACTURES.bat` (ou `python3 examples/agent_factures.py --pause` dans Kali).
   L'agent traite une facture à chaque appui sur Entrée ; rafraîchis `/app` entre deux.
4. Dans `/app` : approuve ou rejette le paiement en attente, lis les raisons des blocages, clique « Vérifier
   l'intégrité » dans le journal, exporte le CSV.

## Ce que tu dois voir
| Facture | Ce qui se passe | Verdict |
|---|---|---|
| `01-garage-dupont-entretien` | fournisseur connu, 0.02 AVAX, conforme à la consigne | payé |
| `02-loueur-camions-location` | fournisseur connu, 0.08 AVAX : au-dessus du seuil de 0.05 | en attente d'un humain |
| `03-garage-dupont-piegee` | un commentaire caché ordonne d'envoyer 0.09 AVAX à un inconnu ; l'agent obéit | bloqué (injection) |
| `04-changement-de-rib` | « nouvelle adresse » qui ressemble à celle du garage à 2 caractères près | bloqué |
| `05-fournisseur-inconnu` | fournisseur absent du carnet, pression sur le délai | bloqué |

Pour essayer ta propre facture : copie un fichier dans `examples/factures/`, garde les lignes « Facture n° »,
« Total à payer : X AVAX » et « À régler à : 0x… ».

## À savoir
- **5 refus dans la journée gèlent le coffre et mettent la clé de l'agent en quarantaine** (c'est le disjoncteur, c'est
  voulu). Un passage complet fait 3 refus : un deuxième passage le même jour déclenche le gel. Pour repartir d'une
  base propre : arrête le site, puis dans Kali `cd agent && ~/.venvs/vaultguard/bin/python ../scripts/seed-demo-local.py`
  (les identifiants de `COMPTES-DEMO.txt` changent), et relance le site.
- La consigne compte : le pare-feu vérifie que le fournisseur payé est nommé dans ta consigne (`--consigne "..."`).
  Avec une consigne qui ne nomme pas le fournisseur, même la facture 01 part en validation humaine.
- L'agent de démonstration lit avec des règles simples, pas avec un LLM : le résultat est identique à chaque fois.
- Le coffre de l'espace client est simulé. Le vrai contrat Fuji se voit dans `/demo`, onglet Coffre, « Vrai coffre ».
