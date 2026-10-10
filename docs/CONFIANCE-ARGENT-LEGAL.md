# Données, blockchain, argent réel, légalité : les réponses de VaultGuard

Rédigé le 10 oct 2026 à partir des questions de l'équipe. Les points juridiques sont un cadrage pour le pitch,
**pas un avis d'avocat** : chaque point marqué « à confirmer » doit l'être avant un premier client réel.

## 1. Ce que l'équipe a demandé, et où c'est dans le projet

| Demande | Réponse | Où |
|---|---|---|
| Ne rien stocker, tout appartient au client | Les factures et la consigne sont analysées en mémoire puis oubliées. La base ne garde que leur empreinte SHA-256 | `agent/api_v1.py`, test `test_no_invoice_text_reaches_the_database` |
| Pas de Claude / Gemini / ChatGPT | Le pare-feu est un moteur de règles, sans LLM. Le lecteur de factures n'appelle aucun service | `agent/firewall.py`, `sdk/invoice_reader.py` |
| Le client choisit ce qu'il transmet | Boîte dédiée où il transfère ses factures, expéditeurs autorisés seulement | `examples/agent_mail.py` (`MODE=dediee`) |
| Tous les formats de facture | Texte, HTML, XML UBL et CII, PDF, Factur-X, mail avec pièces jointes, Word. Illisible = humain | `sdk/invoice_reader.py` |
| Cohérence des prix (œufs à 18 €) | Prix unitaire comparé au prix habituel du client, total comparé aux lignes : validation humaine | `firewall.check_invoice`, facture `06` |
| Pas d'intermédiaire | L'agent tourne chez le client. VaultGuard ne lit ni boîte mail ni dossier | `docs/PARCOURS-A-Z.md` |
| Chiffrement des factures (optionnel) | Non fait : il n'y a plus rien à chiffrer au repos. En transit : HTTPS obligatoire (le SDK refuse `http://` hors localhost) | — |

## 2. Comment les factures arrivent jusqu'à nous

**Elles n'arrivent pas chez nous.** Un petit programme, l'agent, tourne chez l'entreprise. Il lit la facture là où
elle se trouve déjà, et n'envoie à VaultGuard que la question « ai-je le droit de payer ceci ? » avec le texte à
contrôler. Trois branchements, du plus simple au plus intégré :

1. **Un dossier** : l'entreprise dépose ou exporte ses factures dans un dossier, l'agent les lit
   (`examples/agent_factures.py`). C'est aussi la sortie naturelle d'une plateforme de facturation électronique.
2. **Une adresse mail dédiée**, par exemple `factures-a-payer@entreprise.fr`, créée chez l'entreprise. Un
   comptable y transfère les factures à payer. L'agent ne voit que cette boîte, n'accepte que les expéditeurs
   listés, et peut effacer le mail une fois traité (`MODE=dediee`). Pas d'accès à la messagerie générale, donc pas
   de lecture de courriels sans rapport.
3. **L'API `/v1`** : l'outil de facturation ou l'agent IA que l'entreprise utilise déjà appelle VaultGuard avant de
   payer (`sdk/vaultguard_client.py`).

Comment les entreprises reçoivent leurs factures aujourd'hui : PDF par mail (le cas dominant en PME), portail du
fournisseur, papier scanné, échanges automatisés entre grands comptes. Depuis le **1er septembre 2026**, toute
entreprise assujettie à la TVA doit pouvoir recevoir des factures électroniques via une plateforme agréée par
l'État, dans un format structuré : Factur-X (un PDF qui embarque les données en XML), UBL ou CII. L'obligation
d'émettre s'étale jusqu'en septembre 2027 pour les PME. Conséquence pour nous : les données structurées deviennent
la norme, le PDF libre par mail reste pour l'étranger et la transition. Nous lisons les deux. Nous ne sommes pas
une plateforme agréée et n'avons pas à l'être : nous intervenons après la réception, au moment de payer.

Limite : pas encore de connecteur direct vers l'API d'une plateforme agréée ou d'un logiciel comptable.

## 3. Ce que VaultGuard garde, exactement

| Conservé | Jamais conservé |
|---|---|
| Adresse du destinataire, montant, libellé du paiement (140 octets max, ex. « Facture GD-2026-1001 ») | Texte des factures et des mails |
| Décision et raisons, rédigées sans citer la facture (« ligne 1 : 6 fois le prix habituel ») | Consigne donnée à l'agent (seule son empreinte) |
| Empreinte SHA-256 de chaque document, inscrite dans le journal chaîné | Noms de fichiers, expéditeurs |
| Comptes utilisateurs, adresses IP des connexions (sécurité) | Lignes de facture et prix de référence du client |

