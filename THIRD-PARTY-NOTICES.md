# Mentions légales — composants tiers

Ghisdiag intègre et redistribue des composants tiers (binaires `tools/`). Ceux-ci
restent la propriété de leurs auteurs respectifs et sont distribués sous leurs
licences propres, reproduites dans le dossier [`licenses/`](./licenses/).

Ces composants sont utilisés **sans modification** et sont invoqués comme
**bibliothèques chargées ou processus séparés** (voir détails ci-dessous). Le
code propre à Ghisdiag reste sous sa propre licence
([PolyForm Noncommercial 1.0.0](./LICENSE)) ; les licences ci-dessous ne
s'appliquent qu'à leurs composants respectifs.

> **Usage commercial.** Toutes les licences ci-dessous autorisent l'usage
> commercial et la redistribution, y compris payante. Aucune autorisation ni
> notification préalable n'est requise auprès des auteurs : le respect des
> obligations listées (attribution + mise à disposition des sources pour les
> composants copyleft) suffit.

---

## Récapitulatif

| Composant | Version | Auteur / Copyright | Licence | Intégration |
|---|---|---|---|---|
| smartmontools (`smartctl.exe`) | 7.5.0 | © 2002–2025 Bruce Allen, Christian Franke | **GPL-2.0-or-later** | Processus séparé |
| PawnIO (`PawnIO_setup.exe`) | 2.2.0 | © 2026 namazso | **GPL-2.0-or-later** (+ exception IOCTL) | Driver installé / processus séparé |
| LibreHardwareMonitorLib | 0.9.6 | © LibreHardwareMonitor contributors | **MPL-2.0** | Bibliothèque .NET |
| DiskInfoToolkit | 1.1.2 | © Florian K. (Blacktempel) | **MPL-2.0** | Bibliothèque .NET |
| BlackSharp.Core | 1.0.7 | © Florian K. (Blacktempel) | **MPL-2.0** | Bibliothèque .NET |
| HidSharp | 2.6.4 | © 2010–2025 James F. Bellinger / Illusory Studios LLC | **Apache-2.0** | Bibliothèque .NET |
| System.Memory | 4.6.3 | © .NET Foundation and Contributors | **MIT** | Bibliothèque .NET |
| System.Numerics.Vectors | 4.6.1 | © .NET Foundation and Contributors | **MIT** | Bibliothèque .NET |
| System.Runtime.CompilerServices.Unsafe | 6.1.2 | © .NET Foundation and Contributors | **MIT** | Bibliothèque .NET |

---

## Détails et obligations respectées

### smartmontools — `smartctl.exe`
- **Licence :** GNU GPL v2 ou ultérieure — [`licenses/GPL-2.0.txt`](./licenses/GPL-2.0.txt)
- **Site / sources :** https://www.smartmontools.org/ — code source : https://www.smartmontools.org/wiki/Download
- **Intégration :** appelé comme **exécutable indépendant** (processus séparé, via
  `System.Diagnostics.Process`). Il s'agit d'une simple agrégation : Ghisdiag
  n'est pas une œuvre dérivée de smartmontools et n'est pas affecté par la GPL.
- **Obligations :** ce binaire GPL est redistribué accompagné de sa licence et
  d'un accès au code source (lien ci-dessus). Il ne doit jamais être lié
  statiquement dans l'exécutable Ghisdiag.

### PawnIO — `PawnIO_setup.exe`
- **Licence :** GNU GPL v2 ou ultérieure, **avec exception de liaison** : les
  modules indépendants qui communiquent avec PawnIO uniquement via l'interface
  de contrôle d'entrée/sortie (IOCTL) ne sont pas couverts par la GPL. C'est le
  mode d'utilisation ici (PawnIO est installé comme driver et interrogé via
  IOCTL par LibreHardwareMonitor). — [`licenses/GPL-2.0.txt`](./licenses/GPL-2.0.txt)
- **Site / sources :** https://github.com/namazso/PawnIO
- **Intégration :** installeur signé exécuté en **processus séparé**
  (`PawnIO_setup.exe -install -silent`) ; le driver tourne ensuite indépendamment.
- **Licence alternative :** contact `admin@namazso.eu` (non nécessaire dans le
  cadre d'un usage conforme à la GPL).

### LibreHardwareMonitorLib
- **Licence :** Mozilla Public License 2.0 — [`licenses/MPL-2.0.txt`](./licenses/MPL-2.0.txt)
- **Site / sources :** https://github.com/LibreHardwareMonitor/LibreHardwareMonitor
- **Intégration :** bibliothèque .NET chargée, **non modifiée**.
- **Obligations :** la MPL est un copyleft « par fichier ». Les fichiers MPL
  restant inchangés et utilisés tels quels, il suffit de fournir la licence et
  l'accès aux sources (lien ci-dessus). Le code de Ghisdiag reste sous sa propre
  licence.

### DiskInfoToolkit
- **Licence :** Mozilla Public License 2.0 — [`licenses/MPL-2.0.txt`](./licenses/MPL-2.0.txt)
- **Sources :** https://www.nuget.org/packages/DiskInfoToolkit
- **Note :** une partie du code de base s'appuie sur CrystalDiskInfo. Distribué
  par son auteur sous MPL-2.0, ce qui couvre l'ensemble.
- **Intégration / obligations :** identiques à LibreHardwareMonitorLib (dépendance).

### BlackSharp.Core
- **Licence :** Mozilla Public License 2.0 — [`licenses/MPL-2.0.txt`](./licenses/MPL-2.0.txt)
- **Sources :** https://www.nuget.org/packages/BlackSharp.Core
- **Intégration / obligations :** identiques à LibreHardwareMonitorLib (dépendance).

### HidSharp
- **Licence :** Apache License 2.0 — [`licenses/Apache-2.0.txt`](./licenses/Apache-2.0.txt)
- **Copyright :** © 2010–2025 James F. Bellinger — http://software.seekye.com/hidsharp
- **Sources :** https://github.com/IntergatedCircuits/HidSharp
- **Intégration :** bibliothèque .NET chargée, non modifiée.
- **Obligations :** conserver l'avis de copyright et le texte de la licence
  Apache-2.0 (ci-joint). Aucune modification n'a été apportée.

### Composants Microsoft .NET (System.Memory, System.Numerics.Vectors, System.Runtime.CompilerServices.Unsafe)
- **Licence :** MIT — [`licenses/MIT.txt`](./licenses/MIT.txt)
- **Copyright :** © .NET Foundation and Contributors
- **Sources :** https://github.com/dotnet/runtime
- **Obligations :** conserver l'avis de copyright et le texte de la licence MIT
  (ci-joint).

---

*Document de conformité établi pour Ghisdiag v1.6.2. En cas d'ajout, de mise à
jour ou de retrait d'un composant tiers, ce fichier et le dossier `licenses/`
doivent être mis à jour en conséquence.*
