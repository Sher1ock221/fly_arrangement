param(
    [string]$NodeExeSource = "",
    [switch]$Force,
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[prepare-node-runtime] $Message"
}

function Resolve-ProjectRoot {
    param([string]$ExplicitProjectRoot)
    if ($ExplicitProjectRoot -and $ExplicitProjectRoot.Trim()) {
        return [System.IO.Path]::GetFullPath($ExplicitProjectRoot)
    }
    $scriptDir = $PSScriptRoot
    return [System.IO.Path]::GetFullPath((Join-Path $scriptDir "..\.."))
}

try {
    $projectRootResolved = Resolve-ProjectRoot -ExplicitProjectRoot $ProjectRoot
    $runtimeRoot = Join-Path $projectRootResolved "runtime"
    $nodeDir = Join-Path $runtimeRoot "node"
    $destNode = Join-Path $nodeDir "node.exe"

    $src = ""
    if ($NodeExeSource -and $NodeExeSource.Trim()) {
        $src = [System.IO.Path]::GetFullPath($NodeExeSource.Trim())
    } elseif ($env:NODE_EXE_SOURCE -and $env:NODE_EXE_SOURCE.Trim()) {
        $src = [System.IO.Path]::GetFullPath($env:NODE_EXE_SOURCE.Trim())
    } else {
        $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) {
            $src = [System.IO.Path]::GetFullPath($cmd.Source)
        }
    }

    if (-not $src -or -not (Test-Path -LiteralPath $src)) {
        throw "node.exe source not found. Pass -NodeExeSource path to node.exe, or set NODE_EXE_SOURCE, or add Node.js to PATH."
    }

    Write-Info "project_root=$projectRootResolved"
    Write-Info "node_exe_source=$src"
    Write-Info "node_exe_dest=$destNode"

    if (-not (Test-Path -LiteralPath $runtimeRoot)) {
        New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $nodeDir)) {
        New-Item -ItemType Directory -Path $nodeDir -Force | Out-Null
    }

    if ((Test-Path -LiteralPath $destNode) -and -not $Force) {
        throw "runtime/node/node.exe already exists. Use -Force to overwrite."
    }

    Copy-Item -LiteralPath $src -Destination $destNode -Force

    $ver = & $destNode --version 2>&1
    Write-Info "node_version=$ver"
    Write-Info "prepare_node_runtime_success=true"
} catch {
    Write-Error $_
    exit 1
}
