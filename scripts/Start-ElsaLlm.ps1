<#
.SYNOPSIS
    Arranca el runtime de generación local de ELSA (llama-server + Phi-4-mini).

.DESCRIPTION
    Levanta `llama-server` como PROCESO PERSISTENTE, escuchando solo en
    loopback, y espera a que tenga el modelo cargado antes de devolver el
    control.

    Persistente y no una invocación por consulta: cargar un GGUF cuantizado
    cuesta segundos y varios gigas de RAM y VRAM. Hacerlo en cada pregunta
    —lo que ocurriría al llamar a `llama-cli`— convertiría una respuesta de
    unos segundos en una de decenas, y en una tarjeta de 4 GB además
    arriesgaría quedarse sin memoria a mitad.

    El script NO cambia nada permanente de Windows: no instala servicios, no
    toca el registro, no abre puertos en el cortafuegos y no modifica
    variables de entorno del sistema. Deja un archivo de PID y un log en
    %LOCALAPPDATA%\ELSA\llm para que Stop-ElsaLlm.ps1 pueda detener
    exactamente este proceso y no otro.

    Esto NO es el «Modo ELSA»: no cierra aplicaciones, no libera memoria a la
    fuerza y no reorganiza el escritorio. Solo arranca un servidor.

.PARAMETER ModelPath
    Ruta del archivo .gguf. Por defecto, ELSA_LLM_MODEL_PATH del .env.
    Nunca se versiona: depende de la máquina.

.PARAMETER LlamaServer
    Ruta de llama-server.exe. Por defecto, ELSA_LLAMA_SERVER_PATH del .env.

.PARAMETER BindAddress
    Interfaz de escucha. Solo se permite 127.0.0.1 en este bloque.

.PARAMETER ContextSize
    Tokens de contexto. Por defecto, ELSA_LLM_CONTEXT_TOKENS del .env — NO un
    valor propio del script. La aplicación decide cuánta evidencia enviar
    creyendo ese número, así que un contexto de arranque distinto la dejaría
    razonando sobre una ventana que no existe, y el servidor truncaría en
    silencio.

.PARAMETER Parallel
    Ranuras simultáneas. Por defecto, ELSA_LLM_CONCURRENCY del .env, por el
    mismo motivo: el adaptador limita su concurrencia a ese mismo número.

.EXAMPLE
    .\scripts\Start-ElsaLlm.ps1
    .\scripts\Start-ElsaLlm.ps1 -ContextSize 4096 -Threads 4
#>

[CmdletBinding()]
param(
    [string] $ModelPath,
    [string] $LlamaServer,
    [string] $BindAddress = '127.0.0.1',
    [int]    $Port = 0,
    [int]    $ContextSize = 0,
    [int]    $Parallel = 0,
    [string] $Alias,
    [int]    $Threads = 4,
    [int]    $GpuLayers = 99,
    [string] $Device = 'Vulkan0',
    [string] $EnvFile = '.env',
    [ValidateRange(1, 3600)]
    [int]    $ReadyTimeoutSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RuntimeDir = Join-Path $env:LOCALAPPDATA 'ELSA\llm'
$PidFile    = Join-Path $RuntimeDir 'llama-server.json'
$LogFile    = Join-Path $RuntimeDir 'llama-server.log'

function Read-EnvFile {
    <#
        Lee un .env sin interpretarlo como script. Solo `CLAVE=valor`; las
        líneas en blanco y los comentarios se ignoran. Deliberadamente no se
        usa Invoke-Expression: un .env es un archivo de configuración, no
        código que haya que ejecutar.
    #>
    param([string] $Path)

    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
        $index = $trimmed.IndexOf('=')
        if ($index -lt 1) { continue }
        $key = $trimmed.Substring(0, $index).Trim()
        $value = $trimmed.Substring($index + 1).Trim().Trim('"')
        if ($value -ne '') { $values[$key] = $value }
    }
    return $values
}

function Get-Setting {
    <#
        Valor de configuración, sin exigirlo. Devuelve $null si no está.
    #>
    param([hashtable] $EnvValues, [string] $Key)

    $fromEnvironment = [Environment]::GetEnvironmentVariable($Key)
    if ($fromEnvironment) { return $fromEnvironment }
    if ($EnvValues.ContainsKey($Key)) { return $EnvValues[$Key] }
    return $null
}

