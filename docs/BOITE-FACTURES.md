# La boîte de dépôt des factures

Nouvelle direction décidée par l'équipe le 10 octobre : on se concentre sur **recevoir une facture par mail et dire
si elle peut être payée**, puis **préparer le virement en euros** que l'entreprise valide dans sa banque. Avalanche
garde la preuve de ce qui a été préparé. VaultGuard ne touche jamais l'argent. Le reste du projet (coffre Avalanche,
API pour les assistants des clients) est conservé tel quel.

## En une phrase

Chaque entreprise reçoit une adresse mail de notre part. Elle y transfère ses factures. Notre assistant ne lit que
les mails des personnes qu'elle a autorisées, et VaultGuard répond pour chaque facture : **bonne à payer**,
**à vérifier par vous**, ou **refusée**.

## L'image à utiliser

Une boîte aux lettres avec un vigile devant.
- Le vigile regarde d'abord **qui dépose** l'enveloppe. Si ce n'est pas un employé connu, ou si quelqu'un se fait
  passer pour un employé, l'enveloppe part à la poubelle **sans être ouverte**.
- Si c'est un employé connu, un contrôleur ouvre l'enveloppe et compare la facture à ce que l'entreprise sait déjà :
  ce fournisseur est-il connu ? le compte bancaire est-il le bon ? le montant est-il normal ? l'a-t-on déjà reçue ?
- Le contrôleur ne garde pas la facture. Il note seulement son verdict et une empreinte qui permet de prouver plus
  tard de quelle facture il s'agissait.

## L'essayer en 3 minutes (sans vraie boîte mail)

1. `LANCER-DASHBOARD.bat`, puis http://localhost:8000/app , menu **« 2. Factures reçues »**.
   En haut : l'adresse de dépôt du client de démonstration. En bas : les deux personnes autorisées, les trois
   fournisseurs avec leur IBAN (de test), le seuil de 1 000 €.
2. `ENVOYER-FACTURES-DEMO.bat` : il dépose 9 mails un par un. La page se met à jour seule en quelques secondes.

| Mail | Ce qu'il contient | Résultat |
|---|---|---|
| 01 | facture normale du Garage Dupont, 480 € | bon à payer |
| 02 | location de 2 400 €, au-dessus du seuil | à vérifier : ton accord est demandé |
| 03 | le garage annonce un nouveau RIB | refusée : le compte n'est pas celui enregistré |
| 04 | texte blanc invisible qui donne des ordres à l'assistant | refusée : instructions cachées |
| 05 | société de nettoyage jamais vue | à vérifier : fournisseur inconnu |
| 06 | mail d'une adresse non autorisée (faux « Garage Dupont ») | écarté sans être lu |
| 07 | quelqu'un imite l'adresse du dirigeant | écarté sans être lu |
| 08 | la facture 01 renvoyée une seconde fois | refusée : déjà reçue |
| 09 | facture électronique (fichier XML) de l'épicerie, 126 € | bon à payer |

3. Bloc **« À faire »** : clique « Bonne à payer » ou « Refuser » sur les deux factures en attente.
   Bloc **« Payer en euros, par virement »** : clique « Préparer le fichier de virements », puis
   « Télécharger le fichier » (c'est ce que l'entreprise importe dans sa banque).
   Bouton **« Détail »** d'une ligne : les raisons, la fin du compte bancaire lu, l'empreinte de la facture et
   l'inscription au journal infalsifiable.
4. Les mails 06 et 07 n'apparaissent pas dans la liste : ils n'ont jamais été ouverts. Seul un compteur en haut
   indique « 2 mails écartés sans être lus ».

Pour rejouer : relance `ENVOYER-FACTURES-DEMO.bat` (toutes les factures seront alors « déjà reçues », ce qui est le
comportement voulu) ou `RECREER-DEMO.bat` pour repartir de zéro (site arrêté ; les identifiants changent).

