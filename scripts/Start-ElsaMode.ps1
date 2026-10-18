<#
.SYNOPSIS
    Inicia el Modo ELSA en este equipo: ELSA local y el agente de PC1, en orden.

.DESCRIPTION
    Ejecuta `python -m elsa.pc1 start` con el Python del .venv del repositorio.
    La ventana queda abierta mientras el Modo ELSA está en marcha: es la
    ventana «Modo ELSA». Para detenerlo, Ctrl+C en ella o Stop-ElsaMode.ps1.

    Antes de arrancar se comprueba la configuración. Si el token del nodo no
    está en el entorno de esta sesión, se pide sin mostrarlo en pantalla. El
    token nunca se pasa como parámetro ni se escribe en un archivo.

    No requiere administrador y no cambia nada permanente de Windows: no
    instala servicios, no toca el registro ni el cortafuegos y no abre puertos.
    Ver docs/pc1-modo-elsa-runbook.md.

.EXAMPLE
    .\scripts\Start-ElsaMode.ps1
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

# Nombre de la ventana para el operador; algunos hosts no lo permiten.
try { $Host.UI.RawUI.WindowTitle = 'Modo ELSA' } catch { }

# ELSA y el agente leen el .env de la raíz del repositorio: se ejecuta desde ahí.
Push-Location -LiteralPath $RepoRoot
try {
    & $Python -m elsa.pc1 start
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