Une empreinte SHA-256 est un identifiant de 64 caractères calculé à partir du document : elle ne permet pas de le
reconstituer, mais le client qui possède l'original peut prouver que c'est bien celui qui a été jugé (dans `/app`,
détail d'un paiement, « Vérifier une facture » : le calcul se fait dans son navigateur).

Limites honnêtes : le texte **transite** en mémoire sur notre serveur le temps de l'analyse. Pour qu'il ne sorte
jamais de l'entreprise, VaultGuard s'installe chez elle (image Docker fournie). Les comptes et les adresses IP sont
des données personnelles : durée de conservation à fixer.

## 4. La blockchain : ce qu'on y fait, et ce qu'on n'y met pas

Avalanche sert à trois choses, et aucune ne touche aux factures :

1. **Le coffre** (`AgentVault`, déployé sur Fuji) : les fonds de l'entreprise y sont, avec ses règles. L'agent ne
   peut que demander. Plafond par paiement et par jour, liste de fournisseurs avec délai, validation humaine,
   gel. Même si l'agent **et** VaultGuard sont piratés, la perte maximale est celle que le contrat autorise.
2. **La preuve** : chaque refus ou paiement émet un événement, et l'empreinte du journal peut être ancrée
   (`anchorReport`). Un auditeur vérifie sans nous faire confiance.
3. **Le règlement** : le coffre paie le fournisseur.

Ce qui est public sur la chaîne : adresses, montants, libellé. C'est une vraie contrainte de confidentialité (un
concurrent pourrait observer les flux). Réponses : libellé réduit à une référence, et surtout une **L1 Avalanche
dédiée**, c'est-à-dire une chaîne dont l'entreprise ou un consortium choisit les validateurs et qui n'est pas
lisible par tous. C'est un argument propre à Avalanche.

## 5. Les factures restent en euros

Rien ne change pour la facturation : le fournisseur facture en euros, la comptabilité reste en euros. Seul le
règlement passe par le coffre. Dans la démo il se fait en AVAX de test, avec un taux fictif. En réel il se ferait
en **euro numérique** : l'EURC (1 jeton = 1 euro, émis par Circle Mint Europe, établissement de monnaie
électronique agréé par l'ACPR, conforme MiCA, disponible sur Avalanche). Le contrat accepte déjà ce type de jeton.

Parcours avec de l'argent réel :
1. L'entreprise garde sa trésorerie en banque. Elle convertit en EURC, chez un prestataire agréé, seulement le
   budget qu'elle confie à l'agent (par exemple 5 000 € par mois) et le dépose dans **son** coffre.
2. L'agent demande, VaultGuard juge, le coffre paie dans les limites.
3. Le fournisseur reçoit des EURC et les reconvertit en euros chez un prestataire agréé.

**La vraie friction est l'étape 3** : le fournisseur doit accepter ce mode de règlement. Trois réponses, à présenter
comme une feuille de route et non comme acquises :
- commencer par les cas où la crypto est déjà admise (fournisseurs étrangers, entreprises du secteur) ;
- passer par un prestataire de paiement agréé qui reçoit les EURC et verse un virement SEPA au fournisseur ;
- utiliser le pare-feu seul devant un virement bancaire classique, la blockchain ne servant alors qu'à la preuve.
  Le pare-feu ne dépend pas du moyen de paiement ; cette variante n'est pas construite.

## 6. Pourquoi une entreprise nous ferait confiance

- Nous ne détenons **ni ses fonds ni sa clé** : le coffre est à elle, elle signe avec son wallet.
- Nous ne détenons **pas ses données** : empreintes seulement, et installation possible chez elle.
- Elle n'a pas à nous croire : le code du contrat est vérifié sur Snowtrace, les règles sont lisibles, le journal
  est chaîné et vérifiable, les refus sont publics.
- Si nous nous trompons ou si nous sommes piratés, la perte est bornée par son contrat, et tout montant sensible
  passe par un humain. C'est la réponse à « si votre modèle se trompe, qui est responsable ? ».
- 172 tests Python, 33 tests du contrat, audit rejoué à chaque version.

Ce qui manque pour une confiance réelle, à dire au jury : audit du contrat par un tiers, société immatriculée et
assurée, contrat de sous-traitance des données, hébergement en Union européenne, et à terme une certification
(ISO 27001).

## 7. Est-ce légal ?

Aujourd'hui, oui sans réserve : réseau de test, aucune valeur réelle, aucune donnée réelle. Pour un usage réel,
c'est **défendable à trois conditions** : ne jamais détenir les fonds, régler en euro numérique régulé, faire
valider le montage par un avocat avant le premier client.

