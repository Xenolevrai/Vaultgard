# Détection de fraude à la facture — ce qui nous distingue

Direction prise le 10 octobre au soir, après le retour des juges (« votre solution existe déjà, démarquez-vous ») :
**une seule chose, la détection des fraudes à la facture, et en particulier celles que la facture électronique
rend possibles.** Ce document dit quoi, pourquoi, avec quelles preuves, et comment le montrer.

## 1. L'idée en trois phrases

Depuis le **1er septembre 2026**, toute entreprise française doit pouvoir recevoir des factures électroniques.
Une facture électronique, c'est **deux documents en un** : la page que l'humain regarde (le PDF) et les données que
les logiciels lisent pour payer (le XML caché dedans). **Rien n'oblige les deux à dire la même chose, et personne ne
le vérifie** : la plateforme agréée transporte la facture, le logiciel comptable lit le XML, l'humain valide le PDF.

Image à utiliser : *un chèque dont le montant en chiffres et le montant en lettres ne sont pas les mêmes. La banque
le refuse. Pour une facture électronique, aujourd'hui, personne ne compare.*

## 2. Pourquoi les fraudes continuent malgré les logiciels existants

| Outil | Ce qu'il vérifie | Ce qu'il ne voit pas |
|---|---|---|
| Plateformes agréées de facturation électronique | le format du XML, la transmission à l'administration | si le XML dit la même chose que le PDF ; si l'IBAN est le bon |
| Pennylane, Libeo, Spendesk (paiement de factures) | lisent la facture, préparent le paiement, parfois vérifient l'IBAN | une facture dont la page est correcte et les données fausses |
| Trustpair, Sis ID, Mata (vérification d'IBAN) | « ce compte appartient-il à cette société ? » | un compte ouvert au nom d'une société au nom presque identique ; un doublon ; un PDF retouché |
| La banque (vérification du bénéficiaire, depuis oct. 2025) | « le nom saisi correspond-il au titulaire du compte ? » | elle exécute le fichier qu'on lui envoie ; les entreprises peuvent désactiver ce contrôle pour les fichiers de virements en masse |

Ce tableau vient de leur documentation publique et d'articles de presse (sources en bas) : nous n'avons pas testé
ces produits. À dire tel quel au jury : « d'après ce qu'ils publient ».

## 3. Ce que VaultGuard contrôle maintenant

Chaque contrôle répond à un mode opératoire réel, décrit par une source citée.

| Contrôle | En une phrase | Fraude réelle visée |
|---|---|---|
| **La page contre les données** (nouveau) | on lit le PDF comme un humain et le XML comme un logiciel, et on compare le compte bancaire, le montant, le numéro et le nom du vendeur | IBAN du fraudeur dans le XML, compte légitime sur le PDF ; montants HT et TTC intervertis (Supervizor) |
| **PDF retouché** (nouveau) | un éditeur de PDF laisse l'ancienne version dans le fichier : on la retrouve et on la compare | vraie facture récupérée puis modifiée (DAF Magazine, La Banque Postale) |
| **Nom sosie** (nouveau) | « Garage Dupond » avec un autre compte que « Garage Dupont » | sociétés créées avec un nom approchant (Supervizor) |
| **Fausse facture de registre** (nouveau) | air officiel + « inscription » + petite mention « ceci est une offre » | arnaque aux annuaires professionnels (DGCCRF) |
| **Société française, compte à l'étranger** (nouveau) | numéro d'entreprise français, mais compte en Lituanie, au Portugal… | RIB d'une banque portugaise, 189 893 € perdus (Cour de cassation, 9 sept. 2026) |
| **Doublon maquillé** (nouveau) | la lettre O à la place d'un zéro, ou « -BIS » après le numéro | la facture électronique ne garantit pas l'absence de doublons (Supervizor) |
| **Fractionnement** (nouveau) | deux factures moyennes en 24 h qui, ensemble, dépassent le seuil de validation | contournement classique du seuil de signature |
| **IBAN écrit pour échapper à la lecture** (nouveau) | « LT60-3250-… » ou « LT60.3250.… » reste un IBAN | contournement des lecteurs automatiques |
| **Alerte partagée** (nouveau) | un compte refusé pour fraude chez une entreprise prévient les autres, sans rien révéler (empreinte seulement) | le même compte de « mule » sert contre plusieurs victimes |
| **Dernier contrôle avant la banque** (nouveau) | on dépose le fichier de virements de n'importe quel logiciel : chaque ligne est comparée au carnet de fournisseurs | « toute fraude finit logée dans le fichier de paiement » (DAF Magazine) |
| Carnet d'IBAN | le compte payé est celui que l'entreprise a enregistré, jamais celui de la facture | changement de RIB |
| Expéditeur prouvé | un mail d'une adresse imitée n'est même pas ouvert | adresse « ne différant que d'une lettre », 103 375 € perdus (Cour de cassation, 17 juin 2026) |
| Instructions cachées | texte invisible destiné à tromper un assistant IA | injection de prompt (OWASP LLM01) |
| Mentions légales | SIREN et TVA cohérents, annuaire public en option | faux fournisseur |

Où est le code : `agent/fraud.py` (les contrôles), `agent/inbox.py` (`judge`, le verdict), `sdk/invoice_reader.py`
(lecture séparée de la page, du XML et des anciennes versions d'un PDF), `agent/transfers.py` (`audit_file`).

## 4. Les chiffres

`docs/METRIQUES.md`, reproductible par `cd agent && python3 ../scripts/detection-metrics.py`.

Jeu d'essai « modes opératoires réels » (`examples/fraudes_reelles.py`, 25 mails) :

| | Notre version précédente | Maintenant |
|---|---|---|
| Fraudes payées sans alerte | **7 sur 17** | **0 sur 17** |
| Fausses alertes sur des factures honnêtes piégeuses | 2 sur 8 | **0 sur 8** |
| Fraudes arrêtées avec la bonne explication | — | 16 sur 16 |

Avec le premier jeu d'essai : 70 mails, 50 fraudes ou anomalies arrêtées sur 50, 20 factures honnêtes passées
sur 20, une vingtaine de millisecondes par mail.

**Honnêteté à garder au pitch.** Il n'existe pas de base publique de vraies factures frauduleuses : les victimes
ne les publient pas. Nous avons donc reconstruit chaque fraude à partir d'un cas publié (deux arrêts de la Cour de
cassation de 2026, La Banque Postale, la DGCCRF, Supervizor, DAF Magazine). Le chiffre fort n'est pas « 100 % » —
c'est notre jeu d'essai — c'est **« notre propre version d'hier laissait payer 7 de ces fraudes sur 17 »**.

## 5. La démonstration (2 minutes)

1. `lanceurs/LANCER-DASHBOARD.bat`, puis http://localhost:8000/app, menu « 2. Factures reçues ».
2. `lanceurs/ENVOYER-FRAUDES-DEMO.bat` dépose 7 mails un par un :
   - une facture électronique normale → **bon à payer** ;
   - la même, compte habituel sur la page, compte lituanien dans les données → **refusée**, « la page que vous
     voyez et les données lues par les logiciels ne disent pas la même chose » ;
   - 234 € sur la page, 432 € dans les données → **refusée** ;
   - PDF retouché avec un éditeur en ligne → **à vérifier**, « l'ancienne version est encore dans le fichier » ;
   - « Garage Dupond » → **refusée**, nom sosie ; faux registre officiel → **refusée** ; doublon avec la lettre O
     → **refusée**.
3. Bloc « Dernier contrôle avant la banque » : déposer `examples/virements/virements-autre-logiciel.xml` →
   « N'envoyez pas ce fichier » : le compte du loueur y a été remplacé par un compte en Lituanie.

Phrase de clôture : « Ces fraudes ne se voient pas en regardant la facture. C'est pour ça qu'elles passent. »

## 6. Rester dans le sujet (Track 1, Avalanche)

- Track 1 « Guardians of Value » = sécuriser les transactions financières : la fraude au virement est le cœur du
  sujet. Fonctions NIST : **Detect** (les contrôles ci-dessus) et **Respond** (refus, envoi à une personne, alerte
  aux autres entreprises, blocage du fichier avant la banque).
- Avalanche reste le **registre de preuves** : l'empreinte de chaque fichier de virements est scellée sur le
  contrat déployé sur Fuji (`anchorReport`). Suite naturelle, non construite : sceller aussi la liste des
  empreintes de comptes signalés, pour qu'aucun acteur — nous compris — ne puisse la modifier en douce.
- Les agents IA : ce sont eux qui liront le XML demain. Une facture dont la page est honnête et les données
  piégées est exactement l'attaque contre un agent de paiement (axe 3 de la Track 1).

## 7. Ce que nous ne faisons pas (à dire avant qu'on nous le demande)

- Nous ne vérifions pas auprès de la banque que le compte appartient bien à la société (c'est le métier de
  Trustpair et Sis ID ; on peut se brancher dessus).
- Un faux fournisseur entièrement nouveau et crédible part vers une personne, qui peut se tromper.
- Une facture scannée (image) n'est pas lue : elle part vers une personne.
- Si le vrai fournisseur est complice, ou si la boîte mail d'un employé autorisé est piratée, le carnet d'IBAN et
  le seuil limitent les dégâts sans les empêcher.
- L'alerte partagée n'a de valeur qu'avec plusieurs entreprises clientes ; une entreprise malveillante peut signaler
  un compte honnête, mais cela ne produit qu'une demande de vérification, jamais un refus, et jamais sur un compte
  déjà présent dans le carnet d'une entreprise.
- Les indices de retouche d'un PDF sont des indices : un PDF entièrement recréé n'en laisse pas.

## 8. Sources

- Supervizor, « Les risques cachés de la facturation électronique » —
  https://www.supervizor.com/fr/blog/risques-caches-facturation-electronique
- DAF Magazine, « Profitez du passage à la facture électronique pour sécuriser… » —
  https://www.daf-mag.fr/Thematique/fonction-finance-1242/Breves/Profitez-du-passage-a-la-facture-electronique-pour-securiser-votre-384453.htm
- La Banque Postale, « Usurpation d'identité et vraie facture : les fraudes au RIB version 2025 » (64 % des
  entreprises visées par au moins une tentative en 2023, 37 % victimes d'une fraude aboutie) —
  https://www.labanquepostale.fr/entreprises/actualite/2025/fraudes-rib.html
- Cour de cassation, 9 septembre 2026, n° 25-15.225 (RIB portugais, 189 893,14 € et 175 404,11 €) —
  https://www.lemondedudroit.fr/decryptages/379-actualite-juridique/105786-arnaque-au-faux-rib-charge-de-la-preuve.html
- Cour de cassation, 17 juin 2026, n° 24-13.306 (adresse à une lettre près, 103 375,64 €) —
  https://www.lemondedudroit.fr/decryptages/379-actualite-juridique/104799-l-usurpateur-de-creancier-n-est-pas-creancier-apparent.html
- DGCCRF, « Annuaires professionnels : une arnaque qui perdure » —
  https://www.economie.gouv.fr/dgccrf/actualites/annuaires-professionnels-une-arnaque-qui-perdure
- Cabinet Hayot Expertise, « Faux RIB fournisseur : 12 contrôles » —
  https://hayot-expertise.fr/blog/fraude-rib-fournisseur-controles-virement-2026
- Détection de PDF retouchés — https://www.helpnetsecurity.com/2025/07/07/detect-pdf-tampering-forgery/
- Libeo, vérification des IBAN fournisseurs (SEPAmail Diamond) —
  https://intercom.help/libeo/fr/articles/5881168-verification-des-ibans-fournisseurs
- Trustpair, moteur d'évaluation — https://docs.trustpair.com/docs/trustpair-evaluation-engine
- Calendrier de la réforme (réception obligatoire au 1er septembre 2026) —
  https://www.keobiz.fr/le-mag/facturation-electronique-calendrier-2026-2027/
