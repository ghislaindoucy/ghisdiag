# Ghisdiag - Generateur de charge CPU (bench thermique)
#
# Lance N runspaces (par defaut un par processeur logique) executant une boucle
# de calcul flottant a rapport cyclique configurable. Sert a chauffer le CPU de
# maniere reproductible pendant la phase de charge du bench thermique.
#
# Pourquoi des runspaces et pas du multiprocessing Python : en --onefile, chaque
# processus Python enfant reextrait les ~20 Mo du bundle. Les runspaces .NET
# d'un seul powershell.exe n'ont pas de GIL et saturent reellement tous les
# coeurs sans ce cout.
#
# L'arret est pilote par le parent : il termine ce processus (TerminateProcess)
# en fin de phase ou en arret d'urgence. -DurationSec sert de garde-fou si le
# parent disparait (l'auto-arret evite de laisser le CPU en charge indefiniment).
#
# Pas de caractere non-ASCII dans ce fichier (regle PS du projet).

param(
    [int]$Threads     = 0,     # 0 = nombre de processeurs logiques
    [int]$Intensity   = 100,   # rapport cyclique vise, 1..100 (% de temps de calcul)
    [int]$DurationSec  = 0     # 0 = illimite (le parent termine le processus)
)

$ErrorActionPreference = "SilentlyContinue"

if ($Threads -le 0)      { $Threads = [Environment]::ProcessorCount }
if ($Intensity -lt 1)    { $Intensity = 1 }
if ($Intensity -gt 100)  { $Intensity = 100 }

# Echeance absolue (garde-fou). MaxValue.Ticks si illimite.
$deadlineTicks = if ($DurationSec -gt 0) {
    [System.DateTime]::UtcNow.AddSeconds($DurationSec).Ticks
} else {
    [System.DateTime]::MaxValue.Ticks
}

# Corps d'un worker : boucle a rapport cyclique sur une fenetre de 100 ms.
# On calcule pendant $intensity ms (occupation ALU/FPU), puis on dort le reste.
# A 100 d'intensite, offMs = 0 -> aucune pause, coeur sature en continu.
$worker = {
    param($deadlineTicks, $intensity)

    $sw    = [System.Diagnostics.Stopwatch]::new()
    $onMs  = [double]$intensity
    $offMs = 100.0 - $onMs
    $x     = 1.0

    while ([System.DateTime]::UtcNow.Ticks -lt $deadlineTicks) {
        $sw.Restart()
        while ($sw.Elapsed.TotalMilliseconds -lt $onMs) {
            # Chaine de calcul flottant non triviale pour que le JIT n'elimine
            # pas la boucle. La valeur est bornee pour rester finie.
            $x = [System.Math]::Sqrt($x * 1.0000001 + 1.0)
            $x = $x * $x - 0.5
            if ($x -gt 1000000.0 -or $x -lt -1000000.0) { $x = 1.0 }
        }
        if ($offMs -ge 1.0) {
            [System.Threading.Thread]::Sleep([int]$offMs)
        }
    }
}

# Pool de runspaces : un par worker, tous concurrents.
$pool = [runspacefactory]::CreateRunspacePool(1, $Threads)
$pool.Open()

$handles = New-Object System.Collections.Generic.List[object]
for ($i = 0; $i -lt $Threads; $i++) {
    $ps = [powershell]::Create()
    $ps.RunspacePool = $pool
    [void]$ps.AddScript($worker).AddArgument($deadlineTicks).AddArgument($Intensity)
    $handles.Add([pscustomobject]@{ PS = $ps; Async = $ps.BeginInvoke() })
}

# Attente de la fin (echeance atteinte) ou terminaison externe par le parent.
try {
    foreach ($h in $handles) {
        try { $h.PS.EndInvoke($h.Async) } catch {}
        try { $h.PS.Dispose() } catch {}
    }
}
finally {
    try { $pool.Close() }   catch {}
    try { $pool.Dispose() } catch {}
}
