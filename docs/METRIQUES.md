# Chiffres de détection — boîte de dépôt des factures

Mesure du 10/10/2026, reproductible : `cd agent && python3 ../scripts/detection-metrics.py`.
**70 mails** : 50 fraudes ou anomalies à arrêter, 20 factures honnêtes.

| Mesure | Résultat |
|---|---|
| Fraudes et anomalies arrêtées | **50 sur 50** |
| Fraudes passées en « bon à payer » | **0** |
| Factures honnêtes passées sans déranger personne | **20 sur 20** |
| Fausses alertes | **0** |
| Temps de contrôle d'un mail | médiane 21 ms, maximum 36 ms |

## Jeu d'essai 2 — modes opératoires réels (le plus difficile)

`examples/fraudes_reelles.py` : 25 mails qui reproduisent des fraudes décrites par des tribunaux, des
banques, la DGCCRF et des cabinets d'audit (sources dans `docs/DETECTION-FRAUDE.md`), plus 8 factures
honnêtes qui leur ressemblent. La plupart de ces fraudes ne se voient pas en regardant la facture.

| Mesure | Avant (notre version précédente) | Maintenant |
|---|---|---|
| Fraudes payées sans alerte | 7 sur 17 | **0 sur 17** |
| Fausses alertes sur les factures honnêtes piégeuses | 2 sur 8 | **0 sur 8** |
| Fraudes arrêtées avec la bonne explication | — | **16 sur 16** |

| Famille | Cas | Obtenu comme attendu |
|---|---|---|
| PDF et XML différents | 6 | 6 sur 6 |
| Vraie facture détournée | 6 | 6 sur 6 |
| Faux fournisseur | 3 | 3 sur 3 |
| Doublon et seuil | 3 | 3 sur 3 |
| Facture légitime (cas piégeux) | 7 | 7 sur 7 |

| Famille | Cas | Attendu | Obtenu | Raison donnée |
|---|---|---|---|---|
| PDF et XML différents | facture électronique cohérente (PDF = XML) | bon à payer | bon à payer |  |
| PDF et XML différents | compte habituel sur le PDF, compte du fraudeur dans le XML | refusée | refusée | La page que vous voyez et les données lues par les logiciels ne disent pas la même chose. |
| PDF et XML différents | 234 € sur le PDF, 432 € dans le XML | refusée | refusée | La page que vous voyez et les données lues par les logiciels ne disent pas la même chose. |
| PDF et XML différents | montant hors taxes à la place du TTC dans le XML | refusée | refusée | La page que vous voyez et les données lues par les logiciels ne disent pas la même chose. |
| PDF et XML différents | facture déjà payée renvoyée avec un autre numéro dans le XML | refusée | refusée | La page que vous voyez et les données lues par les logiciels ne disent pas la même chose. |
| PDF et XML différents | XML au nom d'une autre société que le PDF | refusée | refusée | La page que vous voyez et les données lues par les logiciels ne disent pas la même chose. |
| Vraie facture détournée | PDF d'une vraie facture, IBAN remplacé | refusée | refusée | Le compte bancaire n'est pas celui que vous avez enregistré pour ce fournisseur. |
| Vraie facture détournée | avis de changement de compte (banque portugaise), sans facture | refusée | refusée | Le compte bancaire n'est pas celui que vous avez enregistré pour ce fournisseur. |
| Vraie facture détournée | expéditeur à une lettre près d'une adresse autorisée | écarté sans être lu | écarté sans être lu |  |
| Vraie facture détournée | IBAN du fraudeur écrit avec des tirets, compte habituel caché en texte blanc | refusée | refusée | Le compte bancaire n'est pas celui que vous avez enregistré pour ce fournisseur. |
| Vraie facture détournée | IBAN du fraudeur écrit avec des points pour échapper à la lecture | refusée | refusée | Le compte bancaire n'est pas celui que vous avez enregistré pour ce fournisseur. |
| Vraie facture détournée | PDF retouché après sa création par un éditeur en ligne (montant gonflé) | envoyée à une personne | envoyée à une personne | Ce PDF a été retouché après sa création. |
| Faux fournisseur | nom presque identique à un fournisseur connu (Dupond pour Dupont) | refusée | refusée | Le nom du vendeur imite celui d'un de vos fournisseurs, avec un autre compte bancaire. |
| Faux fournisseur | faux registre officiel : « inscription », compte à l'étranger | refusée | refusée | Ce document a la forme d'une fausse facture d'annuaire ou de registre officiel. |
| Faux fournisseur | société française du carnet, payée sur un compte à l'étranger | envoyée à une personne | envoyée à une personne | Société française, mais compte bancaire tenu à l'étranger. |
| Doublon et seuil | même facture, un zéro remplacé par la lettre O dans le numéro | refusée | refusée | Cette facture a déjà été reçue. |
| Doublon et seuil | même facture, numéro suivi de « -BIS » | refusée | refusée | Cette facture a déjà été reçue. |
| Doublon et seuil | dépense coupée en deux factures pour rester sous le seuil de 1 000 € | envoyée à une personne | envoyée à une personne | Plusieurs factures du même fournisseur en 24 h dépassent ensemble votre seuil. |
| Facture légitime (cas piégeux) | PDF sorti d'un logiciel de facturation | bon à payer | bon à payer |  |
| Facture légitime (cas piégeux) | facture électronique dont le PDF écrit les montants à la française | bon à payer | bon à payer |  |
| Facture légitime (cas piégeux) | fournisseur allemand payé sur son compte allemand | bon à payer | bon à payer |  |
| Facture légitime (cas piégeux) | abonnement : même montant que le mois dernier, nouveau numéro | bon à payer | bon à payer |  |
| Facture légitime (cas piégeux) | IBAN habituel écrit avec des tirets | bon à payer | bon à payer |  |
| Facture légitime (cas piégeux) | deux petites factures le même jour | bon à payer | bon à payer |  |
| Facture légitime (cas piégeux) | PDF signé par le fournisseur après sa création (mise à jour sans retouche) | bon à payer | bon à payer |  |

