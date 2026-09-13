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
    Interfaz de escucha. 127.0.0.1 por defecto, y cambiarlo exige -AllowRemote:
    llama-server no lleva autenticación y este bloque no se la añade.

.EXAMPLE
    .\scripts\Start-ElsaLlm.ps1
    .\scripts\Start-ElsaLlm.ps1 -ContextSize 4096 -Threads 4
#>

[CmdletBinding()]
param(
    [string] $ModelPath,
    [string] $LlamaServer,
    [string] $BindAddress = '127.0.0.1',
    [int]    $Port = 8080,
    [int]    $ContextSize = 2048,
    [int]    $Parallel = 1,
    [int]    $Threads = 4,
    [int]    $GpuLayers = 99,
    [string] $Device = 'Vulkan0',
    [string] $EnvFile = '.env',
    [int]    $ReadyTimeoutSeconds = 180,
    [switch] $AllowRemote
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

if (-not (Test-Path -LiteralPath $ModelPath)) {
    throw "No existe el modelo GGUF: $ModelPath"
}
if (-not (Test-Path -LiteralPath $LlamaServer)) {
    throw "No existe llama-server: $LlamaServer"
}

$loopback = @('127.0.0.1', 'localhost', '::1')
if (($loopback -notcontains $BindAddress) -and (-not $AllowRemote)) {
    throw @"
$BindAddress no es loopback. llama-server NO lleva autenticación: exponerlo a
la LAN deja la generación abierta a cualquiera que alcance el puerto. La
superficie pública de ELSA es FastAPI, no este servidor.
Si aun así hace falta, vuelve a ejecutar con -AllowRemote y declara también
ELSA_LLM_ALLOW_REMOTE=true en el .env.
"@
}

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
$arguments = @(
    '--model', $ModelPath,
    '--alias', 'phi-4-mini-instruct',
    '--host', $BindAddress,
    '--port', $Port,
    '--ctx-size', $ContextSize,
    '--parallel', $Parallel,
    '--threads', $Threads,
    '--n-gpu-layers', $GpuLayers,
    '--device', $Device,
    '--no-webui'
)

Write-Host "ELSA — arranque del runtime de generación local"
Write-Host "  llama-server : $LlamaServer"
Write-Host "  modelo       : $($modelInfo.Name) ($sizeGb GB)"
Write-Host "  escucha      : http://${BindAddress}:$Port"
Write-Host "  contexto     : $ContextSize tokens   ranuras: $Parallel   hilos: $Threads"
Write-Host "  dispositivo  : $Device (capas en GPU: $GpuLayers)"
Write-Host "  log          : $LogFile"
Write-Host ""

$startedAt = Get-Date
$process = Start-Process -FilePath $LlamaServer -ArgumentList $arguments `
    -RedirectStandardOutput $LogFile -RedirectStandardError "$LogFile.err" `
    -WindowStyle Minimized -PassThru

[ordered]@{
    ProcessId   = $process.Id
    StartTime   = $process.StartTime.ToString('o')
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
        if ($response.StatusCode -eq 200) { $ready = $true; break }
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
