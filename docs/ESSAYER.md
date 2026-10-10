# Tout essayer, pas à pas

Base de démo recréée le 10 oct au soir : entreprise « Transports Martin », trois fournisseurs (Garage Dupont, Loueur
Camions Express, Épicerie Pro), un historique de 5 paiements daté de la veille.

## 1. Lancer le site et se connecter
1. Double-clic sur `LANCER-DASHBOARD.bat`. Laisse la fenêtre ouverte : la fermer arrête le site.
2. Ouvre http://localhost:8000/login et connecte-toi avec le compte **client** écrit dans
   `agent/data/COMPTES-DEMO.txt` (ouvre ce fichier toi-même, ne le montre à personne).
3. Tu arrives sur `/app` : menu « 2. Paiements », « 3. Agents & Clés API », « 4. Fournisseurs », « 6. Journal d'audit ».

## 2. Faire lire les factures par l'agent
Double-clic sur `TRAITER-FACTURES.bat`, puis Entrée entre chaque facture. Résultat attendu :

| Facture | Format | Verdict | Pourquoi |
|---|---|---|---|
| 01 garage, entretien | texte | payé | fournisseur connu, conforme à la consigne |
| 02 loueur, location | texte | en attente d'un humain | 0.08 AVAX, au-dessus du seuil de 0.05 |
| 03 garage, piégée | texte | bloqué | ordre caché : payer un inconnu |
| 04 changement de RIB | texte | bloqué | adresse presque identique à celle du garage |
| 05 fournisseur inconnu | texte | bloqué | absent du carnet |
| 06 épicerie | texte, en euros | en attente d'un humain | boîte d'œufs à 18 € au lieu de 3 € |
| 07 garage | XML (facture électronique UBL) | payé | 50 € |
| 08 garage | PDF Factur-X | payé | 50 € |

## 3. Voir ce que VaultGuard a gardé
Dans `/app`, onglet Paiements, clique « Détails » sur la facture de l'épicerie :
- la raison est écrite sans recopier la facture (« ligne 1 de la facture : 6.0 fois le prix habituel ») ;
- la consigne et le document n'apparaissent que sous forme d'empreintes SHA-256 ;
- « Vérifier une facture » : choisis `examples/factures/06-epicerie-prix-anormal.txt` → message vert. Choisis un
  autre fichier → message rouge. Le fichier ne quitte pas ton navigateur.
- Approuve ou rejette le paiement en attente.

Menu « 6. Journal d'audit » : « Vérifier l'intégrité » contrôle la chaîne d'empreintes.

## 4. Rejouer deux mails
Double-clic sur `REJOUER-MAILS.bat` : un mail normal (payé, ou bloqué pour double paiement si tu l'as déjà joué),
puis un mail piégé (bloqué).

## 5. Tester la détection de prix toi-même
Ouvre `examples/factures/06-epicerie-prix-anormal.txt`, change le numéro de facture et remets le prix des œufs à
`3.00` avec un total cohérent (`5 x 3.00` et `10 x 1.00` = `25.00 EUR`) : la facture passe. Les prix habituels sont
dans `examples/prix-reference.json`.
Pour une seule facture : dans Kali, `python3 examples/agent_factures.py --only 06`.

## 6. La boîte mail dédiée (optionnel, demande une vraie boîte de test)
Voir `docs/PARCOURS-A-Z.md`, section « Variante : une adresse dédiée ». Sans boîte : l'étape 4 suffit.

## 7. Le reste de la démo
`/demo` (scénarios d'attaque, onglet Coffre pour le vrai contrat Fuji), `/admin` avec le compte super-admin et sa
2FA, et le contrat sur https://testnet.snowtrace.io/address/0x30c9A13FACf3Be404C1Ea0333D31165Fe1f0d793 .

## Attention au disjoncteur
**5 refus en une heure mettent la clé de l'agent en quarantaine** (c'est voulu). L'étape 2 fait 3 refus, l'étape 4
en fait 1. Relancer l'étape 2 une deuxième fois déclenche donc le gel : l'agent reçoit alors « HTTP 401 ».
Pour repartir de zéro : ferme la fenêtre du site, double-clic sur `RECREER-DEMO.bat`, relance
`LANCER-DASHBOARD.bat` et reconnecte-toi avec les nouveaux identifiants.