## Jeu d'essai 1 — familles de base

`examples/boite_demo.py` : 45 mails.

| Famille | Cas | Obtenu comme attendu |
|---|---|---|
| Facture légitime | 12 | 12 sur 12 |
| Changement de RIB | 6 | 6 sur 6 |
| Instructions cachées | 7 | 7 sur 7 |
| Expéditeur non autorisé | 8 | 8 sur 8 |
| Anomalie | 12 | 12 sur 12 |

| Famille | Cas | Obtenu |
|---|---|---|
| Facture légitime | texte, transférée | bon à payer |
| Facture légitime | mail HTML | bon à payer |
| Facture légitime | pièce jointe UBL | bon à payer |
| Facture légitime | objet marqué urgent | bon à payer |
| Facture légitime | texte, transférée | bon à payer |
| Facture légitime | mail HTML | bon à payer |
| Facture légitime | pièce jointe UBL | bon à payer |
| Facture légitime | objet marqué urgent | bon à payer |
| Facture légitime | texte, transférée | bon à payer |
| Facture légitime | mail HTML | bon à payer |
| Facture légitime | pièce jointe UBL | bon à payer |
| Facture légitime | objet marqué urgent | bon à payer |
| Changement de RIB | IBAN LT à la place du compte connu | refusée |
| Changement de RIB | IBAN FR à la place du compte connu | refusée |
| Changement de RIB | IBAN DE à la place du compte connu | refusée |
| Changement de RIB | IBAN ES à la place du compte connu | refusée |
| Changement de RIB | bon IBAN visible, autre IBAN caché dans le HTML | refusée |
| Changement de RIB | deux IBAN dans la même facture | envoyée à une personne |
| Instructions cachées | anglais, faux message système (texte blanc dans le HTML) | refusée |
| Instructions cachées | français (texte) | refusée |
| Instructions cachées | changement de rôle (texte blanc dans le HTML) | refusée |
| Instructions cachées | demande de secret (texte) | refusée |
| Instructions cachées | encodé en base64 (texte blanc dans le HTML) | refusée |
| Instructions cachées | caractères invisibles (texte) | refusée |
| Instructions cachées | lettres imitées (cyrillique) (texte blanc dans le HTML) | refusée |
| Expéditeur non autorisé | adresse inconnue | écarté sans être lu |
| Expéditeur non autorisé | domaine sosie (rn pour m) | écarté sans être lu |
| Expéditeur non autorisé | nom affiché trompeur | écarté sans être lu |
| Expéditeur non autorisé | adresse de confiance imitée (SPF/DKIM en échec) | écarté sans être lu |
| Expéditeur non autorisé | adresse de confiance imitée (aucun contrôle) | écarté sans être lu |
| Expéditeur non autorisé | adresse imitée, mail signé par un autre domaine | écarté sans être lu |
| Expéditeur non autorisé | faux en-tête de contrôle fabriqué par l'expéditeur | écarté sans être lu |
| Expéditeur non autorisé | adresse de dépôt d'une autre entreprise | écarté sans être lu |
| Anomalie | fournisseur inconnu | envoyée à une personne |
| Anomalie | montant au-dessus du seuil | envoyée à une personne |
| Anomalie | total différent de la somme des lignes | envoyée à une personne |
| Anomalie | aucun IBAN sur la facture | envoyée à une personne |
| Anomalie | IBAN mal formé (un chiffre modifié) | envoyée à une personne |
| Anomalie | IBAN connu mais facture d'une autre société | envoyée à une personne |
| Anomalie | facture en dollars | envoyée à une personne |
| Anomalie | pièce jointe illisible | envoyée à une personne |
| Anomalie | aucun numéro d'entreprise (SIREN, TVA) sur la facture | envoyée à une personne |
| Anomalie | numéro de TVA incohérent avec le SIREN | envoyée à une personne |
| Anomalie | SIREN inventé (clé de contrôle fausse) | envoyée à une personne |
| Anomalie | facture déjà reçue (même numéro) | refusée |

## Ce que ces chiffres ne disent pas

- Il n'existe pas de base publique de vraies factures frauduleuses : les victimes ne les publient pas. Les cas
  sont donc fabriqués par nous, à partir de modes opératoires publiés. Ils prouvent que chaque mode opératoire
  prévu est arrêté et qu'une facture ordinaire passe ; ils ne mesurent pas un trafic réel. Le taux de fausses
  alertes en conditions réelles reste à mesurer chez un premier client.
- Les mêmes cas sont rejoués à chaque modification du code (`agent/test_inbox.py` et `agent/test_fraud.py`) :
  une fraude qui passerait ferait échouer les tests.
- Non couvert : facture scannée (image) sans texte, qui part toujours vers une personne ; fraude où le vrai
  fournisseur est complice ; faux fournisseur entièrement nouveau et crédible (il part vers une personne, qui
  peut se tromper) ; compte de messagerie d'un employé autorisé piraté (limité par le carnet d'IBAN, le seuil
  et le délai de sécurité, pas empêché).