function Resolve-Setting {
    param([string] $Explicit, [hashtable] $EnvValues, [string] $Key, [string] $Label)

    if ($Explicit) { return $Explicit }
    # La variable de entorno real gana sobre el .env, igual que en la
    # configuración de la aplicación.
    $fromEnvironment = [Environment]::GetEnvironmentVariable($Key)
    if ($fromEnvironment) { return $fromEnvironment }
    if ($EnvValues.ContainsKey($Key)) { return $EnvValues[$Key] }
    throw "Falta $Label. Decláralo con el parámetro correspondiente o con $Key en $EnvFile."
}

# --------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------

$envValues   = Read-EnvFile -Path $EnvFile
$ModelPath   = Resolve-Setting $ModelPath   $envValues 'ELSA_LLM_MODEL_PATH'    'la ruta del modelo GGUF'
$LlamaServer = Resolve-Setting $LlamaServer $envValues 'ELSA_LLAMA_SERVER_PATH' 'la ruta de llama-server'

# Los parámetros del servidor salen de la MISMA configuración que lee la
# aplicación. Tenerlos duplicados aquí como valores propios del script haría
# que arrancar con `-ContextSize 4096` dejara a ELSA creyendo 2048: la
# validación `ELSA_LLM_MAX_OUTPUT_TOKENS < ELSA_LLM_CONTEXT_TOKENS` pasaría a
# no significar nada, porque la ventana real la fija el servidor. Un
# parámetro explícito sigue ganando, para poder probar.
if (-not $ContextSize) {
    $value = Get-Setting $envValues 'ELSA_LLM_CONTEXT_TOKENS'
    $ContextSize = if ($value) { [int] $value } else { 2048 }
}
if (-not $Parallel) {
    $value = Get-Setting $envValues 'ELSA_LLM_CONCURRENCY'
    $Parallel = if ($value) { [int] $value } else { 1 }
}
if (-not $Alias) {
    $value = Get-Setting $envValues 'ELSA_LLM_MODEL'
    $Alias = if ($value) { $value } else { 'phi-4-mini-instruct' }
}
if (-not $Port) {
    # El puerto se deduce de la URL que la aplicación va a usar: dos puertos
    # distintos serían un runtime al que ELSA no llama.
    $baseUrl = Get-Setting $envValues 'ELSA_LLM_BASE_URL'
    $Port = if ($baseUrl -and ([uri] $baseUrl).Port -gt 0) { ([uri] $baseUrl).Port } else { 8080 }
}

if (-not (Test-Path -LiteralPath $ModelPath)) {
    throw "No existe el modelo GGUF: $ModelPath"
}
if (-not (Test-Path -LiteralPath $LlamaServer)) {
    throw "No existe llama-server: $LlamaServer"
}

if ($BindAddress -ne '127.0.0.1') {
    throw 'Bloque 4.5: llama-server solo puede escuchar en 127.0.0.1.'
}
if ($Port -lt 1 -or $Port -gt 65535 -or $ContextSize -lt 1 -or $Parallel -lt 1 -or $Threads -lt 1) {
    throw 'Puerto, contexto, concurrencia e hilos deben ser positivos y válidos.'
}
# Un puerto ocupado no debe confundirse con readiness de nuestro proceso.
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try { $listener.Start() } finally { $listener.Stop() }