Si ta base de démonstration date d'avant cette fonction, une seule fois, site arrêté :
`wsl -d kali-linux --cd <dossier vaultguard>/agent -- python3 ../scripts/seed_inbox_demo.py`
(n'efface rien, ne change aucun identifiant).

## Ce qui est contrôlé, dans l'ordre

**Avant d'ouvrir le mail** (seuls les en-têtes sont téléchargés) :
1. L'adresse de destination désigne-t-elle une entreprise cliente ? Chaque adresse contient une partie tirée au
   hasard : elle ne se devine pas.
2. L'expéditeur est-il dans la liste de confiance **de cette entreprise** ? Être autorisé chez un client ne donne
   aucun droit chez un autre.
3. L'expéditeur est-il **prouvé** ? Une adresse d'expéditeur s'imite en une ligne. On ne la croit que si notre serveur
   de réception a vérifié le mail (SPF, DKIM, DMARC : les trois contrôles standard qui prouvent qu'un mail vient bien
   du domaine affiché). Un faux en-tête de contrôle ajouté par l'expéditeur est ignoré.

**Une fois le mail ouvert**, tout ce qu'il contient est traité comme une donnée non fiable, jamais comme un ordre :
4. Instructions cachées pour un assistant (texte invisible, encodé, lettres imitées) → refusée.
5. Compte bancaire : l'IBAN de la facture doit être celui que l'entreprise a enregistré pour ce fournisseur. Un autre
   IBAN → refusée (c'est la fraude au changement de RIB, la plus courante). Deux IBAN dans le même document, IBAN mal
   formé, pas d'IBAN, fournisseur inconnu → à vérifier.
6. Montant : au-dessus du seuil choisi par l'entreprise, ou plus de trois fois le montant habituel de ce
   fournisseur, ou total différent de la somme des lignes → à vérifier.
7. Déjà reçue (même fichier, ou même numéro chez le même fournisseur) → refusée.
8. Fournisseur ajouté depuis moins de 24 h → à vérifier (délai de sécurité : un pirate qui ajouterait son propre
   compte ne peut pas l'utiliser tout de suite).

Les chiffres mesurés sur 45 mails d'essai sont dans `docs/METRIQUES.md`.

## Ce que VaultGuard garde

| Gardé | Jamais gardé |
|---|---|
| le verdict et ses raisons (nos phrases) | le mail, la facture, les pièces jointes |
| le montant, le numéro de facture | le texte de la facture, les lignes, les prix |
| les 4 derniers caractères de l'IBAN lu + son empreinte | l'IBAN complet d'un compte inconnu |
| l'empreinte SHA-256 du fichier | l'objet du mail, le nom d'un fournisseur inconnu |

Le mail est effacé de la boîte dès qu'il est traité. Un test automatique vérifie qu'un texte confidentiel placé dans
une facture ne se retrouve nulle part dans la base.

Changement par rapport à hier, à dire clairement à un client : avec une adresse fournie par nous, **le mail passe par
chez nous**. La promesse n'est plus « nous ne voyons pas vos factures » mais « nous les lisons le temps du contrôle
et nous ne gardons rien ». Le mode d'hier (l'assistant tourne chez le client) existe toujours pour ceux qui le veulent.

## Brancher une vraie boîte mail (Gmail de test)

1. Créer une adresse Gmail **dédiée au projet** (pas une boîte personnelle), activer la validation en 2 étapes,
   puis créer un « mot de passe d'application » (Compte Google > Sécurité > Mots de passe des applications).
2. Dans Gmail : Paramètres > Transfert et POP/IMAP > activer IMAP.
3. Ajouter dans `agent/.env` (modèle dans `.env.example`) :
   ```
   INBOUND_ADDRESS=ton.adresse+{alias}@gmail.com
   INBOUND_IMAP_HOST=imap.gmail.com
   INBOUND_IMAP_USER=ton.adresse@gmail.com
   INBOUND_IMAP_PASSWORD=le mot de passe d'application
   INBOUND_SMTP_HOST=smtp.gmail.com
   ```
4. Relancer le site. L'adresse affichée dans « Factures reçues » devient `ton.adresse+transports-martin@gmail.com`
   (Gmail remet dans la même boîte tous les mails envoyés à `adresse+quelquechose`).
5. Dans « Personnes autorisées », ajouter **ta propre adresse**, puis transférer une facture à l'adresse de dépôt.
   Le verdict apparaît dans la page et une réponse arrive par mail.

Cette partie n'a pas pu être essayée sans les identifiants d'une boîte : la lecture des mails, le filtre et les
verdicts sont testés sur des mails enregistrés, la connexion à Gmail reste à faire une fois par Ozgun.
En production, on utiliserait notre propre nom de domaine (`nom-du-client@factures.vaultguard.fr`).

## Le paiement : en euros, par virement (construit)

Décision de l'équipe : **le fournisseur doit recevoir des euros sur son compte bancaire**, comme d'habitude.
Personne ne doit avoir à toucher à de la crypto. C'est pour cela que le fournisseur est identifié par son IBAN.

Ce qui marche aujourd'hui, sans partenaire ni agrément :

1. Les factures « bonnes à payer » s'accumulent. Le bloc **« Payer en euros, par virement »** en donne le nombre et
   le total.
2. Un clic sur **« Préparer le fichier de virements »** produit un fichier SEPA (norme ISO 20022, message pain.001 :
   le format que les banques acceptent pour les virements en lot, celui qu'utilisent les logiciels de comptabilité).
3. L'entreprise l'importe dans le site de sa banque et **valide une seule fois** pour tout le lot. Chaque
   fournisseur reçoit un virement ordinaire en euros.
4. L'empreinte du fichier est inscrite au journal infalsifiable, puis **scellée sur Avalanche** : avec `CHAIN=web3`
   c'est une vraie transaction sur Fuji (lien vers l'explorateur affiché) ; hors ligne, c'est le coffre de
   démonstration. Si le réseau ne répond pas, le fichier est quand même prêt et un bouton « Sceller sur Avalanche »
   permet de réessayer.

Garanties :
- L'IBAN du virement est celui **du carnet de l'entreprise**, jamais celui écrit sur la facture.
- Une facture ne peut entrer que dans **un seul fichier** : pas de double virement, même en cliquant deux fois.
- Une facture acceptée à la main pour un fournisseur absent du carnet n'est pas payée automatiquement.
- Le fichier n'est pas stocké : il se régénère à l'identique. S'il ne correspond plus à l'empreinte scellée (ligne
  modifiée en base), il n'est plus délivré.
- VaultGuard ne détient jamais l'argent et n'a aucun accès au compte bancaire.

**« Est-ce que ça enlève l'automatique ? »** Non. La réception, la lecture, le contrôle, la préparation des virements
et la preuve sont automatiques. Il reste un geste humain : valider le lot dans sa banque. C'est voulu (l'argent ne
part jamais sans un humain de l'entreprise) et c'est ce qui nous évite d'avoir besoin d'un agrément.
Étape suivante pour retirer ce dernier clic : envoyer le même fichier à la banque par le canal EBICS (liaison
automatique entre une entreprise et sa banque, proposée par les banques françaises), sans changer le reste.

À dire honnêtement : le fichier a été vérifié par nos tests (structure, montants, IBAN) mais **jamais importé dans
une vraie banque**. Certaines banques demandent une variante plus récente du format ; c'est un réglage.

### Pourquoi pas l'EURC directement ?
Convertir des EURC (des euros en jetons, disponibles sur Avalanche) en euros sur le compte de quelqu'un d'autre,
c'est fournir un service de paiement : il faut un prestataire agréé, il n'existe pas de version gratuite. Ce chemin
reste possible plus tard avec un partenaire ; il n'apporte rien au client tant que le virement fait le travail.

**Avalanche sert de registre de preuves** : l'empreinte de chaque fichier de virements y est scellée, et le bouton
« Sceller sur Avalanche » de « Historique et preuves » y inscrit l'empreinte de tout le journal.

## La facture électronique obligatoire

Depuis le 1er septembre 2026, toutes les entreprises françaises doivent pouvoir **recevoir** leurs factures au
format électronique (Factur-X, UBL ou CII) par l'intermédiaire d'une plateforme agréée par l'État ; l'obligation
d'en **émettre** s'applique d'abord aux grandes entreprises, puis aux PME en septembre 2027.
(Calendrier à confirmer sur impots.gouv.fr avant de le citer au jury.)

Ce que VaultGuard fait déjà :
- Il lit les trois formats structurés. Le détail d'une facture indique « Facture électronique » ou « non électronique ».
- Il contrôle les **mentions légales du vendeur** : un SIREN ou un numéro de TVA doit figurer sur une facture
  française ; le SIREN doit avoir une clé de contrôle valide ; le numéro de TVA doit correspondre au SIREN. Sinon,
  une personne est sollicitée.
- En option (`REGISTRY_CHECK=1` dans `agent/.env`), il interroge **l'annuaire public des entreprises de l'État**
  (API gratuite « Recherche d'entreprises ») : le SIREN existe-t-il, l'entreprise est-elle en activité, porte-t-elle
  le nom du fournisseur attendu ? Seul le SIREN est envoyé, jamais la facture. Si l'annuaire ne répond pas, la
  facture n'est ni bloquée ni validée par ce contrôle. Désactivé par défaut car les entreprises de la démonstration
  sont fictives.

Ce que VaultGuard n'est pas : une plateforme agréée. Les factures légales arriveront par la plateforme du client.
L'étape suivante naturelle est de **brancher VaultGuard sur cette plateforme** (elles proposent des accès par
programme) au lieu du mail : mêmes contrôles, même verdict, source officielle.

À dire honnêtement au jury :
- La blockchain n'empêche pas une illégalité. Elle rend impossible de modifier après coup ce qui a été décidé, par
  qui et quand. C'est une preuve, utile en cas de litige ou de contrôle.
- Les deux chemins de paiement demandent un partenaire régulé (banque, établissement de paiement, prestataire de
  services sur crypto-actifs). Nous ne tenons jamais l'argent nous-mêmes. Ce point est à faire valider par un juriste.

## Limites connues

- Une facture scannée (image sans texte) part toujours vers une personne.
- Si la messagerie d'un employé autorisé est réellement piratée, le pirate peut déposer des factures. Il reste
  limité par le contrôle de l'IBAN, le seuil et le délai de sécurité, mais ce n'est pas empêché.
- Les prix ligne par ligne ne sont pas comparés à des prix habituels dans ce parcours (ils le sont dans l'API pour
  les assistants des clients).
- Une facture par mail : s'il y en a plusieurs en pièces jointes, une personne est sollicitée.
- 60 factures par heure et par entreprise au maximum ; au-delà, les mails sont écartés.

## Où c'est dans le code

| Fichier | Rôle |
|---|---|
| `agent/mail_agent.py` | l'assistant : relève la boîte, filtre sur les en-têtes, lit, répond, efface |
| `agent/inbox.py` | VaultGuard : adresse par entreprise, listes, contrôle de la facture, verdict, décision humaine |
| `sdk/invoice_reader.py` | lecture des formats (texte, HTML, PDF, Factur-X, UBL/CII, Word) |
| `agent/transfers.py` | fichier de virements SEPA, compte de l'entreprise, preuve |
| `agent/registry.py` | SIREN, TVA, annuaire public des entreprises |
| `agent/test_inbox.py` | 28 tests, dont le jeu d'essai de 45 mails |
| `examples/boite_demo.py` | fabrique les mails de démonstration et le jeu d'essai |
| `scripts/detection-metrics.py` | produit `docs/METRIQUES.md` |
