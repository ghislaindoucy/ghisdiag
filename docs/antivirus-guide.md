# Guide — Antivirus & Faux Positifs Ghisdiag

Un exécutable PyInstaller `--onefile` non signé déclenche souvent des faux positifs AV.
Ce guide décrit les actions à prendre, du plus efficace au moins urgent.

---

## 1. Signer numériquement le binaire (priorité absolue)

Sans signature, chaque nouvelle version repart à zéro en termes de réputation.

### Quel certificat choisir ?

| Type | Prix indicatif | Effet |
|---|---|---|
| **Code Signing standard** | 70-200 €/an | Réduit Bitdefender, Kaspersky, ESET, Norton |
| **Code Signing EV** | 250-400 €/an + token HSM | Réputation SmartScreen **immédiate** — Windows Defender ne bloque plus |

→ Recommandation : **EV si possible**, sinon standard pour commencer.

### Fournisseurs recommandés
- [Sectigo](https://sectigo.com/ssl-certificates-tls/code-signing) (ex-Comodo, tarifs compétitifs)
- [DigiCert](https://www.digicert.com/signing/code-signing-certificates) (référence entreprise)
- [GlobalSign](https://www.globalsign.com/en/code-signing-certificate/) (livraison rapide)

### Installation et signature

```bat
:: 1. Installez le certificat dans votre magasin Windows (Personal > Certificates)
::    Le fournisseur vous guidera selon le type (standard = fichier PFX, EV = token USB)

:: 2. Décommentez le bloc signtool dans build.bat

:: 3. Vérifiez que signtool est disponible :
winget install Microsoft.WindowsSDK.10.0.22621

:: 4. Testez la signature :
signtool verify /pa /v dist\Ghisdiag.exe
```

---

## 2. Soumettre les faux positifs aux éditeurs AV

À faire **après chaque version majeure**. Rassemblez d'abord l'analyse VirusTotal :

1. Allez sur [virustotal.com](https://www.virustotal.com)
2. Déposez `dist\Ghisdiag.exe`
3. Notez quels AV détectent un problème
4. Soumettez uniquement à ceux qui détectent

### Formulaires de soumission faux positifs

| Éditeur | URL de soumission |
|---|---|
| **Microsoft Defender** | https://www.microsoft.com/wdsi/filesubmission |
| **Bitdefender** | https://www.bitdefender.com/consumer/support/answer/29358/ |
| **Kaspersky** | https://opentip.kaspersky.com/ |
| **ESET** | samples@eset.com (objet : False Positive) |
| **Avast / AVG** | https://www.avast.com/false-positive-file-form.php |
| **Norton** | https://submit.norton.com/ |
| **McAfee / Trellix** | https://www.trellix.com/support/submit-a-sample/ |
| **Sophos** | https://www.sophos.com/en-us/support/contact-support/submit-sample.aspx |
| **Trend Micro** | https://success.trendmicro.com/solution/1059565 |
| **Malwarebytes** | https://forums.malwarebytes.com/forum/122-false-positives/ |
| **G Data** | https://www.gdatasoftware.com/faq/consumer/how-to-report-false-positives |
| **F-Secure** | https://www.f-secure.com/en/for-the-community/report-a-sample |

### Modèle de message à envoyer

```
Objet : False Positive Report — Ghisdiag.exe

Bonjour,

Je vous soumets un faux positif détecté par votre produit.

Logiciel : Ghisdiag v1.2.0
Éditeur  : Ghislain DOUCY
Usage    : Outil de diagnostic Windows (analyse matériel, réseau, sécurité)
           Génère un rapport HTML/JSON exportable. Open source.
Hash SHA-256 : [collez le hash de dist\Ghisdiag.exe]
VirusTotal   : [collez l'URL du rapport]

Ce logiciel est développé avec Python/PyInstaller et nécessite des droits
administrateur pour accéder à WMI. Il ne contient aucun code malveillant.

Merci de mettre à jour vos signatures.

Cordialement,
Ghislain DOUCY
```

Pour obtenir le hash SHA-256 :
```powershell
Get-FileHash dist\Ghisdiag.exe -Algorithm SHA256 | Select-Object Hash
```

---

## 3. Réduire les déclencheurs heuristiques dans le build

### version_info.txt (déjà actif depuis v1.2.1)
Les métadonnées PE (CompanyName, FileDescription, Copyright) sont maintenant
embarquées. Un exe anonyme est beaucoup plus suspect qu'un exe avec éditeur identifié.

### --onedir vs --onefile

`--onefile` emballe un interpréteur Python complet dans un seul exe qui se
décompresse dans `%TEMP%` à l'exécution — pattern identique à de nombreux droppers.

`--onedir` génère un dossier avec l'exe + DLLs séparées, beaucoup moins flagué.

**Pour basculer en --onedir**, remplacez dans `build.bat` :
```bat
:: Avant
--onefile ^

:: Après
--onedir ^
```
L'utilisateur recevra un dossier `dist\Ghisdiag\` au lieu d'un seul fichier.
Zippez ce dossier pour la distribution.

---

## 4. Réputation à long terme

- **Distribuer via un canal fixe** — même URL de téléchargement entre les versions.
  Les AV "apprennent" qu'un fichier venant de ce domaine est sûr.
- **Publier sur winget** — ironiquement, être dans le catalogue winget est l'une
  des meilleures preuves de légitimité pour les AV Microsoft.
  Guide : https://github.com/microsoft/winget-pkgs/blob/master/CONTRIBUTING.md
- **GitHub Releases avec checksums** — publiez le SHA-256 dans les release notes,
  les utilisateurs peuvent vérifier l'intégrité.
- **Microsoft Store (MSIX)** — packaging MSIX signé = zero SmartScreen pour les
  utilisateurs qui installent via le Store.
