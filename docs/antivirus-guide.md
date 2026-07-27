# Guide — Antivirus & Faux Positifs Ghisdiag

Ghisdiag est signalé par plusieurs antivirus, parfois comme *trojan*. C'est un faux
positif structurel : l'outil cumule des comportements qui, pris ensemble, reproduisent
la chaîne d'un logiciel voleur d'identifiants.

Le détail complet de ces comportements et de leur justification est dans
[transparence-systeme.md](transparence-systeme.md) — c'est le document à joindre à
tout signalement.

Ce guide liste les actions à prendre, **en séparant ce qui est gratuit de ce qui est
payant**, car la signature numérique représente un coût annuel récurrent.

---

## Partie A — Actions gratuites

### A1. Réduire les déclencheurs dans le build

**Déjà appliqué :**

- `version_info.txt` — métadonnées PE (éditeur, description, copyright). Un exe
  anonyme est nettement plus suspect qu'un exe identifié.
- `upx=False` — la compression UPX est un marqueur de packer qui ajoute plusieurs
  points au score heuristique, même sur un binaire sain.
- **`onedir` au lieu de `onefile`** — `onefile` emballait un interpréteur Python
  complet dans un exe qui se décompressait dans `%TEMP%` à chaque exécution :
  schéma identique à celui de nombreux *droppers*. `onedir` produit un dossier
  (exe + DLL séparées) et ne décompresse rien. Sortie : `dist\Ghisdiag\` plus
  l'archive `dist\Ghisdiag.zip` pour la distribution.
- `uac_admin=True` dans le `.spec` — sans ce paramètre, PyInstaller réécrivait le
  `requestedExecutionLevel` du manifeste à `asInvoker`, et l'application se
  rattrapait en se relançant elle-même en mode élevé. Ce double lancement est en
  soi un comportement que les moteurs comportementaux regardent de près.

### A2. Réduire les comportements signalés dans l'application

**Déjà appliqué :** la sauvegarde des profils WiFi n'exporte plus les mots de passe
en clair par défaut. L'export en clair reste disponible sur confirmation explicite —
il reste nécessaire pour restaurer après une réinstallation de Windows ou sur une
autre machine, la clé chiffrée par DPAPI ne survivant pas à ces deux cas.

L'export en masse de PSK en clair vers une archive est *exactement* la signature
comportementale de la famille `PWS:Win32/WifiStealer`. Le déplacer du chemin par
défaut vers un acte confirmé réduit la fréquence à laquelle ce motif est observé, et
donne un argument concret dans les signalements de faux positifs. À noter cependant :
en usage atelier, le technicien répondra souvent « oui » — le gain est réel mais
partiel, et ne remplace pas la signature numérique.

### A3. Provenance vérifiable via l'intégration continue

Le workflow [`.github/workflows/build-release.yml`](../.github/workflows/build-release.yml)
compile `dist\Ghisdiag\` sur un runner GitHub à partir du code source taggé,
en produit l'archive `Ghisdiag.zip`, puis
génère une **attestation de provenance signée** (SLSA). N'importe qui peut vérifier
que le binaire publié provient exactement de ce code source public :

```bash
gh attestation verify Ghisdiag.zip --repo ghislaindoucy/ghisdiag
```

C'est l'argument le plus solide dont on dispose sans certificat : un analyste
traitant un signalement peut auditer la source correspondant au hash, au lieu de
devoir faire confiance à un binaire opaque.

Le workflow se déclenche sur push d'un tag `v*`.

`Ghisdiag.spec` et `Ghisdiag.manifest` sont **versionnés** (exceptions explicites
dans `.gitignore`), et `build.bat` les consomme au lieu de les régénérer. Local et CI
compilent donc avec exactement les mêmes options.

⚠ PyInstaller n'est pas reproductible au bit près : deux compilations successives du
même code donnent des binaires de taille et d'empreinte différentes. L'attestation ne
prouve donc pas « ce binaire est le seul possible », mais « **ce** binaire précis a
été produit par GitHub Actions à partir de **ce** commit public ». C'est suffisant
pour un analyste antivirus — à condition de publier l'exe compilé par la CI, pas
celui compilé en local.

Conséquence sur la checklist de release : le numéro de version du manifeste UAC se
change désormais dans `Ghisdiag.manifest`, et non plus dans `build.bat`.

### A4. Signaler les faux positifs aux éditeurs

À faire **après chaque version**. C'est gratuit et c'est ce qui débloque
concrètement les détections une par une.

1. Déposer `dist\Ghisdiag\Ghisdiag.exe` sur [virustotal.com](https://www.virustotal.com)
2. Noter quels moteurs détectent quelque chose
3. Soumettre **uniquement** à ceux-là

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

Pour Microsoft, soumettre **en tant que développeur du logiciel** (l'option existe
dans le formulaire) : le traitement est prioritaire et la décision s'applique aux
versions suivantes.

#### Modèle de message

```
Objet : False Positive Report — Ghisdiag.exe

Bonjour,

Je vous soumets un faux positif détecté par votre produit.

