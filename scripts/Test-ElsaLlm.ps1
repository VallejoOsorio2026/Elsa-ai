<#
.SYNOPSIS
    Comprueba que el runtime responde y mide una generación mínima.

.DESCRIPTION
    Cuatro cosas, en orden, y cada una responde una pregunta distinta:

      1. /health    — ¿escucha alguien y tiene el modelo cargado?
      2. /props     — ¿con qué contexto y qué modelo arrancó de verdad?
      2b. /slots    — ¿está cerrado el endpoint que publicaría el prompt?
      3. generación — ¿cuánto tarda y a cuántos tokens por segundo?

    Es una comprobación del RUNTIME, no de ELSA: no hay recuperación, ni
    evidencia, ni verificación de citas. Para eso está la herramienta de
    Python, que recorre el camino del bloque:

        uv run python -m elsa.tools.llm_runtime demo "¿cada cuánto se lubrica?"

    Los números que imprime sirven de línea base para dimensionar PC1. No son
    medidas de laboratorio: una sola corrida, con la máquina como esté.

.EXAMPLE
    .\scripts\Test-ElsaLlm.ps1
    .\scripts\Test-ElsaLlm.ps1 -Prompt "Responde solo con la palabra LISTO."
#>

[CmdletBinding()]
param(
    [string] $BaseUrl,
    [string] $Model = 'phi-4-mini-instruct',
    [string] $Prompt = 'Responde solo con la palabra LISTO.',
    [int]    $MaxTokens = 64,
    [int]    $TimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RuntimeDir = Join-Path $env:LOCALAPPDATA 'ELSA\llm'
$PidFile    = Join-Path $RuntimeDir 'llama-server.json'

if (-not $BaseUrl) {
    if (Test-Path -LiteralPath $PidFile) {
        $BaseUrl = (Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json).BaseUrl
    } else {
        $BaseUrl = 'http://127.0.0.1:8080'
    }
}

Write-Host "Runtime: $BaseUrl"
Write-Host ""

# --------------------------------------------------------------------
# 1. Salud
# --------------------------------------------------------------------

try {
    $health = Invoke-WebRequest -Uri "$BaseUrl/health" -UseBasicParsing -TimeoutSec 10
} catch {
    Write-Error @"
El runtime no responde en $BaseUrl.
Arráncalo con .\scripts\Start-ElsaLlm.ps1 y vuelve a intentarlo.
"@
    exit 1
}

if ($health.StatusCode -ne 200) {
    Write-Error "El runtime respondió HTTP $($health.StatusCode): todavía está cargando el modelo."
    exit 1
}
Write-Host "[1/3] salud     : listo" -ForegroundColor Green

# --------------------------------------------------------------------
# 2. Con qué arrancó
# --------------------------------------------------------------------

try {
    $props = Invoke-RestMethod -Uri "$BaseUrl/props" -TimeoutSec 10
    Write-Host "[2/3] modelo    : $($props.model_path)"
    if ($props.PSObject.Properties.Name -contains 'default_generation_settings') {
        $ctx = $props.default_generation_settings.n_ctx
        Write-Host "      contexto  : $ctx tokens (por ranura)"
    }
} catch {
    Write-Host "[2/3] modelo    : /props no disponible en esta versión de llama.cpp"
}

# --------------------------------------------------------------------
# 2b. El endpoint de ranuras tiene que estar cerrado
# --------------------------------------------------------------------

# `/slots` viene ACTIVADO por defecto en llama.cpp y publica el prompt en
# curso de cada ranura: en ELSA, el bloque de evidencias. Start-ElsaLlm.ps1
# arranca con `--no-slots`, y esto comprueba que la versión instalada
# efectivamente lo respeta en vez de darlo por hecho.
try {
    $slots = Invoke-WebRequest -Uri "$BaseUrl/slots" -UseBasicParsing -TimeoutSec 10
    if ($slots.StatusCode -eq 200) {
        Write-Warning @"
GET $BaseUrl/slots responde 200: el endpoint de ranuras está ABIERTO y publica
el prompt en curso, es decir el texto de las evidencias que ELSA envía.
Arranca el servidor con .\scripts\Start-ElsaLlm.ps1, que añade --no-slots.
"@
    } else {
        Write-Host "[2b/3] ranuras  : cerrado (HTTP $($slots.StatusCode))" -ForegroundColor Green
    }
} catch {
    Write-Host "[2b/3] ranuras  : cerrado" -ForegroundColor Green
}

# --------------------------------------------------------------------
# 3. Generación
# --------------------------------------------------------------------

# Misma interfaz que usa el adaptador de ELSA: si esto funciona y la
# aplicación no, el problema no es el runtime.
$body = @{
    model       = $Model
    messages    = @(@{ role = 'user'; content = $Prompt })
    temperature = 0
    max_tokens  = $MaxTokens
    stream      = $false
} | ConvertTo-Json -Depth 5

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $result = Invoke-RestMethod -Uri "$BaseUrl/v1/chat/completions" -Method Post `
        -ContentType 'application/json; charset=utf-8' `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
        -TimeoutSec $TimeoutSeconds
} catch {
    Write-Error "La generación falló: $($_.Exception.Message)"
    exit 1
}
$stopwatch.Stop()

$content = $result.choices[0].message.content
Write-Host "[3/3] generación: ok" -ForegroundColor Green
Write-Host ""
Write-Host "--- respuesta ---"
Write-Host $content.Trim()
Write-Host ""
Write-Host "latencia total  : $([math]::Round($stopwatch.Elapsed.TotalSeconds, 2)) s"

if ($result.PSObject.Properties.Name -contains 'usage') {
    Write-Host "tokens entrada  : $($result.usage.prompt_tokens)"
    Write-Host "tokens salida   : $($result.usage.completion_tokens)"
}
if ($result.PSObject.Properties.Name -contains 'timings') {
    # Medido por llama-server: solo la fase de generación. La latencia de
    # arriba incluye además leer el prompt, así que los dos números no son
    # comparables y no se mezclan.
    Write-Host "tokens/s        : $([math]::Round($result.timings.predicted_per_second, 1)) (medidos por llama-server)"
}
Write-Host ""
Write-Host "Camino completo de ELSA (contexto + citas + verificación):"
Write-Host "  uv run python -m elsa.tools.llm_runtime demo `"¿cada cuánto se lubrica el rodamiento?`""
