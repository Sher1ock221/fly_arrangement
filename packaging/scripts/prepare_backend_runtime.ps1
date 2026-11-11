<#
.SYNOPSIS
  准备桌面安装包用的便携 Python（方案 A1：完整 Windows Python 安装目录镜像到 runtime/python）。

.DESCRIPTION
  - A1（默认）：将含 python.exe、DLLs、Lib 等的 Python 3.11 根目录 robocopy 到 runtime/python，
    再用 pip 将 backend 依赖安装到该树内的 Lib/site-packages。安装包内不再依赖 pyvenv 的 home 路径。
  - A2（备选）：可使用官方 embeddable 包，解压后改 python311._pth 启用 import site，再 pip install --target Lib\site-packages；
    本仓库当前实现为 A1，便于与现有 wheels/扩展兼容。

  构建安装包前在开发机执行（可指定 -PortablePythonSource 或设置 PORTABLE_PYTHON_HOME）：
    powershell -ExecutionPolicy Bypass -File .\packaging\scripts\prepare_backend_runtime.ps1 -Force
#>
param(
    [string]$PortablePythonSource = "",
    [switch]$Force,
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[prepare-backend-runtime] $Message"
}

function Resolve-ProjectRoot {
    param([string]$ExplicitProjectRoot)
    if ($ExplicitProjectRoot -and $ExplicitProjectRoot.Trim()) {
        return [System.IO.Path]::GetFullPath($ExplicitProjectRoot)
    }
    $scriptDir = $PSScriptRoot
    return [System.IO.Path]::GetFullPath((Join-Path $scriptDir "..\.."))
}

function Read-PyvenvHome {
    param([string]$PyvenvCfgPath)
    if (-not (Test-Path -LiteralPath $PyvenvCfgPath)) {
        return ""
    }
    foreach ($line in Get-Content -LiteralPath $PyvenvCfgPath) {
        if ($line -match '^\s*home\s*=\s*(.+)\s*$') {
            return $Matches[1].Trim()
        }
    }
    return ""
}

function Resolve-PortablePythonSource {
    param(
        [string]$Explicit,
        [string]$ProjectRootResolved
    )
    if ($Explicit -and $Explicit.Trim()) {
        $p = [System.IO.Path]::GetFullPath($Explicit.Trim())
        if (-not (Test-Path -LiteralPath $p)) {
            throw "PortablePythonSource does not exist: $p"
        }
        return $p
    }
    $envSrc = [string]$env:PORTABLE_PYTHON_HOME
    if ($envSrc -and $envSrc.Trim()) {
        $p = [System.IO.Path]::GetFullPath($envSrc.Trim())
        if (Test-Path -LiteralPath $p) {
            return $p
        }
    }
    $cfg = Join-Path $ProjectRootResolved "runtime\backend-venv\pyvenv.cfg"
    $home = Read-PyvenvHome -PyvenvCfgPath $cfg
    if ($home -and (Test-Path -LiteralPath $home)) {
        Write-Info "using_home_from_pyvenv_cfg=$home"
        return [System.IO.Path]::GetFullPath($home)
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311"),
        (Join-Path ${env:ProgramFiles(x86)} "Python311-32"),
        (Join-Path $env:ProgramFiles "Python311")
    )
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        $exe = Join-Path $c "python.exe"
        if (Test-Path -LiteralPath $exe) {
            Write-Info "using_candidate_python_root=$c"
            return [System.IO.Path]::GetFullPath($c)
        }
    }
    throw @"
Could not resolve base Python directory for portable copy.
Pass -PortablePythonSource 'C:\Path\To\Python311' (folder containing python.exe, Lib, DLLs),
or set environment variable PORTABLE_PYTHON_HOME,
or ensure runtime\backend-venv\pyvenv.cfg has a valid 'home = ...' path.
"@
}

