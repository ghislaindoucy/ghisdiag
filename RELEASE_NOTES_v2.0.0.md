# Ghisdiag v2.0.0 — Distribution en dossier portable

**Date : 27 juillet 2026**

---

## ⚠️ Ce qui change pour toi

Ghisdiag n'est plus un fichier `.exe` unique. Tu télécharges maintenant une
**archive `Ghisdiag.zip`** (~34 Mo, exactement la taille de l'ancien exe) que tu
décompresses où tu veux — disque local ou directement sur une clé USB.

Tu obtiens un dossier :

```
Ghisdiag\
├── Ghisdiag.exe        ← double-clique ici
└── _internal\          ← ne pas supprimer, ne pas déplacer
```

**Garde le dossier entier.** `Ghisdiag.exe` seul ne démarre pas : il a besoin du
sous-dossier `_internal\` posé à côté de lui.

C'est ce changement de format qui justifie le passage en version majeure. Aucune
fonctionnalité n'est retirée.

---

## 📦 Pourquoi ce changement

L'ancien format embarquait un interpréteur Python complet dans un exe unique, qui
**se décompressait dans le `%TEMP%` de la machine à chaque lancement** — 34 Mo, à
chaque fois. Trois conséquences :

1. **Lenteur en usage nomade.** Depuis une clé USB, cette décompression était le
   goulot d'étranglement de chaque démarrage, sur chaque poste client.
2. **Traces chez le client.** Un dossier `_MEI…` restait dans le `%TEMP%` de la
   machine diagnostiquée, parfois orphelin après un plantage.
3. **Faux positifs antivirus.** Ce schéma « je m'extrais dans TEMP puis je
   m'exécute » est exactement celui des logiciels malveillants de type *dropper*.
   Il pesait lourd dans le score heuristique des moteurs antivirus.

Le nouveau format ne décompresse rien : Windows charge les DLL directement depuis
le dossier.

---

## 🛡️ Antivirus — travail de fond

Ghisdiag était signalé comme *trojan* par plusieurs moteurs. C'est un **faux
positif structurel** : l'outil cumule des comportements légitimes qui, pris
ensemble, ressemblent à ceux d'un voleur d'identifiants (lecture de clés WiFi,
élévation de privilèges, effacement de journaux, accès matériel bas niveau).

Cette version s'y attaque sur plusieurs fronts :

- **Nouveau document [`docs/transparence-systeme.md`](docs/transparence-systeme.md)** —
  recense **toutes** les opérations privilégiées de Ghisdiag, leur justification
  et leur déclencheur. Destiné autant aux utilisateurs qu'aux analystes antivirus,
  à qui il est joint lors des signalements de faux positifs.
- **Sauvegarde WiFi sans mots de passe en clair par défaut.** L'export en clair
  reste disponible — il est indispensable pour restaurer après une réinstallation
  de Windows ou sur une autre machine — mais il demande désormais une confirmation
  explicite qui en énonce la conséquence. L'export en masse de clés WiFi en clair
  vers une archive est la signature comportementale exacte d'une famille entière
  de logiciels voleurs.
- **Abandon de la compression UPX**, marqueur de packer qui coûtait des points de
  score même sur un binaire sain.
- **Build public et vérifiable.** Un workflow GitHub Actions compile l'application
  à partir du code source taggé et génère une **attestation de provenance signée**
  (SLSA). N'importe qui — dont un analyste traitant un signalement — peut vérifier
  qu'une archive publiée provient bien de ce code source public :

  ```bash
  gh attestation verify Ghisdiag.zip --repo ghislaindoucy/ghisdiag
  ```

C'est le levier le plus solide disponible sans certificat de signature de code,
dont le coût annuel ne se justifie pas encore.

---

## 🩹 Correctifs

**Une seule invite UAC au démarrage.** Le manifeste de l'application déclarait
`requireAdministrator`, mais PyInstaller réécrit ce niveau à partir d'un de ses
propres paramètres et le forçait à `asInvoker` — le manifeste était donc
**inopérant depuis toujours**. L'application compensait en se relançant elle-même
en mode élevé, soit un double lancement du process à chaque démarrage,
particulièrement coûteux depuis une clé USB.

**Températures disque affichées immédiatement.** La première lecture n'était
déclenchée qu'au 5ᵉ cycle du moniteur, soit 10 secondes après l'ouverture : les
disques affichaient « N/A » pendant tout ce temps, alors que le CPU et le GPU
disposent d'un repli immédiat. Elles partent maintenant dès le premier cycle, et
un libellé « mesure… » distingue une lecture en cours d'une absence de donnée.

**Températures disque découplées de la lecture CPU.** Le cache n'était publié
qu'après le repli WMI de la température CPU — une requête qui coûte une seconde,
et jusqu'à six sur une machine sans PawnIO, où elle se déclenchait à *chaque*
cycle. GPU et disques sont désormais publiés dès qu'ils sont disponibles.

**Restauration WiFi : noms de profils lisibles.** La liste affichait les noms de
fichiers préfixés par l'interface (`Wi-Fi 3-MonReseau`) au lieu des noms réels.

---

## 🔧 Pour le développement

Nouveau commutateur **`GHISDIAG_DEBUG=1`** :

```powershell
$env:GHISDIAG_DEBUG = "1"; .\Ghisdiag.exe
```

Il bascule le journal (`%LOCALAPPDATA%\Ghisdiag\ghisdiag.log`) en `DEBUG` et ouvre
chaque session sur un bloc de contexte : version, exe gelé ou sources, chemin des
ressources, élévation effective, et **quels modules optionnels n'ont pas pu
s'importer, avec la cause exacte**.

La plupart des chemins capteurs attrapent leurs exceptions et les tracent en
`DEBUG` : sans ce commutateur, un « N/A » dans l'interface ne laissait aucune
trace exploitable. Les journaux HTTP restent volontairement en `INFO` pour
qu'aucune clé API ne se retrouve dans un fichier partagé.

Détails dans [`SENSORS_TROUBLESHOOTING.md`](SENSORS_TROUBLESHOOTING.md).

---

## 📥 Téléchargement

| | |
|---|---|
| **Fichier** | `Ghisdiag.zip` |
| **Taille** | `<TAILLE>` octets |
| **SHA-256** | `<SHA256>` |

> ⚠️ **À renseigner juste avant la publication**, sur le fichier exact qui sera
> mis en ligne. PyInstaller n'est pas reproductible au bit près : deux
> compilations du même code donnent des empreintes différentes. L'archive publiée
> doit être **celle compilée par GitHub Actions** — c'est elle qui porte
> l'attestation de provenance.

Vérifier l'intégrité après téléchargement :

```powershell
Get-FileHash Ghisdiag.zip -Algorithm SHA256
```

**Prérequis :** Windows 10/11. Rien d'autre à installer.
