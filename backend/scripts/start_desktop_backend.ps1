param(
    [string]$DataRoot = "C:\ProgramData\FlyArrangement",
    [Alias("Host")]
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 18000,
    [string]$BackendApp = "app.main:app",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$script:ChildProcess = $null
$script:LogFile = $null
$script:ErrLogFile = $null
$script:CleanupDone = $false

function Write-Info {
    param([string]$Message)
    Write-Host "[desktop-backend] $Message"
}

function Write-Log {
    param([string]$Message)
    $line = "[desktop-backend] $Message"
    Write-Host $line
    if ($script:LogFile) {
        $parent = Split-Path -Parent $script:LogFile
        if ($parent -and (Test-Path -LiteralPath $parent)) {
            try {
                Add-Content -LiteralPath $script:LogFile -Value $line -Encoding utf8
            } catch {}
        }
    }
}

function Write-ErrLog {
    param([string]$Message)
    $ts = (Get-Date).ToString("o")
    $line = "[$ts] $Message"
    Write-Host $line -ForegroundColor Red
    if ($script:ErrLogFile) {
        $parent = Split-Path -Parent $script:ErrLogFile
        if ($parent -and (Test-Path -LiteralPath $parent)) {
            try {
                Add-Content -LiteralPath $script:ErrLogFile -Value $line -Encoding utf8
            } catch {}
        }
    }
}

function Write-FatalErr {
    param(
        [string]$FatalError,
        [object]$ExceptionObj = $null,
        [string]$SelectedPython = "",
        [string]$PythonVersion = ""
    )
    $cwd = ""
    try { $cwd = (Get-Location).Path } catch {}
    Write-ErrLog "fatal_error=$FatalError"
    if ($SelectedPython) { Write-ErrLog "selected_python=$SelectedPython" }
    if ($PythonVersion) { Write-ErrLog "python_version=$PythonVersion" }
    Write-ErrLog "cwd=$cwd"
    if ($ExceptionObj) {
        Write-ErrLog "exception=$($ExceptionObj | Out-String)"
        $ex = $ExceptionObj.Exception
        while ($ex) {
            if ($ex.StackTrace) { Write-ErrLog "stack=$($ex.StackTrace)" }
            $ex = $ex.InnerException
        }
        if ($ExceptionObj | Get-Member ScriptStackTrace -ErrorAction SilentlyContinue) {
            Write-ErrLog "ps_stack=$($ExceptionObj.ScriptStackTrace)"
        }
    }
}

function Test-PortInUse {
    param([string]$HostName, [int]$PortNumber)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($HostName, $PortNumber, $null, $null)
        $connected = $iar.AsyncWaitHandle.WaitOne(300)
        if (-not $connected) { return $false }
        $client.EndConnect($iar) | Out-Null
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-ChildProcessIds {
    param([int]$ParentPid)
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentPid" -ErrorAction SilentlyContinue)
    $ids = @()
    foreach ($child in $children) {
        $ids += [int]$child.ProcessId
        $ids += Get-ChildProcessIds -ParentPid ([int]$child.ProcessId)
    }
    return $ids
}

function Stop-ProcessTree {
    param([int]$RootPid)
    $all = @(Get-ChildProcessIds -ParentPid $RootPid) + @($RootPid)
    $all = $all | Select-Object -Unique
    foreach ($procId in ($all | Sort-Object -Descending)) {
        $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($p) {
            try {
                if ($p.CloseMainWindow()) { Start-Sleep -Milliseconds 400 }
            } catch {}
            if (-not $p.HasExited) {
                try { Stop-Process -Id $procId -ErrorAction SilentlyContinue } catch {}
            }
        }
    }
}

function Cleanup-ChildProcess {
    if ($script:CleanupDone) { return }
    $script:CleanupDone = $true
    if ($script:ChildProcess -and -not $script:ChildProcess.HasExited) {
        Write-Log "cleanup_start pid=$($script:ChildProcess.Id)"
        Stop-ProcessTree -RootPid $script:ChildProcess.Id
        Start-Sleep -Milliseconds 500
    }
}

function Get-PyvenvHome {
    param([string]$VenvPythonPath)
    $venvRoot = Split-Path -Parent (Split-Path -Parent $VenvPythonPath)
    $cfg = Join-Path $venvRoot "pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $cfg)) { return "" }
    foreach ($line in Get-Content -LiteralPath $cfg) {
        if ($line -match '^\s*home\s*=\s*(.+)\s*$') { return $Matches[1].Trim() }
    }
    return ""
}

function Test-VenvPortable {
    param([string]$VenvPythonPath)
    $home = Get-PyvenvHome -VenvPythonPath $VenvPythonPath
    if (-not $home) { return @{ Ok = $true; Reason = "no pyvenv.cfg or no home line" } }
    if (-not (Test-Path -LiteralPath $home)) {
        return @{ Ok = $false; Home = $home }
    }
    return @{ Ok = $true }
}

function Resolve-PythonExecutable {
    param(
        [string]$BackendRootPath,
        [string]$ResourceRootPath,
        [string]$ExplicitPythonExe
    )

    $candidatesLog = [System.Collections.Generic.List[string]]::new()

    if ($ExplicitPythonExe -and $ExplicitPythonExe.Trim()) {
        $explicit = [System.IO.Path]::GetFullPath($ExplicitPythonExe.Trim())
        if (-not (Test-Path -LiteralPath $explicit)) {
            throw "PythonExe 参数指向的文件不存在：$explicit"
        }
        $candidatesLog.Add("argument:$explicit")
        return @{ Path = $explicit; Source = "argument"; CandidatesLog = $candidatesLog }
    }

    $portableA = [System.IO.Path]::GetFullPath((Join-Path $ResourceRootPath "runtime\python\python.exe"))
    $portableB = [System.IO.Path]::GetFullPath((Join-Path $ResourceRootPath "runtime\python\Scripts\python.exe"))
    $venvRt = [System.IO.Path]::GetFullPath((Join-Path $ResourceRootPath "runtime\backend-venv\Scripts\python.exe"))
    $venvLocal = [System.IO.Path]::GetFullPath((Join-Path $BackendRootPath ".venv\Scripts\python.exe"))

    if (Test-Path -LiteralPath $portableA) {
        $candidatesLog.Add("runtime_python_root:$portableA")
        return @{ Path = $portableA; Source = "runtime_python"; CandidatesLog = $candidatesLog }
    }
    if (Test-Path -LiteralPath $portableB) {
        $candidatesLog.Add("runtime_python_scripts:$portableB")
        return @{ Path = $portableB; Source = "runtime_python"; CandidatesLog = $candidatesLog }
    }

    $candidatesLog.Add("runtime_python_missing:$portableA")
    $candidatesLog.Add("runtime_python_missing:$portableB")

    if (Test-Path -LiteralPath $venvRt) {
        $chk = Test-VenvPortable -VenvPythonPath $venvRt
        if (-not $chk.Ok) {
            $msg = "backend venv is not portable. Missing base Python: $($chk.Home). Use resources\runtime\python\python.exe instead."
            $candidatesLog.Add("runtime_backend_venv_rejected:$venvRt | $msg")
        } else {
            $candidatesLog.Add("runtime_backend_venv:$venvRt")
            return @{ Path = $venvRt; Source = "runtime_backend_venv"; CandidatesLog = $candidatesLog }
        }
    }

    if (Test-Path -LiteralPath $venvLocal) {
        $chk2 = Test-VenvPortable -VenvPythonPath $venvLocal
        if (-not $chk2.Ok) {
            $msg2 = "backend venv is not portable. Missing base Python: $($chk2.Home). Use resources\runtime\python\python.exe instead."
            $candidatesLog.Add("backend_local_venv_rejected:$venvLocal | $msg2")
        } else {
            $candidatesLog.Add("backend_venv:$venvLocal")
            return @{ Path = $venvLocal; Source = "backend_venv"; CandidatesLog = $candidatesLog }
        }
    }

    $candidatesLog.Add("system:python")
    return @{ Path = "python"; Source = "system_python"; CandidatesLog = $candidatesLog }
}

try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $backendRoot = Split-Path -Parent $scriptDir
    $projectRoot = Split-Path -Parent $backendRoot

    if ([System.IO.Path]::IsPathRooted($DataRoot)) {
        $dataRootAbs = [System.IO.Path]::GetFullPath($DataRoot)
    } else {
        $dataRootAbs = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $DataRoot))
    }

    $dataDir = Join-Path $dataRootAbs "data"
    $logDir = Join-Path $dataRootAbs "logs"
    $configDir = Join-Path $dataRootAbs "config"
    $dbFile = Join-Path $dataDir "fly_arrangement.db"
    # 启动诊断写入 backend.log（Add-Content）；uvicorn 标准输出写入 backend.uvicorn.log，避免截断覆盖。
    $bootLogFile = Join-Path $logDir "backend.log"
    $uvicornStdoutLog = Join-Path $logDir "backend.uvicorn.log"
    $errLogFile = Join-Path $logDir "backend.log.err"
    $script:LogFile = $bootLogFile
    $script:ErrLogFile = $errLogFile

    foreach ($dir in @($dataRootAbs, $dataDir, $logDir, $configDir)) {
        if (-not (Test-Path -LiteralPath $dir)) {
            [void][System.IO.Directory]::CreateDirectory($dir)
            Write-Log "created_dir=$dir"
        } else {
            Write-Log "dir_exists=$dir"
        }
    }

    $ts0 = (Get-Date).ToString("o")
    try {
        "[${ts0}] desktop_backend_session_start" | Out-File -LiteralPath $bootLogFile -Encoding utf8
    } catch {}

    if (Test-PortInUse -HostName $BindHost -PortNumber $Port) {
        throw "Port already in use: ${BindHost}:$Port. Stop the existing backend first."
    }

    $pythonResolved = Resolve-PythonExecutable -BackendRootPath $backendRoot -ResourceRootPath $projectRoot -ExplicitPythonExe $PythonExe
    $pythonPath = $pythonResolved.Path
    $pythonSource = $pythonResolved.Source
    $candidatesLine = [string]::Join(" | ", $pythonResolved.CandidatesLog)

    Write-Log "python_candidates=$candidatesLine"
    Write-Log "selected_python=$pythonPath"
    Write-Log "selected_python_source=$pythonSource"
    Write-Log "backend_root=$backendRoot"
    Write-Log "project_root=$projectRoot"
    Write-Log "app_main_target=$BackendApp"
    $initScript = Join-Path $projectRoot "backend\scripts\init_sqlite_baseline.py"
    Write-Log "init_sqlite_baseline_exists=$(Test-Path -LiteralPath $initScript)"
    Write-Log "app_main_exists=$(Test-Path -LiteralPath (Join-Path $backendRoot 'app\main.py'))"

    $dbFileForUrl = $dbFile -replace "\\", "/"
    $databaseUrl = "sqlite+aiosqlite:///$dbFileForUrl"
    $env:DATABASE_URL = $databaseUrl
    $env:API_HOST = $BindHost
    $env:API_PORT = "$Port"
    $env:LOG_DIR = $logDir

    Write-Log "data_root=$dataRootAbs"
    Write-Log "database_url=$databaseUrl"
    Write-Log "sqlite_db_path=$dbFile"
    Write-Log "api_host=$BindHost"
    Write-Log "api_port=$Port"
    Write-Log "diagnostic_log_file=$bootLogFile"
    Write-Log "uvicorn_stdout_log=$uvicornStdoutLog"
    Write-Log "err_log_file=$errLogFile"

    $pyVer = ""
    try {
        $pyVer = (& $pythonPath --version 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) { throw "python --version failed exit=$LASTEXITCODE" }
    } catch {
        Write-FatalErr -FatalError "python_executable_failed" -ExceptionObj $_ -SelectedPython $pythonPath
        throw
    }
    Write-Log "python_version=$pyVer"

    try {
        & $pythonPath -c "import uvicorn" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "uvicorn import failed" }
    } catch {
        Write-FatalErr -FatalError "uvicorn_missing" -ExceptionObj $_ -SelectedPython $pythonPath -PythonVersion $pyVer
        throw
    }

    if (-not (Test-Path -LiteralPath $initScript)) {
        Write-FatalErr -FatalError "init_sqlite_baseline_missing" -SelectedPython $pythonPath -PythonVersion $pyVer
        throw "init_sqlite_baseline.py not found: $initScript"
    }

    Write-Log "running init_sqlite_baseline.py ..."
    Set-Location -LiteralPath $projectRoot
    try {
        & $pythonPath $initScript
        if ($LASTEXITCODE -ne 0) { throw "init_sqlite_baseline exit=$LASTEXITCODE" }
    } catch {
        Write-FatalErr -FatalError "init_sqlite_baseline_failed" -ExceptionObj $_ -SelectedPython $pythonPath -PythonVersion $pyVer
        throw
    }
    Write-Log "sqlite baseline initialization completed."

    Set-Location -LiteralPath $backendRoot
    Write-Log "starting uvicorn $BackendApp on ${BindHost}:$Port ..."
    $backendErrLog = $errLogFile
    $script:ChildProcess = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList @("-m", "uvicorn", $BackendApp, "--host", $BindHost, "--port", "$Port", "--log-level", "info") `
        -WorkingDirectory $backendRoot `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $uvicornStdoutLog `
        -RedirectStandardError $backendErrLog
    Write-Log "child_pid=$($script:ChildProcess.Id) stderr_log=$backendErrLog"

    Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Cleanup-ChildProcess } | Out-Null
    try {
        Wait-Process -Id $script:ChildProcess.Id
    } finally {
        Cleanup-ChildProcess
    }
} catch {
    $selPy = if (Test-Path Variable:pythonPath) { $pythonPath } else { "" }
    $pv = if (Test-Path Variable:pyVer) { $pyVer } else { "" }
    Write-FatalErr -FatalError "start_desktop_backend_failed" -ExceptionObj $_ -SelectedPython $selPy -PythonVersion $pv
    Write-Error $_
    exit 1
}
