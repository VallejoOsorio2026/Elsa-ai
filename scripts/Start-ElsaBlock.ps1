<#
.SYNOPSIS
    Lanza el runner local de bloques de trabajo de ELSA.

.DESCRIPTION
    Ejecuta scripts/orchestrator.py con el Python del .venv del repositorio.
    Lee la especificación de %USERPROFILE%\elsa-o1\inbox\<id>.md.

    Validate no cambia el repositorio. Run pide escribir APROBAR <id> y deja como
    mucho commits locales en la rama del bloque: sin push, sin PR y sin merge.
    Cleanup retira la copia de trabajo sin forzar nada. Status lista las copias.

    No requiere administrador, no instala nada y no recibe secretos.
    Ver docs/orchestration/README.md.

.EXAMPLE
    .\scripts\Start-ElsaBlock.ps1 -Action Validate -Block O1.3
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Validate', 'Run', 'Status', 'Cleanup')]
    [string]$Action,

    [string]$Block
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# El Python del entorno del repositorio, sin `uv run`: lanzar el runner no debe
# sincronizar dependencias ni tocar la red. El Python global no es el del proyecto.
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host 'No se encontró el entorno de ELSA (.venv). Prepárelo siguiendo el README.' -ForegroundColor Red
    exit 3
}

if ($Action -ne 'Status' -and [string]::IsNullOrWhiteSpace($Block)) {
    Write-Host 'Esta acción necesita -Block <id>.' -ForegroundColor Red
    exit 3
}

$Runner = Join-Path $PSScriptRoot 'orchestrator.py'
$Arguments = @($Runner, $Action.ToLowerInvariant())
if ($Action -ne 'Status') {
    $Arguments += $Block
}

# Sin cambiar de carpeta: el runner fija la carpeta de cada proceso que lanza.
& $Python @Arguments
$code = $LASTEXITCODE
exit $code
