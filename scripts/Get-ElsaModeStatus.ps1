<#
.SYNOPSIS
    Muestra el estado del Modo ELSA en este equipo. Solo lee: no cambia nada.

.DESCRIPTION
    Ejecuta `python -m elsa.pc1 status` con el Python del .venv del
    repositorio. Indica si el Modo ELSA está EN MARCHA, ARRANCANDO, DEGRADADO,
    DETENIÉNDOSE o DETENIDO, y si ELSA local está lista. La conectividad con
    Render no se verifica en este piloto. Ver docs/pc1-modo-elsa-runbook.md.

.EXAMPLE
    .\scripts\Get-ElsaModeStatus.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# El Python del entorno del repositorio, sin `uv run`: operar el nodo no debe
# sincronizar dependencias ni tocar la red.
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host 'No se encontró el entorno de ELSA (.venv). Prepárelo siguiendo el README.' -ForegroundColor Red
    exit 2
}

# ELSA y el agente leen el .env de la raíz del repositorio: se ejecuta desde ahí.
Push-Location -LiteralPath $RepoRoot
try {
    & $Python -m elsa.pc1 status
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
