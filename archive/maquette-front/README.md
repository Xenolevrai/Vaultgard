# Maquette d'origine du front-end (archive)

Travail de Kanan Bashaï sur la branche `feat/dashboard`, gardé tel quel. C'est une application autonome : elle
tourne seule, avec des données inventées dans le navigateur (`core.js`), sans le serveur VaultGuard.

```bash
node server.js        # http://localhost:3000
node --test test.js   # 16 tests du moteur de démonstration
```

Elle a servi de base à l'interface réelle, `dashboard/workspace/`, qui reprend sa charte graphique, sa structure
et son schéma de parcours des factures, mais affiche les données du serveur (`agent/`). Ce qui a été gardé,
retiré ou corrigé est décrit dans `docs/ETAT.md`.

Ne pas modifier ce dossier pour faire évoluer le produit : travailler dans `dashboard/workspace/`.

`.agents/teamwork/`, `challenger_ui_stress.js`, `stress_sankey.js`, `context.md` : notes et scripts de travail de
l'outil qui a aidé à produire la maquette.