Logiciel : Ghisdiag v<VERSION>
Éditeur  : Ghislain DOUCY
Usage    : Outil de diagnostic et de dépannage Windows destiné aux
           techniciens informatiques (analyse matériel, réseau, sécurité,
           benchmark thermique, réparation système).
Source   : https://github.com/ghislaindoucy/ghisdiag

Hash SHA-256 : <HASH>
VirusTotal   : <URL DU RAPPORT>

Ce binaire est compilé publiquement par GitHub Actions à partir du code
source ci-dessus, et dispose d'une attestation de provenance SLSA
vérifiable via :
    gh attestation verify Ghisdiag.zip --repo ghislaindoucy/ghisdiag

Les comportements susceptibles de déclencher votre heuristique sont
documentés en détail ici, avec leur justification fonctionnelle :
https://github.com/ghislaindoucy/ghisdiag/blob/main/docs/transparence-systeme.md

En résumé : l'outil est compilé avec PyInstaller, demande les droits
administrateur (accès WMI et capteurs matériels), lit les profils WiFi
sur action explicite de l'utilisateur (fonction de sauvegarde/restauration
destinée aux réinstallations), et peut vider les journaux d'événements
après réparation. Aucune donnée ne quitte la machine et aucune de ces
actions n'est automatique.

Merci de mettre à jour vos signatures.

Cordialement,
Ghislain DOUCY
```

Empreinte SHA-256 :
```powershell
Get-FileHash dist\Ghisdiag.zip -Algorithm SHA256 | Select-Object Hash
Get-FileHash dist\Ghisdiag\Ghisdiag.exe -Algorithm SHA256 | Select-Object Hash
```

### A5. Construire une réputation

- **Canal de téléchargement stable** — même URL entre les versions. Les moteurs de
  réputation apprennent qu'un fichier venant de ce domaine est sain.
- **Publier sur winget** — être dans le catalogue Microsoft est l'un des meilleurs
  signaux de légitimité pour Defender.
  Guide : https://github.com/microsoft/winget-pkgs/blob/master/CONTRIBUTING.md
- **SHA-256 dans les release notes** — déjà fait.

---

## Partie B — Signature numérique (payant)

C'est le levier qui règle 80 % du problème, mais aucune option n'est gratuite dans
notre situation. À enclencher quand l'application le justifie économiquement.

### Pourquoi il n'y a pas d'option gratuite ici

**SignPath Foundation** offre la signature de code gratuite aux projets open source,
mais exige une licence approuvée OSI. Ghisdiag est sous **PolyForm Noncommercial
1.0.0**, qui est une licence *source-available*, pas open source — le projet n'est
donc pas éligible. Y accéder supposerait de relicencier en MIT / Apache-2.0 / GPL,
ce qui abandonnerait la restriction d'usage commercial.

### Options payantes

Depuis juin 2023, **tous** les certificats Code Signing exigent un stockage de clé
sur matériel certifié FIPS 140-2 niveau 2. Les tarifs d'avant (~70 €/an) n'existent
plus.

| Option | Coût indicatif | Remarques |
|---|---|---|
| **Azure Trusted Signing** | ~10 $/mois | Certificat émis par Microsoft, signature par API donc scriptable dans le build, pas de token USB à gérer. Le meilleur rapport coût/effet aujourd'hui. **Vérifier les conditions d'éligibilité** (vérification d'identité, ancienneté) avant de compter dessus. |
| **Code Signing OV** | ~200-400 €/an | Token matériel à commander et conserver. Réduit les détections, mais SmartScreen exige encore d'accumuler de la réputation. |
| **Code Signing EV** | ~350-600 €/an | Réputation SmartScreen immédiate. |

Fournisseurs : [Sectigo](https://sectigo.com/ssl-certificates-tls/code-signing),
[DigiCert](https://www.digicert.com/signing/code-signing-certificates),
[GlobalSign](https://www.globalsign.com/en/code-signing-certificate/).

### Une fois le certificat obtenu

1. Décommenter le bloc `signtool` dans [`build.bat`](../build.bat).
2. `winget install Microsoft.WindowsSDK.10.0.22621` pour disposer de `signtool`.
3. Vérifier : `signtool verify /pa /v dist\Ghisdiag\Ghisdiag.exe`
4. **Signer aussi les scripts `.ps1`** (`Set-AuthenticodeSignature`), puis remplacer
   `-ExecutionPolicy Bypass` par `AllSigned` dans
   [`orchestrator.py`](../orchestrator.py). Cela supprime le déclencheur
   « PowerShell masqué avec politique contournée », qui est l'un des plus lourdement
   pondérés.

---

## Ordre de priorité

1. ✅ `upx=False`, `onedir`, `uac_admin=True`, métadonnées PE — fait
2. ✅ Sauvegarde WiFi sans clés en clair par défaut — fait
3. ✅ Build CI avec attestation de provenance — fait
4. ⬜ Soumettre la prochaine version à VirusTotal, puis aux éditeurs qui détectent
5. ⬜ Publier sur winget
6. ⬜ Signature numérique, quand le budget le permet
