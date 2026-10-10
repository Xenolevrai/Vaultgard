# État du projet — ce qui est fait, ce qui ne l'est pas

Mis à jour le 10 octobre 2026 au soir, après la fusion du front-end (branche `feat/dashboard`) et du back-end
(branche `backend/detection-fraude`). À relire avant de reprendre le travail ou de préparer le pitch.

## En une phrase
VaultGuard contrôle chaque facture **avant** qu'elle soit payée : il repère les fraudes (compte bancaire changé,
page PDF et données XML qui se contredisent, faux fournisseur, doublon…), demande l'accord d'une personne quand il
doute, et prépare le fichier de virements que l'entreprise envoie elle-même à sa banque.

## Ce qui marche, de bout en bout (vérifié dans le navigateur le 10 oct.)
| Écran de `/app` | Ce qu'on peut y faire | Code côté serveur |
|---|---|---|
| Vue d'ensemble | Chiffres réels, schéma du parcours des factures (cliquable), montants par mois et par fournisseur | `agent/inbox.py` |
| Factures reçues | Liste, recherche, filtres, vues enregistrées, export CSV ; détail avec chaque contrôle expliqué ; accepter ou refuser une facture « à vérifier » | `agent/inbox.py`, `agent/fraud.py` |
| Déposer une facture | Envoyer un fichier à la main (PDF, XML, mail, image…) : même contrôle qu'un mail reçu | `inbox.check_upload` |
| Paiements | Factures bonnes à payer, fichier de virements SEPA à télécharger, empreinte du fichier inscrite comme preuve, contrôle d'un fichier de virements venu d'un autre logiciel | `agent/transfers.py` |
| Factures émises | Créer une facture électronique pour un client (par son SIREN), la lui remettre s'il est sur VaultGuard, suivre où elle en est | `agent/einvoice.py` |
| Alertes | Ce qui demande une action, le plus urgent d'abord | calculé dans `dashboard/workspace/app.js` |
| Fournisseurs | Liste de référence (nom + compte bancaire), ajout, retrait | `agent/inbox.py` |
| Réglages | Adresse de dépôt, expéditeurs autorisés, seuil d'accord humain, compte bancaire de l'entreprise | `agent/inbox.py`, `agent/transfers.py` |
| Historique et preuves | Journal de toutes les actions, vérification qu'il n'a pas été modifié, export CSV | `agent/orgs.py`, `agent/auth.py` |

Les factures entrent par quatre portes, toutes contrôlées de la même façon : mail transféré à l'adresse de dépôt,
fichier déposé sur le site, facture émise sur la plateforme par un fournisseur, appel d'un assistant automatique
par l'API `/v1`.

Tests : voir `README.md` (suite complète et audit de sécurité à relancer après chaque changement).

## Ce qui n'est pas fait
| Sujet | État | Pourquoi / quoi faire |
|---|---|---|
| Connecteur Pennylane | **Non construit.** | Pas de compte Pennylane dans l'équipe, et impossible d'en créer sans entreprise. Voir « Sans Pennylane » ci-dessous. |
| Contrôles anti-fraude dans l'API `/v1` | Non branchés. | L'API des assistants automatiques garde ses propres contrôles (pare-feu + coffre). Les contrôles de `fraud.py` ne passent que par la boîte de dépôt, le dépôt manuel, la plateforme et le fichier de virements. |
| Équipe, clés d'accès des assistants, coffre, règles de paiement | Non repris dans la nouvelle interface. | Toujours utilisables dans l'ancienne interface, `/app/classique` (lien en bas du menu). Design différent. |
| Site public (`/`, `/demo`, `/docs`, `/securite`) | Pas mis à jour. | Il présente encore l'ancien sujet (pare-feu de paiements pour agents IA) et l'ancienne charte graphique. |
| Version anglaise | Abandonnée. | La maquette était en anglais ; l'interface est en français simple, pour des utilisateurs non informaticiens. |
| Affichage sur téléphone | Non vérifié. | Les règles d'adaptation existent dans `styles.css`, mais seul l'affichage sur écran d'ordinateur a été contrôlé. |
| Plateforme agréée | Hors de portée du hackathon. | VaultGuard n'est pas immatriculé auprès de l'administration ; rien n'est transmis à l'État. |
| Livrables du hackathon | À faire avant dimanche 12h00. | Vidéo 2-3 min, deck 8 slides (dont conformité), fiche de défense, playbook de réponse. Voir `HACKATHON.md`. |

## Ce qui a été retiré de la maquette du front-end, et pourquoi
La maquette (`archive/maquette-front/`) fonctionnait seule, avec des données inventées dans le navigateur. En la
branchant sur le vrai serveur, tout ce qui n'avait aucun équivalent côté serveur a été retiré plutôt que laissé
« pour faire joli » : un jury qui clique sur un bouton factice le voit tout de suite.

- Connexions affichées « connectées » à SAP, Oracle NetSuite, QuickBooks, BNP Paribas, registre européen de TVA.
- Rapprochement avec bon de commande et bon de livraison, départements, attribution à un auditeur.
- Conversion de devises, escompte, paiement partiel, avoir, rapprochement bancaire.
- Rôles de démonstration changeables à la volée, commentaires, pièces jointes, notifications Slack / Teams.

Ce qui a été gardé tel quel : toute la charte graphique (`styles.css`), la structure de la page, le schéma de
parcours des factures, les graphiques, le thème clair / sombre, les vues enregistrées.
Trois défauts de la maquette ont été corrigés au passage : les rubans du schéma de parcours ne s'affichaient pas,
la liste des contrôles d'une facture s'affichait sans libellés ni résultats (l'écran et le moteur n'utilisaient
pas les mêmes noms de champs), et le bouton « rappel téléphonique » appelait une fonction qui n'existait pas.

## Sans Pennylane : où se place-t-on ?
Nous ne pouvons pas tester l'API de Pennylane (il faut un compte d'entreprise payant). Ce n'est pas bloquant :
**le produit ne dépend d'aucun logiciel de comptabilité.**

1. **Ce qu'on montre** : VaultGuard se place *à côté* du logiciel de l'entreprise, quel qu'il soit. Deux points
   de contrôle fonctionnent aujourd'hui sans aucun accès à ce logiciel :
   - à l'entrée : la facture est transférée par mail ou déposée, et contrôlée ;
   - à la sortie : le fichier de virements exporté par le logiciel (Pennylane, Sage, Cegid, peu importe) est
     déposé dans « Dernier contrôle avant la banque », et chaque ligne est comparée à la liste de fournisseurs.
   Le second point est l'argument le plus fort : quelle que soit la façon dont la fraude est entrée, elle finit
   dans ce fichier, et tous les logiciels savent l'exporter au même format (SEPA).
2. **Ce qu'on dit sur Pennylane** : leur documentation publique montre que le branchement est possible (lecture
   des factures fournisseurs avec le PDF et les données d'origine, écriture d'un statut « contestée »). Nous
   l'avons lue, pas testée. C'est une étape suivante, pas une fonction livrée.
3. **Ce qu'on ne fait pas** : écrire un faux Pennylane pour faire croire à un branchement. Un simulateur ne
   prouverait que notre lecture de leur documentation.

## Questions encore ouvertes (à poser à un organisateur)
- La règle « le cœur du projet est développé pendant l'événement » : VaultGuard existait avant le 10 octobre.
  La détection de fraude à la facture électronique, la plateforme de facturation et la nouvelle interface ont été
  faites pendant.
- Cette direction répond-elle à un problème « agentique » et à un axe de la Track 1 ? Voir `HACKATHON.md`.
