# Dépannage — Pas de température CPU / bench thermique impossible

## Symptôme
- Aucune température CPU dans le suivi temps réel
- Le bench thermique ne démarre pas ou ne produit que des valeurs `None`
- Cas observés : Celeron, Ryzen Zen 5 (9800X3D / 9950X3D)

> Depuis l'ajout du superviseur anti-freeze : le bench **ne fige plus** si le
> backend capteurs se bloque (ex. CPU non supporté). Il attend un premier
> échantillon CPU exploitable (`STREAM_WARMUP_SEC`), puis renonce avec un message
> explicite ; et si le flux s'interrompt en cours de bench, un watchdog tue le
> backend, coupe la charge et abandonne la session proprement. Le diagnostic
> ci-dessous reste nécessaire pour traiter la cause de fond.

## Cause
Ghisdiag lit la température et la fréquence CPU via LibreHardwareMonitor (LHM),
qui accède aux registres **MSR** du processeur. Cet accès passe par un driver
kernel : **PawnIO**. Voir [`collectors/pawnio.py`](collectors/pawnio.py) :

> *Sans PawnIO : GPU, disques, ventilateur GPU et charge CPU remontent ; mais la
> température CPU, la fréquence CPU et les ventilateurs carte mère restent N/A.*

Les trois causes possibles, **par ordre de probabilité** :

1. **PawnIO non installé** (ou installation différée car l'app n'était pas élevée).
2. **CPU trop récent pour la DLL LHM embarquée** (actuellement `0.9.6`). Un Zen 5
   X3D peut ne pas être reconnu → LHM n'expose aucun capteur de température CPU.
3. **Application non lancée en administrateur** → accès MSR bloqué.

> ⚠️ Un fallback WMI (`MSAcpi_ThermalZoneTemperature`) **ne convient pas** au bench
> thermique : c'est une zone ACPI carte mère, pas la température de die CPU ; elle
> ne suit pas la charge et fausserait le delta T. Le moniteur temps réel l'utilise
> déjà comme dernier recours ([`collectors/realtime_monitor.py`](collectors/realtime_monitor.py)),
> mais le bench a besoin de la vraie sonde CPU.

---

## Étape 1 — Diagnostiquer

Sur la machine concernée, **dans une console Administrateur** :

```bash
python diagnose_sensors.py
```

Le script rapporte l'élévation, l'état de PawnIO, la présence de la DLL, le modèle
CPU, et la liste brute des capteurs CPU vus par LHM, puis un verdict.

➡️ **Copie-colle toute la sortie** : c'est elle qui détermine le correctif.

---

## Étape 2 — Corriger selon le verdict

### a) « Console non élevée »
Relance Ghisdiag (ou le diagnostic) en **Administrateur**. En production l'exe
tourne déjà sous UAC ; le problème se pose surtout en test/dev.

### b) « PawnIO absent »
En administrateur :
```
tools\PawnIO_setup.exe -install -silent
```
Puis relance le diagnostic. (Ghisdiag tente cette installation automatiquement
via [`collectors/pawnio.py`](collectors/pawnio.py) quand il est élevé.)

### c) « LHM n'expose AUCUN capteur CPU » / « LHM se fige » (CPU trop récent)
La DLL embarquée (`0.9.6`) ne connaît pas ce processeur (cas du Zen 5). On peut
**remplacer le backend sans recompiler** : Ghisdiag charge en priorité un jeu de
DLL plus récent s'il en trouve un (override). Voir [`collectors/lhm_backend.py`](collectors/lhm_backend.py).

Mise à jour (console Administrateur) :
```bash
py update_backend.py                  # télécharge la dernière release LHM (réseau)
py update_backend.py chemin\vers.zip  # ou installe un zip net472 local (hors ligne)
```
Le nouveau backend est déposé dans `%LOCALAPPDATA%\Ghisdiag\tools` et prime sur
l'embarqué au prochain démarrage. Pour forcer un jeu précis : le poser dans un
dossier `tools` à côté de l'exe, ou pointer `GHISDIAG_TOOLS_DIR` dessus.
`diagnose_sensors.py` (section [3]) affiche le dossier actif et la version chargée.

### d) « LHM expose des capteurs mais aucune température reconnue »
Là, et **seulement là**, le mapping de noms dans
[`collectors/sensors.ps1`](collectors/sensors.ps1) est à adapter — sur la base des
noms réels remontés par le diagnostic, pas en devinant.

---

## Fichiers liés
- [`diagnose_sensors.py`](diagnose_sensors.py) — diagnostic ciblé (élévation, PawnIO, backend, capteurs)
- [`diagnose_probe.py`](diagnose_probe.py) — isole le sous-système LHM qui se fige
- [`update_backend.py`](update_backend.py) — met à jour le backend LHM (remplaçable)
- [`collectors/lhm_backend.py`](collectors/lhm_backend.py) — résolution + mise à jour du backend
- [`collectors/pawnio.py`](collectors/pawnio.py) — gestion du driver PawnIO
- [`collectors/sensors.ps1`](collectors/sensors.ps1) — lecture LHM (mode `-Once` = `debug_sensors`)
- Logs : `Documents\Ghisdiag_Reports\…` / `ghisdiag.log`
