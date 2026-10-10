# Mettre VaultGuard en place chez une entreprise

Ce qui suit est la marche à suivre telle que le projet la permet aujourd'hui. Elle a été jouée sur la démo locale,
**jamais chez un vrai client**. Les étapes marquées « pas encore » ne sont pas construites.

## Qui fait quoi, en une ligne
- **L'entreprise** garde sa boîte mail, ses factures, son argent et la clé de son coffre. Elle fixe ses règles.
- **Nous** installons deux programmes et montrons comment s'en servir : VaultGuard (le site qui vérifie) et
  l'assistant (le petit programme qui lit les factures).

## Avant la visite
| Qui | Quoi |
|---|---|
| Nous | Décider où tourne VaultGuard : sur un serveur de l'entreprise (ses données ne sortent pas de chez elle) ou sur le nôtre. Installation par Docker : `docs/MISE_EN_PRODUCTION.md`. |
| L'entreprise | Désigner deux personnes : le **responsable** (dirigeant ou directeur financier, il fixe les règles) et le **valideur** (comptable, il accepte ou refuse les paiements douteux). |
| L'entreprise | Préparer la liste de ses fournisseurs réguliers et ses plafonds habituels. |
| Son informaticien | Prévoir une machine allumée en permanence pour l'assistant (un petit serveur suffit). |

## Sur place, dans l'ordre

### 1. Créer l'espace de l'entreprise (15 min)
- Nous : ouvrir le site, « Créer un espace » avec l'adresse du responsable.
- Le responsable : choisit son mot de passe et active la double authentification (menu « 9. Paramètres ») avec
  une application comme Google Authenticator. Nous ne connaissons pas son mot de passe.
- Le responsable invite le valideur (menu « 7. Équipe »).

### 2. Fixer les règles (20 min, c'est l'entreprise qui décide)
Menu « 5. Règles de paiement » :
- somme maximale par paiement et par jour ;
- somme à partir de laquelle un humain doit donner son accord ;
- nombre de refus qui gèle tout.

Menu « 4. Fournisseurs » : le nom et l'adresse de paiement de chaque fournisseur. Un nouveau fournisseur n'est
utilisable qu'après 24 h : c'est voulu, un fraudeur ne peut pas s'ajouter et être payé dans la foulée.

### 3. Le coffre (30 min)
- Le responsable crée son portefeuille (Core Wallet). Lui seul en a la clé.
- Nous déployons un coffre à son nom sur Avalanche (`scripts/deploy-fuji.sh` sur le réseau de test) avec ses règles.
- Il y dépose le budget qu'il confie à l'assistant, pas sa trésorerie.
- Aujourd'hui : réseau de test, et l'espace client utilise un coffre de démonstration. Le règlement en euro
  numérique (EURC) : pas encore.

### 4. L'adresse mail des factures (20 min, avec leur informaticien)
- L'informaticien crée une adresse réservée, par exemple `factures-a-payer@entreprise.fr`, sur leur messagerie.
- Il autorise la lecture par un programme (accès IMAP) et crée un mot de passe d'application pour cette boîte.
- L'entreprise décide **qui a le droit d'y envoyer des factures** (par exemple le comptable et l'assistante).

Personne ne nous donne accès à la messagerie générale : l'assistant ne lit que cette boîte.

### 5. Installer l'assistant (30 min)
Sur la machine prévue, chez eux :
1. Installer Python 3 et copier les dossiers `sdk/` et `examples/`.
2. Dans le site, menu « 3. Assistants et clés d'accès » : le responsable crée une clé. Elle s'affiche une seule fois.
3. Donner à l'assistant l'adresse du site et cette clé (`VAULTGUARD_URL`, `VAULTGUARD_API_KEY`).
4. Remplir `examples/.env.mail` : la boîte, son mot de passe d'application, `MODE=dediee`,
   `EXPEDITEURS_AUTORISES=` les adresses décidées à l'étape 4, `SUPPRIMER_APRES=1`.
5. Remplir `examples/prix-reference.json` avec eux : leurs prix habituels pour les achats courants.
6. Lancer : `python3 examples/agent_mail.py --watch 60 --consigne "Paie les factures de <leurs fournisseurs>"`.

À faire par leur informaticien : que ce programme redémarre tout seul avec la machine (tâche planifiée ou
service). Pas encore : un installateur qui fait ces étapes d'un clic.

### 6. Essayer ensemble (20 min)
1. `--dry-run` d'abord : l'assistant montre ce qu'il ferait, sans rien envoyer.
2. Le comptable transfère une vraie petite facture d'un fournisseur enregistré : elle est payée.
3. Il transfère une facture au-dessus du seuil : elle apparaît dans « À faire », le valideur accepte.
4. Nous envoyons une facture piégée de démonstration : elle est bloquée, avec la raison écrite en clair.
5. « Cette facture a-t-elle déjà été payée ? » : on retrouve la facture du point 2 et sa preuve.
6. On renvoie la même facture : elle n'est pas payée une deuxième fois.

## Ensuite, au quotidien
| Qui | Quoi |
|---|---|
| Le comptable | Transfère les factures à payer vers l'adresse dédiée. C'est tout. |
| Le valideur | Ouvre l'accueil du site : « À faire » liste ce qui attend son accord, avec la raison. Accepter ou Refuser. |
| Le responsable | Ajoute les nouveaux fournisseurs, ajuste les plafonds, rouvre le coffre s'il s'est gelé. |
| Nous | Mises à jour et assistance. Nous ne voyons ni les factures ni les fonds. |

Pas encore : un mail ou un SMS qui prévient le valideur qu'un paiement l'attend. Aujourd'hui il doit ouvrir le site.

## En cas de problème
- Un doute sur l'assistant : menu « 3. Assistants et clés d'accès », révoquer la clé. Il ne peut plus rien demander.
- Trop de refus d'un coup : le coffre se gèle tout seul et la clé est mise à l'écart. Le responsable regarde
  l'historique, puis rouvre le coffre (double authentification demandée) et crée une nouvelle clé.
- Un fournisseur dit ne pas avoir été payé : « Cette facture a-t-elle déjà été payée ? », puis « Voir la preuve ».
