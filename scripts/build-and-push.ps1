<#
.SYNOPSIS
    Build the Looking Glass images and push them to a container registry.

.DESCRIPTION
    Builds the api, worker, and web targets from the root Dockerfile and pushes
    them. Postgres and Azurite are upstream images and are not built here.

    The default registry is Docker Hub. Run "docker login" first, or pass
    -Namespace. The default tag is the current git short SHA. Pass -Tag latest
    when you want that tag instead. -AlsoLatest also pushes :latest alongside
    the SHA.

    Commands go through the Docker context named "default".

.PARAMETER Registry
    Registry host, or host plus a path. Defaults to docker.io (Docker Hub).
    Examples: docker.io, myacr.azurecr.io, ghcr.io/myorg.

.PARAMETER Namespace
    Docker Hub user or organization. Defaults to the account from "docker login".
    Ignored when -Registry is not Docker Hub.

.PARAMETER Tag
    Image tag. Defaults to the git short SHA, or "latest" when git is unavailable.

.PARAMETER ImagePrefix
    Image name prefix. Defaults to looking-glass, producing looking-glass-api,
    looking-glass-worker, and looking-glass-web.

.PARAMETER Platform
    Target platform. Defaults to linux/amd64 so images built on Windows run in Azure.

.PARAMETER AcrLogin
    Run "az acr login" before pushing. The registry host must be *.azurecr.io.

.PARAMETER BuildOnly
    Build and tag the images, then stop before pushing.

.PARAMETER AlsoLatest
    Also tag and push :latest when -Tag is something else.

.EXAMPLE
    ./scripts/build-and-push.ps1

.EXAMPLE
    ./scripts/build-and-push.ps1 -Tag 1.4.0 -AlsoLatest

.EXAMPLE
    ./scripts/build-and-push.ps1 -Registry myacr.azurecr.io -AcrLogin
#>
[CmdletBinding()]
param(
    [string] $Registry = "docker.io",

    [string] $Namespace,

    [string] $Tag,

    [string] $ImagePrefix = "looking-glass",

    [string] $Platform = "linux/amd64",

    [switch] $AcrLogin,

    [switch] $BuildOnly,

    [switch] $AlsoLatest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "Dockerfile"))) {
    $Root = $PSScriptRoot
}
if (-not (Test-Path (Join-Path $Root "Dockerfile"))) {
    throw "Could not find the Looking Glass Dockerfile next to this script."
}

$DockerContext = "default"

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]] $DockerArgs)
    $prefix = @()
    if ($script:DockerContext) {
        $prefix = @("--context", $script:DockerContext)
    }
    # Windows PowerShell turns docker's stderr into a terminating error when
    # ErrorActionPreference is Stop. Continue lets us read the exit code instead.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker @prefix @DockerArgs
        if ($LASTEXITCODE -ne 0) {
            throw "docker $($DockerArgs -join ' ') failed with exit code $LASTEXITCODE."
        }
    } finally {
        $ErrorActionPreference = $previous
    }
}

Write-Host "Checking Docker..."
Write-Host "Using Docker context $DockerContext"
$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& docker --context $DockerContext info 1>$null 2>$null
$dockerReady = $LASTEXITCODE -eq 0
$ErrorActionPreference = $previous
if (-not $dockerReady) {
    throw "Docker context '$DockerContext' is not responding. Start Docker Desktop and try again."
}

if (-not $Tag) {
    $sha = $null
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        $sha = & git -C $Root rev-parse --short HEAD 2>$null
        if ($LASTEXITCODE -ne 0) {
            $sha = $null
        }
    }
    if ($sha) {
        $Tag = $sha.Trim()
    } else {
        $Tag = "latest"
    }
}

$Registry = $Registry.Trim().TrimEnd("/")
if ($Registry -eq "docker") {
    $Registry = "docker.io"
}
$dockerHub = $Registry -in @("docker.io", "index.docker.io", "registry.hub.docker.com", "https://index.docker.io/v1")
if ($dockerHub) {
    $Registry = "docker.io"
    if (-not $Namespace) {
        $helper = Get-Command "docker-credential-desktop" -ErrorAction SilentlyContinue
        if ($helper) {
            $previous = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $raw = "https://index.docker.io/v1/" | & docker-credential-desktop get 2>$null
            $loginOk = $LASTEXITCODE -eq 0
            $ErrorActionPreference = $previous
            if ($loginOk -and $raw) {
                try {
                    $Namespace = [string](($raw | ConvertFrom-Json).Username).Trim()
                } catch {
                    $Namespace = ""
                }
            }
        }
    }
    if (-not $Namespace) {
        throw "Docker Hub is the default registry. Run 'docker login', or pass -Namespace your-dockerhub-user."
    }
    $imageRoot = "$Registry/$Namespace"
} else {
    $imageRoot = $Registry
}

$images = @(
    @{ Target = "api"; Name = "$ImagePrefix-api" },
    @{ Target = "worker"; Name = "$ImagePrefix-worker" },
    @{ Target = "web"; Name = "$ImagePrefix-web" }
)

if ($AcrLogin -and -not $BuildOnly) {
    $hostName = ($Registry -split "/")[0]
    if ($hostName -notlike "*.azurecr.io") {
        throw "-AcrLogin needs an Azure Container Registry host such as myacr.azurecr.io."
    }
    $acrName = $hostName.Split(".")[0]
    $az = Get-Command az -ErrorAction SilentlyContinue
    if (-not $az) {
        throw "Azure CLI (az) is not installed, so -AcrLogin cannot run."
    }
    Write-Host "Logging in to ACR $acrName..."
    & az acr login --name $acrName
    if ($LASTEXITCODE -ne 0) {
        throw "az acr login failed with exit code $LASTEXITCODE."
    }
}

$pushed = @()
foreach ($image in $images) {
    $remote = "$imageRoot/$($image.Name):$Tag"
    Write-Host ""
    Write-Host "Building $($image.Target) -> $remote"
    Invoke-Docker build --platform $Platform --target $image.Target -t $remote -f (Join-Path $Root "Dockerfile") $Root
    $pushed += $remote
}

if ($BuildOnly) {
    Write-Host ""
    Write-Host "Built $($pushed.Count) images. Push was skipped."
    foreach ($remote in $pushed) {
        Write-Host "  $remote"
    }
    return
}

foreach ($remote in $pushed) {
    Write-Host ""
    Write-Host "Pushing $remote"
    Invoke-Docker push $remote
}

if ($AlsoLatest -and $Tag -ne "latest") {
    foreach ($image in $images) {
        $source = "$imageRoot/$($image.Name):$Tag"
        $latest = "$imageRoot/$($image.Name):latest"
        Write-Host ""
        Write-Host "Pushing $latest"
        Invoke-Docker tag $source $latest
        Invoke-Docker push $latest
        $pushed += $latest
    }
}

Write-Host ""
Write-Host "Pushed $($pushed.Count) images:"
foreach ($remote in $pushed) {
    Write-Host "  $remote"
}
