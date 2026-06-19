# Release Checklist — Ghisdiag v1.4.0

**Date :** 2026-06-11

---

## Pré-build

- ✅ Version bump : **1.3.0 → 1.4.0** (orchestrator.py, report/generator.py, version_info.txt, README, mistral_report.py, finalize_release.ps1)
- ✅ CHANGELOG.md mis à jour
- ✅ RELEASE_NOTES_v1.4.0.md créé
- ✅ UI validée visuellement (4 onglets, captures + vérification pixel)

## Build & publication

1. `build.bat` → `dist\Ghisdiag.exe` (vérifier Propriétés → Détails : **1.4.0.0**)
2. `git push origin HEAD:main HEAD:master`
3. `gh release create v1.4.0 --draft --title "Ghisdiag v1.4.0 — Refonte graphique & audit IA approfondi" --notes-file RELEASE_NOTES_v1.4.0.md`
4. `.\finalize_release.ps1 -Version 1.4.0 -Commit -Push -Release`

## SHA-256 de l'exe

86b07adf0d80fb19228fc25fc5609bbfd7eaf2b367495ee13bf9d24113362188