function Invoke-RobocopyMirror {
    param([string]$Source, [string]$Dest)
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "robocopy source missing: $Source"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Source "python.exe"))) {
        throw "robocopy source has no python.exe: $Source"
    }
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    $args = @($Source, $Dest, "/MIR", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS")
    Write-Info "robocopy $($args -join ' ')"
    & robocopy @args
    $code = $LASTEXITCODE
    if ($code -ge 8) {
        throw "robocopy failed exit_code=$code"
    }
}

function Invoke-Step {
    param([string]$Exe, [string[]]$CmdArgs, [string]$StepName)
    Write-Info "${StepName}: $Exe $($CmdArgs -join ' ')"
    & $Exe @CmdArgs
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed, exit_code=$LASTEXITCODE"
    }
}

try {
    $projectRootResolved = Resolve-ProjectRoot -ExplicitProjectRoot $ProjectRoot
    $runtimeRoot = Join-Path $projectRootResolved "runtime"
    $destPythonRoot = Join-Path $runtimeRoot "python"
    $destPython = Join-Path $destPythonRoot "Scripts\python.exe"
    $destPythonAlt = Join-Path $destPythonRoot "python.exe"
    $requirementsPath = Join-Path $projectRootResolved "backend\requirements.txt"

    if (-not (Test-Path -LiteralPath $requirementsPath)) {
        throw "Requirements file not found: $requirementsPath"
    }

    $sourceRoot = Resolve-PortablePythonSource -Explicit $PortablePythonSource -ProjectRootResolved $projectRootResolved
    Write-Info "project_root=$projectRootResolved"
    Write-Info "portable_python_source=$sourceRoot"
    Write-Info "portable_python_dest=$destPythonRoot"

    if (Test-Path -LiteralPath $destPythonRoot) {
        if (-not $Force) {
            throw "runtime/python already exists: $destPythonRoot. Use -Force to rebuild."
        }
        Write-Info "force_rebuild=true removing runtime/python ..."
        Remove-Item -LiteralPath $destPythonRoot -Recurse -Force
    }

    if (-not (Test-Path -LiteralPath $runtimeRoot)) {
        New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    }

    Invoke-RobocopyMirror -Source $sourceRoot -Dest $destPythonRoot

    $pyExe = $null
    if (Test-Path -LiteralPath $destPython) {
        $pyExe = $destPython
    } elseif (Test-Path -LiteralPath $destPythonAlt) {
        $pyExe = $destPythonAlt
    } else {
        throw "After robocopy, python.exe not found under $destPythonRoot"
    }

    Write-Info "portable_python_exe=$pyExe"
    $ver = & $pyExe --version 2>&1
    Write-Info "portable_python_version=$ver"

    Invoke-Step -Exe $pyExe -CmdArgs @("-m", "pip", "install", "--upgrade", "pip") -StepName "upgrade_pip"
    Invoke-Step -Exe $pyExe -CmdArgs @("-m", "pip", "install", "-r", $requirementsPath) -StepName "install_requirements"

    Write-Info "verifying_imports=fastapi,uvicorn,sqlalchemy,aiosqlite,pydantic"
    Invoke-Step -Exe $pyExe -CmdArgs @(
        "-c", "import fastapi, uvicorn, sqlalchemy, aiosqlite, pydantic; print('portable python deps ok')"
    ) -StepName "verify_imports"

    $backendMain = Join-Path $projectRootResolved "backend\app\main.py"
    if (-not (Test-Path -LiteralPath $backendMain)) {
        throw "backend app/main.py missing: $backendMain"
    }
    Push-Location -LiteralPath $projectRootResolved
    try {
        Invoke-Step -Exe $pyExe -CmdArgs @(
            "-c", "import sys; sys.path.insert(0, 'backend'); import app.main; print('backend import ok')"
        ) -StepName "verify_backend_import"
    } finally {
        Pop-Location
    }

    Write-Info "runtime_prepare_success=true"
    Write-Info "next=start_desktop_backend.ps1 prefers resources/runtime/python/python.exe (or Scripts/python.exe)"
} catch {
    Write-Error $_
    exit 1
}
