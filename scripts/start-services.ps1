param(
  [int]$TimeoutSeconds = 180,
  [switch]$Build,
  [switch]$ForceRecreate,
  [switch]$SkipDockerDesktop
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DockerDesktopExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$DockerConfig = Join-Path $env:TEMP "agentic-genbi-docker-config"
$ComposeArgs = @("compose", "up", "-d")

if ($Build) {
  $ComposeArgs += "--build"
}
if ($ForceRecreate) {
  $ComposeArgs += "--force-recreate"
}

function Write-Step([string]$Message) {
  Write-Host "==> $Message"
}

function Invoke-WithTimeout {
  param(
    [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock,
    [int]$Seconds = 30,
    [string]$Name = "command"
  )

  $job = Start-Job -ScriptBlock $ScriptBlock
  try {
    if (-not (Wait-Job -Job $job -Timeout $Seconds)) {
      Stop-Job -Job $job -ErrorAction SilentlyContinue
      throw "$Name timed out after ${Seconds}s"
    }
    $output = Receive-Job -Job $job
    return $output
  } finally {
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
  }
}

function Test-DockerReady {
  try {
    $output = Invoke-WithTimeout -Seconds 12 -Name "docker info" -ScriptBlock {
      Set-Location $using:ProjectRoot
      $env:DOCKER_CONFIG = $using:DockerConfig
      docker info --format "{{.ServerVersion}}"
    }
    return [bool]($output -join "").Trim()
  } catch {
    return $false
  }
}

function Wait-DockerReady {
  param([int]$Seconds)

  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-DockerReady) {
      return
    }
    Start-Sleep -Seconds 3
  }
  throw "Docker daemon is not ready. Start Docker Desktop/WSL first, then rerun this script."
}

function Test-Http {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$Seconds = 5
  )

  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $Seconds
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
  } catch {
    return $false
  }
}

function Wait-Http {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$Name,
    [int]$Seconds
  )

  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-Http -Url $Url) {
      Write-Step "$Name is ready: $Url"
      return
    }
    Start-Sleep -Seconds 3
  }
  throw "$Name did not become ready: $Url"
}

New-Item -ItemType Directory -Force -Path $DockerConfig | Out-Null

Write-Step "Project root: $ProjectRoot"
Set-Location $ProjectRoot

if (-not $SkipDockerDesktop -and -not (Test-DockerReady)) {
  if (-not (Test-Path -LiteralPath $DockerDesktopExe)) {
    throw "Docker Desktop executable not found: $DockerDesktopExe"
  }
  Write-Step "Starting Docker Desktop"
  Start-Process -FilePath $DockerDesktopExe -WindowStyle Hidden
}

Write-Step "Waiting for Docker daemon"
Wait-DockerReady -Seconds $TimeoutSeconds

Write-Step "Starting compose services"
$env:DOCKER_CONFIG = $DockerConfig
& docker @ComposeArgs
if ($LASTEXITCODE -ne 0) {
  throw "docker $($ComposeArgs -join ' ') failed with exit code $LASTEXITCODE"
}

Write-Step "Compose status"
& docker compose ps

Write-Step "Waiting for backend health"
Wait-Http -Url "http://127.0.0.1:8000/health" -Name "backend" -Seconds $TimeoutSeconds

Write-Step "Waiting for frontend"
Wait-Http -Url "http://127.0.0.1:3000" -Name "frontend" -Seconds $TimeoutSeconds

Write-Step "Agentic GenBI services are ready"
