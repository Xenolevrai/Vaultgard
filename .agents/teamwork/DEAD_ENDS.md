# Dead Ends Log

| Iteration | Approach Tried | Why It Failed | Files Touched |
|-----------|---------------|---------------|---------------|
| 1 | Monkey-patching `VG.createInitialState` in `test.js` to add `action` to timeline items | Concealed production mismatch where `core.js` used `event` and `app.js` expected `evt.action`. Fails in real runtime without test harness patch. | `test.js`, `app.js` |