if (Test-Path -LiteralPath $PidFile) {
    $previous = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    $running = Get-Process -Id $previous.ProcessId -ErrorAction SilentlyContinue
    if ($running -and $running.StartTime.ToString('o') -eq $previous.StartTime) {
        throw "Ya hay un llama-server de ELSA en marcha (PID $($previous.ProcessId)). Deténlo con Stop-ElsaLlm.ps1."
    }
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

$modelInfo = Get-Item -LiteralPath $ModelPath
$sizeGb = [math]::Round($modelInfo.Length / 1GB, 2)

# --------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------

# La temperatura NO se fija aquí: la manda ELSA en cada petición, desde
# ELSA_LLM_TEMPERATURE. Un valor de arranque distinto del de la aplicación
# haría que la misma configuración diera resultados distintos según quién
# arrancara el servidor.
#
# `--no-slots` no es opcional. El endpoint de ranuras viene ACTIVADO por
# defecto en llama.cpp y publica el estado de cada ranura, prompt en curso
# incluido: es decir, el bloque de evidencias que ELSA acaba de enviar,
# legible con un GET y sin credencial. Loopback protege de la LAN, no de
# otro proceso o de otra sesión de la misma máquina, y PC1 es un equipo de
# planta. Lo mismo con `--no-webui`, que además serviría una interfaz de
# chat sobre el mismo modelo.
$arguments = @(
    '--model', $ModelPath,
    '--alias', $Alias,
    '--host', $BindAddress,
    '--port', $Port,
    '--ctx-size', ($ContextSize * $Parallel),
    '--parallel', $Parallel,
    '--threads', $Threads,
    '--n-gpu-layers', $GpuLayers,
    '--device', $Device,
    '--no-context-shift',
    '--cors-origins', "http://127.0.0.1:$Port",
    '--no-cors-credentials',
    '--no-agent',
    '--no-webui',
    '--no-slots'
)

Write-Host "ELSA — arranque del runtime de generación local"
Write-Host "  llama-server : $LlamaServer"
Write-Host "  modelo       : $($modelInfo.Name) ($sizeGb GB), alias $Alias"
Write-Host "  escucha      : http://${BindAddress}:$Port"
Write-Host "  contexto     : $ContextSize tokens   ranuras: $Parallel   hilos: $Threads"
Write-Host "  dispositivo  : $Device (capas en GPU: $GpuLayers)"
Write-Host "  endpoints    : /slots y la interfaz web, desactivados"
Write-Host "  log          : $LogFile  (puede contener texto de evidencias)"
Write-Host ""

$startedAt = Get-Date
# Start-Process une ArgumentList con espacios; cada argumento necesita comillas.
$quotedArguments = foreach ($argument in $arguments) {
    $value = [string] $argument
    if ($value.Contains('"')) { throw 'Un argumento contiene comillas no admitidas.' }
    '"' + $value + '"'
}
$process = Start-Process -FilePath $LlamaServer -ArgumentList $quotedArguments `
    -RedirectStandardOutput $LogFile -RedirectStandardError "$LogFile.err" `
    -WindowStyle Hidden -PassThru

[ordered]@{
    ProcessId   = $process.Id
    StartTime   = $process.StartTime.ToString('o')
    ExecutablePath = (Resolve-Path -LiteralPath $LlamaServer).Path
    BaseUrl     = "http://${BindAddress}:$Port"
    ModelPath   = $ModelPath
    ContextSize = $ContextSize
    Parallel    = $Parallel
} | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8

# --------------------------------------------------------------------
# Readiness
# --------------------------------------------------------------------

# `/health` responde 503 mientras carga los pesos y 200 cuando ya puede
# generar. Se espera al 200: devolver el control antes dejaría a quien
# ejecute la primera consulta creyendo que el modelo está caído.
$healthUrl = "http://${BindAddress}:$Port/health"
$deadline = $startedAt.AddSeconds($ReadyTimeoutSeconds)
$ready = $false

Write-Host "Esperando a que el modelo esté cargado..." -NoNewline
while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) {
        Write-Host ""
        throw "llama-server terminó con código $($process.ExitCode). Revisa $LogFile.err"
    }
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200 -and -not $process.HasExited) {
            $props = Invoke-RestMethod -Uri "http://${BindAddress}:$Port/props" -TimeoutSec 5
            if ($props.default_generation_settings.n_ctx -ne $ContextSize -or $props.total_slots -ne $Parallel) {
                throw 'El runtime no coincide con el contexto/concurrencia configurados.'
            }
            $ready = $true
            break
        }
    } catch {
        # Todavía no escucha, o sigue cargando. Reintentar.
    }
    Start-Sleep -Milliseconds 500
    Write-Host "." -NoNewline
}
Write-Host ""

if (-not $ready) {
    throw "llama-server no quedó listo en $ReadyTimeoutSeconds s. Revisa $LogFile"
}

$elapsed = (Get-Date) - $startedAt
Write-Host ""
Write-Host "Listo." -ForegroundColor Green
Write-Host "  PID                : $($process.Id)"
Write-Host "  tiempo hasta listo : $([math]::Round($elapsed.TotalSeconds, 1)) s"
Write-Host "  endpoint           : http://${BindAddress}:$Port"
Write-Host ""
Write-Host "Comprueba una generación con:  .\scripts\Test-ElsaLlm.ps1"
Write-Host "Detén el servidor con:         .\scripts\Stop-ElsaLlm.ps1"
Write-Host ""
Write-Host "Recuerda: el log del servidor queda en tu perfil y puede contener el texto" -ForegroundColor DarkYellow
Write-Host "de las evidencias enviadas. Stop-ElsaLlm.ps1 lo borra salvo que pases -KeepLog." -ForegroundColor DarkYellow
