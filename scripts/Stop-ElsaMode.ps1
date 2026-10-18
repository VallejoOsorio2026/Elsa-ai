<#
.SYNOPSIS
    Detiene el Modo ELSA en este equipo: primero el agente, después ELSA local.

.DESCRIPTION
    Ejecuta `python -m elsa.pc1 stop` con el Python del .venv del repositorio.
    No detiene ningún proceso por sí mismo: pide la parada al supervisor (la
    ventana «Modo ELSA») y espera a que termine. Nunca toca procesos que no
    haya iniciado el Modo ELSA. Ver docs/pc1-modo-elsa-runbook.md.

.EXAMPLE
    .\scripts\Stop-ElsaMode.ps1
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
    & $Python -m elsa.pc1 stop
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
