# Expliquer VaultGuard simplement

## En une phrase
Quand une entreprise laisse une IA payer ses factures, VaultGuard vérifie chaque paiement avant qu'il parte, et
empêche l'IA de dépenser plus que ce que l'entreprise a décidé.

## L'image à utiliser
Un stagiaire très rapide à qui on confie le chéquier. Il lit tout ce qu'il reçoit et fait ce qui est écrit. Si une
fausse facture dit « payez plutôt sur ce nouveau compte », il le fait.
VaultGuard, c'est deux choses autour de ce stagiaire :
1. **Un contrôleur** qui relit chaque chèque avant qu'il parte : est-ce un fournisseur connu ? est-ce bien ce que
   le patron a demandé ? la facture cache-t-elle un ordre ? le prix est-il normal ? a-t-elle déjà été payée ?
2. **Un coffre à règles fixes** : même si le stagiaire et le contrôleur se trompent tous les deux, le coffre ne
   laisse pas sortir plus que le plafond, et seulement vers les fournisseurs enregistrés.

Trois issues possibles, et pas une de plus : **payé**, **à valider par un humain**, **bloqué**.

## Les mots à remplacer
| Ne dis pas | Dis |
|---|---|
| agent IA | l'assistant qui lit les factures |
| injection de prompt | un ordre caché dans une facture |
| pare-feu | le contrôleur |
| smart contract, on-chain | le coffre à règles fixes, sur Avalanche |
| empreinte SHA-256 | l'empreinte de la facture (comme une empreinte digitale : elle l'identifie sans la montrer) |
| human-in-the-loop | un humain donne son accord |
| disjoncteur | trop de refus, tout se gèle |

## Le pitch en 5 minutes : un seul scénario
1. **Le problème (45 s)** : les entreprises commencent à laisser une IA payer. Une facture piégée suffit à la
   détourner. Montrer la facture 03 : le texte caché ordonne de payer un inconnu.
2. **Sans protection (30 s)** : `/demo`, mode sans protection : l'argent part.
3. **Avec VaultGuard (1 min 30)** : lancer l'assistant sur les factures. La 01 est payée, la 03 est bloquée avec
   la raison en français, la 02 et la 06 attendent un humain. Sur l'accueil : « À faire », un clic sur Accepter.
4. **Si tout est piraté (45 s)** : le coffre sur Avalanche refuse quand même au-delà du plafond. Montrer le contrat
   sur Snowtrace et un refus enregistré.
5. **La preuve (45 s)** : « Cette facture a-t-elle déjà été payée ? » puis « Voir la preuve ». Un auditeur vérifie
   sans nous croire sur parole. Nous ne gardons pas les factures, seulement leur empreinte.
6. **Chiffres et limites (45 s)** : taux de détection et faux positifs mesurés (à produire), puis les limites dites
   franchement : réseau de test, règlement en euro numérique à construire.

## Le lien avec le sujet (Track 1, axe 3)
Le sujet décrit ce scénario : un agent manipulé par un document piégé fait exécuter une transaction, faute de
vérification de la chaîne d'autorité. Ce que le sujet demande, et ce que VaultGuard montre :

| Demandé | Dans VaultGuard |
|---|---|
| Journal de chaque action avec qui l'a demandée | historique chaîné : la consigne du patron d'un côté, le document reçu de l'autre |
| Détection des transactions hors périmètre | fournisseur inconnu, adresse imitée, montant ou prix anormal, facture déjà payée |
| Autorisations courtes et révocables | clé de l'assistant révocable en un clic, clé du coffre qui expire |
| Arrêt automatique au-delà d'un seuil de risque | trop de refus : gel du coffre, clé mise à l'écart ; adresse piège |
| Validation humaine des actions sensibles | « À faire » : Accepter ou Refuser |
| Contrat surveillé sur Avalanche Fuji (axe 4) | coffre déployé sur Fuji, refus enregistrés, pause |

## Les trois questions à préparer
- **« Si votre système se trompe, qui est responsable ? »** La perte maximale est fixée par le contrat de
  l'entreprise, et tout montant sensible passe par un humain. Nous ne détenons jamais les fonds.
- **« Le fournisseur veut des euros sur son compte. »** Aujourd'hui la cible est l'entreprise qui règle déjà en
  euro numérique ; ensuite un partenaire de paiement agréé reverse un virement. Ce n'est pas construit.
- **« Qu'avez-vous fait pendant le hackathon ? »** Dire honnêtement ce qui existait avant et ce qui a été ajouté
  (déploiement Fuji, parcours factures et mail, zéro conservation, contrôle des prix, preuve de paiement,
  tableau de bord en langage simple).
