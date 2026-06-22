# finalize_release.ps1
# Calcule le SHA-256 + la taille de l'exe, les injecte dans les notes de release,
# puis (optionnel) commit et push. A lancer depuis la racine du projet APRES build.bat.
#
# Exemples :
#   .\finalize_release.ps1                          # remplit les fichiers + affiche (pas de commit)
#   .\finalize_release.ps1 -Commit                  # remplit + commit
#   .\finalize_release.ps1 -Commit -Push            # remplit + commit + push (origin main & master)
#   .\finalize_release.ps1 -Commit -Push -Release   # + attache l'exe, met a jour les notes et PUBLIE la release GitHub

param(
    [string]$Version = "1.4.0",
    [string]$ExePath = "dist\Ghisdiag.exe",
    [switch]$Commit,
    [switch]$Push,
    [switch]$Release
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ExePath)) {
    Write-Error "Exe introuvable : $ExePath  ->  lance build.bat d'abord."
    exit 1
}

$notes     = "RELEASE_NOTES_v$Version.md"
$checklist = "RELEASE_CHECKLIST_v$Version.md"
if (-not (Test-Path $notes)) { Write-Error "Notes introuvables : $notes"; exit 1 }

$file   = Get-Item $ExePath
$hash   = (Get-FileHash $ExePath -Algorithm SHA256).Hash.ToLower()
$sizeMB = [math]::Round($file.Length / 1MB, 1)

Write-Host ""
Write-Host "  Exe    : $($file.FullName)"
Write-Host "  Taille : $sizeMB MB"
Write-Host "  SHA256 : $hash"

# Controle de coherence : la version embarquee doit matcher (sinon build pre-bump)
$fv = $file.VersionInfo.ProductVersion
if ($fv) {
    Write-Host "  Version exe (ProductVersion) : $fv"
    if ($fv -notlike "$Version*") {
        Write-Warning "L'exe est en $fv, pas $Version. As-tu rebuild APRES le bump de version ?"
    }
}
Write-Host ""

# --- Injection (UTF-8 sans BOM pour ne pas polluer le diff git) ---
$utf8 = New-Object System.Text.UTF8Encoding($false)
$replSha  = '- **Sha256** : `' + $hash + '`'
$replSize = '- **Taille** : ' + $sizeMB + ' MB'

$notesPath = (Resolve-Path $notes).Path
$txt = [System.IO.File]::ReadAllText($notesPath)
$txt = $txt -replace '(?m)^- \*\*Sha256\*\* :.*$', $replSha
$txt = $txt -replace '(?m)^- \*\*Taille\*\* :.*$',  $replSize
[System.IO.File]::WriteAllText($notesPath, $txt, $utf8)
Write-Host "  OK -> $notes"

if (Test-Path $checklist) {
    $ckPath = (Resolve-Path $checklist).Path
    $ck = [System.IO.File]::ReadAllText($ckPath)
    # Regex ASCII (independante des accents du placeholder) : [... remplir ... build]
    $ck = $ck -replace '\[[^\]]*remplir[^\]]*build[^\]]*\]', $hash
    [System.IO.File]::WriteAllText($ckPath, $ck, $utf8)
    Write-Host "  OK -> $checklist"
}
Write-Host ""

if ($Commit) {
    git add -- $notes $checklist
    git commit -m "release: SHA-256 et taille de l'exe v$Version"
    if ($LASTEXITCODE -ne 0) { Write-Error "Echec du commit"; exit 1 }
    Write-Host "  Commit cree."
    if ($Push) {
        git push origin HEAD:main HEAD:master
        if ($LASTEXITCODE -ne 0) { Write-Error "Echec du push"; exit 1 }
        Write-Host "  Pousse sur origin (main + master)."
    } else {
        Write-Host "  Pour publier : git push origin HEAD:main HEAD:master"
    }
} else {
    Write-Host "  (pas de commit -- relance avec -Commit, ou -Commit -Push)"
}
Write-Host ""

if ($Release) {
    $tag = "v$Version"
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-Error "GitHub CLI (gh) introuvable -- impossible de publier la release. Installe-le ou publie a la main."
        exit 1
    }
    # La release doit exister (creee en brouillon au prealable)
    gh release view $tag 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Aucune release $tag sur GitHub. Cree d'abord le brouillon : gh release create $tag --draft --title ... --notes-file $notes"
        exit 1
    }
    Write-Host "  Publication de la release GitHub $tag..."
    # 1) Attache l'exe (--clobber : remplace l'asset si on relance)
    gh release upload $tag $ExePath --clobber
    if ($LASTEXITCODE -ne 0) { Write-Error "Echec de l'upload de l'exe"; exit 1 }
    Write-Host "  Exe attache."

    # 1b) Conformite licences : attache les mentions legales + les textes de licence
    #     (obligation d'attribution / mise a disposition des sources des composants tiers)
    $notices = "THIRD-PARTY-NOTICES.md"
    if (Test-Path $notices) {
        $licZip = "THIRD-PARTY-LICENSES_v$Version.zip"
        if (Test-Path $licZip) { Remove-Item $licZip -Force }
        $toZip = @($notices)
        if (Test-Path "licenses") { $toZip += "licenses" }
        Compress-Archive -Path $toZip -DestinationPath $licZip -Force
        gh release upload $tag $notices $licZip --clobber
        if ($LASTEXITCODE -ne 0) { Write-Error "Echec de l'upload des mentions legales"; exit 1 }
        Write-Host "  Mentions legales attachees ($notices + $licZip)."
        Remove-Item $licZip -Force   # artefact temporaire (ignore par git)
    } else {
        Write-Warning "THIRD-PARTY-NOTICES.md introuvable -- mentions legales NON attachees."
    }

    # 2) Met a jour les notes (hash desormais rempli) + passe en public
    gh release edit $tag --notes-file $notes --draft=false
    if ($LASTEXITCODE -ne 0) { Write-Error "Echec de la publication"; exit 1 }
    Write-Host "  Release publiee :"
    gh release view $tag --json url -q .url
}
Write-Host ""
