---
description: Ajouter une nouvelle défense (règle de sécurité) de bout en bout
---

1. Décris l'attaque visée en 2 phrases et la référence (OWASP LLM / Agentic ASI / fraude financière).
2. Si la règle est « dure » (montant, destinataire, délai) : ajoute-la dans `contracts/src/AgentVault.sol` + un test dans `contracts/test/AgentVault.t.sol`, puis réplique-la dans `MockChain.preview()` (`agent/chain.py`).
   Si la règle a une raison de refus : ajoute-la à l'enum `BlockReason` ET à `REASONS` (même ordre) dans `chain.py`.
3. Si la règle est « contextuelle » (texte, provenance, comportement) : ajoute-la dans `TxFirewall.check()` (`agent/firewall.py`) + une entrée dans `CATALOG` (titre grand public + référence) + un test dans `agent/test_vaultguard.py`.
4. Ajoute un scénario d'attaque dans `agent/scenarios.py` qui la déclenche (avec `naive_actions`).
5. Lance `bash scripts/test-all.sh --full` (dont le test de parité), puis vérifie le scénario dans le dashboard (onglet Comparer).
6. Mets à jour AGENTS.md §6 et la liste des défenses dans `docs/PITCH.md`.
