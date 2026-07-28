# Ghisdiag v2.0.2 — correctif critique : les capteurs ne fonctionnaient pas après téléchargement

> ⚠️ **Si vous utilisez la 2.0.0 ou la 2.0.1, mettez à jour.** Sur ces versions,
> aucune température, aucun ventilateur et aucune fréquence ne remontait dès lors
> que l'archive avait été téléchargée puis décompressée normalement. Le moniteur
> et le bench thermique étaient hors service.

---

## Ce qui se passait

Une archive téléchargée avec un navigateur porte une marque invisible : **« ce
fichier vient d'Internet »** (*Mark of the Web*). Quand l'Explorateur Windows la
décompresse, il **recopie cette marque sur chacun des fichiers extraits**.

Or .NET refuse de charger un composant depuis un emplacement ainsi marqué. Le
moteur de capteurs ne pouvait donc plus charger une seule de ses bibliothèques,
et l'application se retrouvait aveugle :

```
Impossible de charger le fichier ou l'assembly
'...\_internal\tools\System.Runtime.CompilerServices.Unsafe.dll'
L'opération n'est pas prise en charge. (HRESULT : 0x80131515)
```

## Pourquoi ça n'avait pas été vu

Le défaut est né du **passage en dossier portable** (v2.0.0). Auparavant, les
bibliothèques étaient embarquées dans l'exécutable et extraites par l'application
elle-même : Windows ne les marquait jamais. Depuis, elles sont livrées en
fichiers libres dans `_internal\tools`, et héritent de la marque de l'archive.

Il est passé au travers de tous les essais parce que le développement, comme
l'usage sur clé USB en atelier, part de fichiers **copiés** — et Windows ne
marque que ce qui a été téléchargé. Le cas nominal de l'utilisateur, lui, était
le seul cassé.

## Le correctif

L'application retire la marque de ses propres bibliothèques avant de les charger.
**Rien à faire de votre côté** : il n'est pas nécessaire de « débloquer »
l'archive avant de la décompresser.

L'opération ne touche qu'au dossier `tools` de Ghisdiag, elle est sans effet si
la marque est absente, et n'interrompt rien si elle échoue — le message d'erreur
exact remonte alors jusqu'à vous.

## Comment il a été trouvé

Par la remontée des causes d'erreur livrée en **2.0.1**. Avant elle, le moteur
savait pourquoi il échouait mais jetait le message, et le journal ne contenait
que « les capteurs ne répondent pas ». C'est en lisant enfin la vraie erreur
qu'on a pu la reproduire, puis la corriger.

---

## 📥 Téléchargement

| | |
|---|---|
| **Fichier** | `Ghisdiag.zip` |
| **Taille** | `<TAILLE>` octets |
| **SHA-256** | `<SHA256>` |

> Ces valeurs portent sur l'archive **compilée par GitHub Actions** à partir du
> tag `v2.0.2` — celle qui est jointe à cette release et qui porte l'attestation
> de provenance.

Vérifier l'intégrité :

```powershell
Get-FileHash Ghisdiag.zip -Algorithm SHA256
```

Vérifier la provenance :

```powershell
gh attestation verify Ghisdiag.zip --repo ghislaindoucy/ghisdiag
```

**Prérequis :** Windows 10/11. Rien d'autre à installer. Décompressez l'archive
et gardez le dossier entier.

---

Le reste de la 2.0.1 est inchangé — voir
[`RELEASE_NOTES_v2.0.1.md`](RELEASE_NOTES_v2.0.1.md) pour le détail de la
fiabilité du bench thermique.