| Sujet | Position | Statut |
|---|---|---|
| Payer un fournisseur en crypto-actif | Aucune loi ne l'interdit entre entreprises d'accord ; l'euro reste la monnaie légale, le fournisseur peut refuser | établi |
| MiCA (règlement européen sur les crypto-actifs) | Un éditeur de logiciel qui ne contrôle pas les clés n'est pas un prestataire de services sur crypto-actifs (considérant 83). Le client signe lui-même | à confirmer : notre clé « guardian » ne peut que geler, jamais déplacer des fonds |
| Services de paiement (DSP2) | Depuis mars 2026, transférer des jetons de monnaie électronique **pour le compte de clients** est un service de paiement. Nous ne transférons rien : le coffre du client exécute | à confirmer ; à ne jamais franchir sans agrément |
| Lutte contre le blanchiment | Les obligations pèsent sur les prestataires régulés (conversion euros/EURC) et sur le client. Carnet de fournisseurs et délai d'activation vont dans ce sens | pas de filtrage des listes de sanctions : limite connue |
| RGPD | Nous sommes sous-traitant (article 28) : contrat écrit, minimisation, sécurité. La minimisation est poussée au maximum | contrat type à rédiger |
| Secret des affaires | Prix, fournisseurs et volumes ne sont pas conservés chez nous ; sur chaîne publique les montants sont visibles, d'où la L1 dédiée | voir §4 |
| Conservation des factures (6 ans fiscal, 10 ans commercial) | Obligation du client, remplie par sa plateforme ou son archivage. Nous ne sommes pas une archive | établi |
| Facturation électronique | Nous n'émettons ni ne recevons de factures au sens fiscal : pas d'agrément de plateforme à obtenir | établi |
| AI Act | Moteur de règles explicable, humain dans la boucle. Le paiement de factures ne figure pas, à notre lecture, parmi les usages à haut risque | à confirmer |
| DORA | Si le client est une entité financière, nous serions un prestataire informatique tiers : exigences contractuelles et de résilience | à prévoir |
| Comptabilité et fiscalité | L'EURC vaut 1 euro : pas de plus-value de change en principe ; écritures à valider par l'expert-comptable du client | à confirmer |

## 8. Le marché est-il bouché ?

| Segment | Acteurs | Ce qu'ils font | Ce qu'ils ne font pas |
|---|---|---|---|
| Paiement de factures fournisseurs | Libeo, Pennylane, Spendesk, Yooz, Esker | Lire, valider et payer les factures ; doublons et montants inhabituels | Borner un agent IA autonome ; preuve indépendante |
| Fraude au virement | Trustpair, Sis ID (de mémoire, non revérifié) | Vérifier qu'un IBAN appartient bien au fournisseur | Contrôler ce qu'un agent IA a lu avant de payer |
| Paiements pour agents IA | Payman, Skyfire, Circle Agent Stack, x402, Visa, Mastercard, AP2 | Wallets d'agents avec plafonds, listes blanches, approbations | Analyser la provenance d'une adresse et l'injection de prompt dans les documents (non vérifié produit par produit) |

« Payer les factures automatiquement » est bouché : ne pas se présenter ainsi. La place de VaultGuard est une
**couche de sécurité indépendante entre l'agent et l'argent**, qui se branche derrière ces outils : elle comprend
d'où vient l'ordre de payer, elle borne la perte par un contrat que personne ne peut contourner, et elle ne voit
pas les données. Une grande entreprise pourrait le construire ; l'avantage est d'être spécialisé, neutre (ni la
banque ni l'éditeur de l'agent) et vérifiable par un tiers.

Le parcours de démonstration (boîte mail, verdict, fichier de virements) ressemble en surface à Pennylane ou Libeo :
c'est volontaire, pour montrer un scénario complet et vérifiable, pas pour concurrencer leur produit. La différence
qui compte au pitch : eux optimisent pour payer vite, nous optimisons pour détecter quand l'ordre de payer a été
manipulé, avec zéro conservation des documents et une preuve que même nous ne pouvons pas falsifier après coup.

## 9. Limites connues

- Lecture des PDF sans dépendance : les PDF scannés, chiffrés ou à polices exotiques ne sont pas lus et partent à
  un humain. Les images demandent l'outil d'OCR `tesseract`, non installé par défaut.
- Le contrôle des prix compare à une liste tenue par le client et envoyée par son agent : il attrape les erreurs,
  pas un agent entièrement compromis. Les bornes dures restent celles du contrat.
- Les factures de démo donnent l'adresse de paiement du fournisseur dans le champ du compte bancaire.
- Pas de connecteur vers une plateforme de facturation agréée, pas de règlement en EURC dans la démo. Le fichier de
  virements SEPA est construit et testé mais jamais importé dans une vraie banque (voir `docs/BOITE-FACTURES.md`).
- Contrat non audité par un tiers, réseau de test uniquement.

## Sources
- Facturation électronique : https://www.previssima.fr/actualite/facturation-electronique-ce-qui-change-pour-les-entreprises-des-le-1er-septembre-2026.html
- RGPD et facturation : https://www.donneespersonnelles.fr/facturation-electronique-rgpd · https://donneespersonnelles.fr/sous-traitant-rgpd
- MiCA et non-custodial : https://dfns.co/article/custodial-or-non-custodial-under-micar
- EURC : https://www.circle.com/eurc
- DSP2 et jetons de monnaie électronique : https://www.eba.europa.eu/publications-and-media/press-releases/eba-publishes-no-action-letter-interplay-between-payment-services-directive-psd23-and-markets-crypto
- Fiscalité des crypto-actifs en entreprise : https://www.swim.legal/blog/fiscalite-cryptomonnaies-entreprise
- Paiements d'agents IA : https://privacy.com/blog/payment-solutions-ai-agents-2026-compared · https://dupple.com/reviews/payman
- Paiement de factures : https://www.lafabriquedunet.fr/logiciels/alternatives/alternative-libeo · https://www.spendesk.com/fr/platform/invoice-management/
