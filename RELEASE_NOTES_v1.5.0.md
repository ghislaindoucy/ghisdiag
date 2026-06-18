# PlanetDiag v1.5.0 — Notes de Release

**Date de sortie :** 2026-06-18  
**Version précédente :** 1.4.0

---

> Release **bench thermique** : objectiver le gain d'un nettoyage ou d'un
> changement de pâte thermique. Des courbes de température avant intervention,
> des courbes après, un verdict chiffré — un argument concret à montrer au client.

---

## 🌡️ Bench thermique avant / après maintenance

Nouvel onglet **« Bench thermique »**. Un protocole reproductible en trois phases —
**repos → charge CPU → refroidissement** — mesure le comportement thermique de la
machine, puis compare deux sessions pour chiffrer le gain d'une intervention.

### Des températures enfin fiables

- Embarque **LibreHardwareMonitorLib** (MPL-2.0) et le driver **PawnIO** (signé,
  hors blocklist Windows 11) pour lire température et fréquence CPU via les MSR.
- Remplace la chaîne WMI/OpenHardwareMonitor, souvent vide sur les machines de
  bureau. **Bénéfice immédiat** : le moniteur temps réel affiche désormais des
  températures partout — CPU, GPU, disques et **vitesses des ventilateurs**.

### Moteur de bench

- Durée et **intensité de charge** (50 / 100 %) configurables ; génération de
  charge par workers PowerShell (runspaces .NET, un par cœur logique).
- **Arrêt d'urgence automatique** si la température CPU dépasse 95 °C, plus un
  bouton Stop.
- Métriques : T repos, T max, T plateau en charge, **ΔT**, temps de retour au
  calme, **détection de throttling** (la fréquence s'effondre quand la température
  plafonne), régime des ventilateurs.
- Chaque session est enregistrée en JSON horodaté, étiquetée **Avant / Après / Libre**.

### Courbes en temps réel

- Graphe sur `tk.Canvas` : zones colorées par phase, séries CPU / GPU / disque,
  ligne d'urgence à 95 °C. Pas de matplotlib — l'exécutable reste léger.

### Comparaison avant / après

- Sélection de deux sessions → **courbes superposées** dans l'app et **rapport
  HTML autonome** (courbes SVG, hors-ligne, imprimable) à remettre au client.
- **Carte des gains** : ΔT, plateau, max, temps de refroidissement, throttling
  éliminé (oui/non), et un **verdict clair** (« −12 °C en charge — intervention
  efficace »).
- **Garde-fou honnêteté** : seuls des protocoles identiques sont comparés, et le
  **ΔT** (écart à la température de repos, insensible à la température ambiante)
  est mis en avant comme mesure la plus fiable.

---

## ✏️ Aussi dans cette version

- **Renommer un compte utilisateur local** (onglet Setup) via `Rename-LocalUser` —
  profil et données conservés (SID inchangé), avec garde-fous de validation.

---

## ✅ Vérification Pré-Release

- ✅ `thermal_bench.py`, `thermal_compare.py`, `main.py` compilent
- ✅ Moteur validé end-to-end (3 phases, arrêt utilisateur, métriques, throttling)
- ✅ UI vérifiée visuellement : onglet bench (courbes temps réel) + mode comparaison
- ✅ Rapport HTML de comparaison validé (courbes SVG, verdict, section honnêteté)
- ✅ Versions synchronisées (orchestrator, generator, version_info, manifest, README, mistral_report)

---

## 🚀 À Savoir Avant le Déploiement

1. **Le driver PawnIO** est installé en silence au premier lancement (l'app est
   déjà élevée — pas d'UAC supplémentaire). Sans lui, la température et la
   fréquence CPU restent indisponibles ; GPU et disques remontent quand même.
2. **Aucune nouvelle dépendance Python.** Les DLL LibreHardwareMonitor et
   l'installeur PawnIO sont embarqués dans l'exe.
3. La génération de charge sollicite fortement le CPU pendant le test —
   l'arrêt d'urgence à 95 °C protège la machine.

---

## 📝 Modifications

```
feat(thermal): Phase 0 — source temperatures LibreHardwareMonitor + driver PawnIO
feat(thermal): Phases 1-3 — moteur de bench, UI temps reel, comparaison avant/apres
feat(comptes): renommer un compte utilisateur local
release: bump version 1.5.0 (orchestrator, generator, version_info, manifest, README, mistral_report)
```

---

## ⬇️ Téléchargement

- **Exe** : `PlanetDiag.exe`
- **Sha256** : `904cd5d4eaa29f1783a82051a1fbc39ee917d761af43d01935da13ea6fff2ec2`
- **Taille** : 23.4 MB
