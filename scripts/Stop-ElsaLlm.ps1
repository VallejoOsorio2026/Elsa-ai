<#
.SYNOPSIS
    Detiene el llama-server que arrancó ELSA. Solo ese.

.DESCRIPTION
    Lee el registro que dejó Start-ElsaLlm.ps1 y detiene **ese** proceso,
    comprobando antes que el PID sigue siendo el mismo proceso.

    La comprobación no es paranoia: Windows reutiliza los identificadores de
    proceso. Si el llama-server de ELSA terminó y el sistema reasignó su PID,
    matar ese número a ciegas detendría un proceso ajeno elegido al azar. Por
    eso se compara también la hora de arranque, que sí identifica una
    ejecución concreta.

    Tampoco se hace `Get-Process llama-server | Stop-Process`: en esa máquina
    puede haber otro llama.cpp corriendo —otro modelo, otro proyecto, una
    prueba de alguien— y no es nuestro.

    No deja nada permanente detrás: borra el archivo de PID y, por defecto,
    también el log.

    El log se borra porque `llama-server` vuelca por su salida el prompt que
    procesa, y el prompt de ELSA es el bloque de evidencias: documentación
    interna de planta. Dejarlo en el perfil de quien arrancó el servidor sería
    un archivo de texto plano con contenido de planta fuera de toda política
    de retención. Para una sesión de medición, `-KeepLog` lo conserva y
    entonces borrarlo es responsabilidad de quien lo pidió.

.PARAMETER KeepLog
    Conserva el log del servidor. Úsalo solo mientras se diagnostica algo, y
    bórralo después: puede contener texto de evidencias.

.EXAMPLE
    .\scripts\Stop-ElsaLlm.ps1
    .\scripts\Stop-ElsaLlm.ps1 -KeepLog   # mientras se investiga un fallo
#>

[CmdletBinding()]
param(
    [int]    $TimeoutSeconds = 20,
    [switch] $KeepLog
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RuntimeDir = Join-Path $env:LOCALAPPDATA 'ELSA\llm'
$PidFile    = Join-Path $RuntimeDir 'llama-server.json'
$LogFile    = Join-Path $RuntimeDir 'llama-server.log'

function Clear-RuntimeLog {
    param([switch] $Keep)

    if ($Keep) {
        Write-Warning "El log se conserva en $LogFile. Puede contener texto de evidencias: bórralo al terminar."
        return
    }
    foreach ($path in @($LogFile, "$LogFile.err")) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    }
}

if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host "No hay ningún llama-server registrado por ELSA. Nada que detener."
    exit 0
}

$record = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
$process = Get-Process -Id $record.ProcessId -ErrorAction SilentlyContinue

if (-not $process) {
    Write-Host "El proceso $($record.ProcessId) ya no existe. Se limpia el registro."
    Remove-Item -LiteralPath $PidFile -Force
    Clear-RuntimeLog -Keep:$KeepLog
    exit 0
}

if ($process.StartTime.ToString('o') -ne $record.StartTime) {
    # Mismo número, otra ejecución: Windows reutilizó el PID.
    Write-Warning @"
El PID $($record.ProcessId) pertenece ahora a otro proceso ($($process.ProcessName)),
no al llama-server que arrancó ELSA. No se detiene nada.
"@
    Remove-Item -LiteralPath $PidFile -Force
    exit 0
}

Write-Host "Deteniendo llama-server de ELSA (PID $($process.Id), $($process.ProcessName))..."

# Cierre ordenado primero: liberar la VRAM de una tarjeta de 4 GB conviene
# hacerlo bien. Si no atiende, se fuerza.
$process.CloseMainWindow() | Out-Null
if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
    Write-Host "No respondió en $TimeoutSeconds s; se fuerza el cierre."
    Stop-Process -Id $process.Id -Force
    $process.WaitForExit(5000) | Out-Null
}

Remove-Item -LiteralPath $PidFile -Force
Clear-RuntimeLog -Keep:$KeepLog
Write-Host "Detenido." -ForegroundColor Green
