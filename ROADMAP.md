# PlanetDiag — Résumé & Roadmap

**Version actuelle : 1.4.0** (2026-06-11) — [Release](https://github.com/ghislaindoucy/planetdiag/releases/tag/v1.4.0)

---

## 📋 L'application aujourd'hui

PlanetDiag est un **outil de diagnostic et de maintenance Windows tout-en-un**, compilé
en un seul exécutable (PyInstaller, ~19 MB), sans aucune dépendance à installer sur la
machine cible. Pensé pour le technicien SAV : on branche, on lance, on repart avec un
rapport.

### Ce qu'il fait (4 onglets)

**🔍 Analyse** — le cœur du produit
- 8 collecteurs PowerShell exécutés en parallèle (~20 s) : système, performances,
  démarrage/services, événements, réseau, sécurité, logiciels/drivers, santé disques
- **Journaux de fiabilité niveau 3** : BSOD avec code BugCheck, erreurs matérielles
  WHEA, erreurs disque, corruption NTFS, services en échec
- **SMART complet** via smartctl embarqué (NVMe : usure, spare, erreurs ; SATA : attributs)
- Rapport **HTML interactif** (thème Catppuccin) + **JSON** exploitable par une IA
- **Audit IA Mistral** optionnel : 10 sections, corrélations entre données, cause
  racine, niveau de confiance — et zéro problème inventé (garde-fous anti-faux-positifs)
- Moniteur temps réel CPU / RAM / disque / températures

**🔧 Dépannage**
- Impression : spooler, files d'attente, annulation, page de test
- Réseau : état des cartes, réinitialisation
- Réparation système : SFC + DISM en streaming avec suivi live

**📶 WiFi**
- Profils enregistrés : consultation (avec mot de passe), suppression, sauvegarde/restauration
- Scan des réseaux et connexion

**⚙️ Setup / MAJ**
- Comptes locaux (création, renommage, expiration de mot de passe)
- Mises à jour logicielles via winget
- PC Neuf : installation silencieuse des essentiels + icônes du bureau
- Récupération : partition de récupération, BitLocker

### Architecture (pour mémoire)

```
main.py               UI tkinter (thème Catppuccin Mocha)
orchestrator.py       exécution parallèle des collecteurs PS1
collectors/*.ps1      collecte (pattern Safe-Get partagé)
report/generator.py   rapport HTML/JSON + règles d'alertes déclaratives
mistral_analyzer.py   audit IA (prompt rigueur + profondeur)
prefs.py / security.py  préférences persistées, UAC, garde-fous
```

---

## 🗺️ Roadmap

### v1.5.0 — 🌡️ Bench thermique avant/après maintenance ⭐ *priorité*

**Le besoin** : objectiver le gain d'un nettoyage ou d'un changement de pâte thermique.
Courbes de température **avant** intervention, courbes **après**, et chiffrage du gain —
un argument concret à montrer au client.

#### Phase 0 — Source de températures fiable *(prérequis)*

La collecte actuelle (WMI `MSAcpi_ThermalZoneTemperature`, souvent vide sur desktop ;
namespace OpenHardwareMonitor, exige OHM lancé) est trop fragile pour un bench.

- Embarquer **LibreHardwareMonitorLib.dll** (MPL 2.0, redistribuable) chargée depuis
  un collecteur PowerShell (`Add-Type -Path`) qui dump tous les capteurs en JSON —
  même pattern que smartctl (`--add-binary`)
- Capteurs cibles : CPU package + cœurs, GPU, disques, **vitesses ventilateurs**
  (précieux pour diagnostiquer un ventirad encrassé) et fréquences CPU
- Fallback : chaîne actuelle si la DLL échoue
- Bénéfice immédiat : le moniteur temps réel affiche enfin des températures partout

#### Phase 1 — Moteur de bench

- **Protocole en 3 phases** : repos (~2 min, baseline) → charge (5-10 min, stress CPU
  configurable 50/100 %) → refroidissement (~5 min)
- Génération de charge par **multiprocessing** (un processus par cœur logique — les
  threads Python ne chargent pas un CPU à cause du GIL)
- Échantillonnage toutes les 2-5 s : températures + charge + fréquence CPU
- **Détection de throttling** : fréquence qui s'effondre quand la température plafonne
- **Arrêt d'urgence** : automatique si T > 95 °C, ou bouton Stop
- Métriques : T idle, T max, T plateau en charge, ΔT, temps de retour au calme
- Session sauvegardée en JSON horodaté, étiquetée **Avant / Après / Libre**
  (`Documents\PlanetDiag_Reports\thermal\`)

#### Phase 2 — UI : nouvel onglet « Bench thermique »

- Courbes **temps réel** sur `tk.Canvas` (multi-séries CPU/GPU/disque, zones colorées
  par phase) — pas de matplotlib : l'exe resterait léger
- Configuration simple : durée, intensité, étiquette avant/après
- Liste des sessions enregistrées de la machine

#### Phase 3 — Comparaison avant/après & gains

- Sélection de 2 sessions → **courbes superposées** + carte des gains :
  ΔT idle, ΔT max, ΔT plateau, Δ temps de refroidissement, throttling éliminé (oui/non)
- **Rapport HTML dédié** avec courbes en SVG auto-généré (offline, imprimable,
  à remettre au client) et verdict clair : *« −12 °C en charge — intervention efficace »*
- Garde-fou honnêteté : comparer uniquement des sessions au protocole identique,
  avertir que la température ambiante n'est pas contrôlée

---

### v1.6.0 — Diagnostic encore plus parlant

- **Résumé exécutif** « Ce qui ralentit ce PC » en tête du rapport HTML (top 3 priorisé)
- **Pilotes obsolètes / non signés** : détection + source de mise à jour
- **Analyse du boot par phase** (Event ID 100 : MainPath, drivers, services, profil)
- **Historique des diagnostics** : comparer deux rapports JSON dans le temps —
  la machine s'améliore ou se dégrade ? (synergie directe avec le bench thermique)

### Plus tard / opportuniste

- **Signature de code** de l'exe (réduction des faux positifs antivirus — process déjà
  documenté dans build.bat, il manque le certificat)
- Benchmark disque simple (débit séquentiel/aléatoire avant/après remplacement)
- Export PDF du rapport
- Mode « rapport client » simplifié (vulgarisé, sans jargon)

---

*Document vivant — mis à jour à chaque release.*
