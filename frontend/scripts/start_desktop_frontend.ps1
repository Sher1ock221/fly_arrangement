param(
    [string]$DataRoot = "C:\ProgramData\FlyArrangement",
    [Alias("Host")]
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 13000,
    [string]$ApiBaseUrl = "http://127.0.0.1:18000",
    [string]$NodeExe = ""
)

$ErrorActionPreference = "Stop"
$script:ChildProcess = $null
$script:LogFile = $null
$script:ErrLogFile = $null
$script:CleanupDone = $false

function Write-Info {
    param([string]$Message)
    Write-Host "[desktop-frontend] $Message"
}

function Write-Log {
    param([string]$Message)
    $line = "[desktop-frontend] $Message"
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
        [string]$SelectedNode = ""
    )
    $cwd = ""
    try { $cwd = (Get-Location).Path } catch {}
    Write-ErrLog "fatal_error=$FatalError"
    if ($SelectedNode) { Write-ErrLog "selected_node=$SelectedNode" }
    try {
        if ($SelectedNode -and (Test-Path -LiteralPath $SelectedNode)) {
            $nv = (& $SelectedNode --version 2>&1 | Out-String).Trim()
            Write-ErrLog "node_version=$nv"
        }
    } catch {}
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

function Close-StandaloneLogPipes {
    if ($script:ChildProcess -is [System.Diagnostics.Process]) {
        try { $script:ChildProcess.CancelOutputRead() } catch {}
        try { $script:ChildProcess.CancelErrorRead() } catch {}
    }
    try {
        Get-EventSubscriber -ErrorAction SilentlyContinue |
            Where-Object { $_.SourceObject -eq $script:ChildProcess } |
            ForEach-Object { Unregister-Event -SubscriptionId $_.SubscriptionId -ErrorAction SilentlyContinue }
    } catch {}
    if ($script:StandaloneLogWriters) {
        try { $script:StandaloneLogWriters.Out.Flush() } catch {}
        try { $script:StandaloneLogWriters.Out.Close() } catch {}
        try { $script:StandaloneLogWriters.Err.Flush() } catch {}
        try { $script:StandaloneLogWriters.Err.Close() } catch {}
        $script:StandaloneLogWriters = $null
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
    Close-StandaloneLogPipes
}

function Resolve-NodeExecutable {
    param([string]$ResourceRootPath, [string]$ExplicitNodeExe)

    $list = [System.Collections.Generic.List[string]]::new()

    if ($ExplicitNodeExe -and $ExplicitNodeExe.Trim()) {
        $p = [System.IO.Path]::GetFullPath($ExplicitNodeExe.Trim())
        if (-not (Test-Path -LiteralPath $p)) { throw "NodeExe 参数不存在：$p" }
        $list.Add("argument:$p")
        return @{ Path = $p; Source = "argument"; CandidatesLog = $list }
    }

    if ($env:NODE_EXE_SOURCE -and $env:NODE_EXE_SOURCE.Trim()) {
        $ep = [System.IO.Path]::GetFullPath($env:NODE_EXE_SOURCE.Trim())
        $list.Add("env_NODE_EXE_SOURCE:$ep")
        if (Test-Path -LiteralPath $ep) {
            return @{ Path = $ep; Source = "env_node_exe_source"; CandidatesLog = $list }
        }
    }

    $bundled = [System.IO.Path]::GetFullPath((Join-Path $ResourceRootPath "runtime\node\node.exe"))
    $list.Add("bundled:$bundled")
    if (Test-Path -LiteralPath $bundled) {
        return @{ Path = $bundled; Source = "runtime_node"; CandidatesLog = $list }
    }

    $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        $sys = [System.IO.Path]::GetFullPath($cmd.Source)
        $list.Add("system:$sys")
        return @{ Path = $sys; Source = "system_node"; CandidatesLog = $list }
    }

    $list.Add("system:missing")
    return @{ Path = ""; Source = "none"; CandidatesLog = $list }
}

function Start-NextStandaloneWithProcessStartInfo {
    param(
        [string]$NodePath,
        [string]$StandaloneRoot,
        [string]$StdOutPath,
        [string]$StdErrPath
    )

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $NodePath
    $psi.WorkingDirectory = $StandaloneRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    # 使用相对参数，避免绝对路径中的空格进入 Arguments 字符串后被错误拆分
    $arg0 = "server.js"
    $usedArgList = $false
    if ($psi.PSObject.Properties.Match("ArgumentList").Count -gt 0) {
        try {
            [void]$psi.ArgumentList.Add($arg0)
            $usedArgList = $true
        } catch {
            $psi.Arguments = $arg0
        }
    } else {
        $psi.Arguments = $arg0
    }

    $wOut = [System.IO.StreamWriter]::new($StdOutPath, $false, [System.Text.UTF8Encoding]::new($false))
    $wErr = [System.IO.StreamWriter]::new($StdErrPath, $false, [System.Text.UTF8Encoding]::new($false))
    $script:StandaloneLogWriters = @{ Out = $wOut; Err = $wErr }

    $proc = [System.Diagnostics.Process]::new()
    $proc.EnableRaisingEvents = $true
    $proc.StartInfo = $psi

    $msgOut = $wOut
    $null = Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -MessageData $msgOut -Action {
        if ($null -ne $EventArgs.Data) {
            $EventSubscriber.MessageData.WriteLine($EventArgs.Data)
            $EventSubscriber.MessageData.Flush()
        }
    }
    $msgErr = $wErr
    $null = Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -MessageData $msgErr -Action {
        if ($null -ne $EventArgs.Data) {
            $EventSubscriber.MessageData.WriteLine($EventArgs.Data)
            $EventSubscriber.MessageData.Flush()
        }
    }

    if (-not $proc.Start()) {
        try {
            Get-EventSubscriber -ErrorAction SilentlyContinue |
                Where-Object { $_.SourceObject -eq $proc } |
                ForEach-Object { Unregister-Event -SubscriptionId $_.SubscriptionId -ErrorAction SilentlyContinue }
        } catch {}
        try { $wOut.Close() } catch {}
        try { $wErr.Close() } catch {}
        $script:StandaloneLogWriters = $null
        throw "Process.Start returned false (node standalone)"
    }
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()

    return @{
        Process     = $proc
        Arg0        = $arg0
        UsedArgList = $usedArgList
    }
}

try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $frontendRoot = Split-Path -Parent $scriptDir
    $projectRoot = Split-Path -Parent $frontendRoot

    if ([System.IO.Path]::IsPathRooted($DataRoot)) {
        $dataRootAbs = [System.IO.Path]::GetFullPath($DataRoot)
    } else {
        $dataRootAbs = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $DataRoot))
    }

    $logDir = Join-Path $dataRootAbs "logs"
    $bootLogFile = Join-Path $logDir "frontend.log"
    $nodeStdoutLog = Join-Path $logDir "frontend.server.log"
    $errLogFile = Join-Path $logDir "frontend.log.err"
    $script:LogFile = $bootLogFile
    $script:ErrLogFile = $errLogFile

    foreach ($dir in @($dataRootAbs, $logDir)) {
        if (-not (Test-Path -LiteralPath $dir)) {
            [void][System.IO.Directory]::CreateDirectory($dir)
            Write-Log "created_dir=$dir"
        } else {
            Write-Log "dir_exists=$dir"
        }
    }

    $ts0 = (Get-Date).ToString("o")
    try {
        "[${ts0}] desktop_frontend_session_start" | Out-File -LiteralPath $bootLogFile -Encoding utf8
    } catch {}

    if (Test-PortInUse -HostName $BindHost -PortNumber $Port) {
        throw "Port already in use: ${BindHost}:$Port"
    }

    $nodeResolved = Resolve-NodeExecutable -ResourceRootPath $projectRoot -ExplicitNodeExe $NodeExe
    $nodePath = $nodeResolved.Path
    Write-Log "node_candidates=$([string]::Join(' | ', $nodeResolved.CandidatesLog))"
    Write-Log "selected_node=$nodePath"
    Write-Log "selected_node_source=$($nodeResolved.Source)"
    Write-Log "frontend_root=$frontendRoot"
    Write-Log "port=$Port"
    Write-Log "api_base_url=$ApiBaseUrl"
    Write-Log "diagnostic_log_file=$bootLogFile"
    Write-Log "node_stdout_log=$nodeStdoutLog"

    $standaloneRoot = Join-Path $frontendRoot ".next\standalone"
    $serverJs = Join-Path $standaloneRoot "server.js"
    $standaloneExists = Test-Path -LiteralPath $serverJs
    Write-Log "standalone_exists=$standaloneExists"
    Write-Log "server_js=$serverJs"

    $env:NEXT_PUBLIC_API_BASE_URL = $ApiBaseUrl
    $env:NEXT_PUBLIC_API_URL = $ApiBaseUrl
    $env:PORT = "$Port"
    $env:HOSTNAME = $BindHost

    if ($standaloneExists) {
        if (-not $nodePath) {
            Write-FatalErr -FatalError "node_missing_for_standalone"
            throw "Node runtime not found. Expected resources\runtime\node\node.exe"
        }
        $nv = (& $nodePath --version 2>&1 | Out-String).Trim()
        Write-Log "node_version=$nv"

        Write-Log "starting Next.js standalone (node server.js) ..."
        $feErr = $errLogFile
        $standaloneRootFull = [System.IO.Path]::GetFullPath($standaloneRoot)
        $nodePathFull = [System.IO.Path]::GetFullPath($nodePath)

        Write-Log "process_start_mode=ProcessStartInfo"
        Write-Log "node_file_name=$nodePathFull"
        Write-Log "node_working_directory=$standaloneRootFull"

        $started = Start-NextStandaloneWithProcessStartInfo `
            -NodePath $nodePathFull `
            -StandaloneRoot $standaloneRootFull `
            -StdOutPath $nodeStdoutLog `
            -StdErrPath $feErr

        $script:ChildProcess = $started.Process
        Write-Log "node_argument_0=$($started.Arg0)"
        Write-Log "node_argv_used_argument_list=$($started.UsedArgList)"
        Write-Log "child_pid=$($script:ChildProcess.Id) stderr_log=$feErr"

        Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Cleanup-ChildProcess } | Out-Null
        try {
            Wait-Process -InputObject $script:ChildProcess
        } finally {
            Cleanup-ChildProcess
        }
        return
    }

    # --- npm fallback (development only) ---
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCmd) { $npmCmd = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $npmCmd) {
        Write-FatalErr -FatalError "npm_not_found_and_standalone_server_js_not_found"
        throw "npm not found and standalone server.js not found. Run frontend build with standalone + copy-standalone-assets, and ensure resources\runtime\node\node.exe exists."
    }
    $npmPath = $npmCmd.Source
    Write-Log "fallback=npm path=$npmPath"

    $nextBuildDir = Join-Path $frontendRoot ".next"
    if (-not (Test-Path -LiteralPath $nextBuildDir)) {
        throw "Missing frontend/.next. Run npm run build first."
    }

    Set-Location -LiteralPath $frontendRoot
    Write-Log "starting Next.js via npm (dev fallback) ..."
    $feErr2 = $errLogFile
    $script:ChildProcess = Start-Process `
        -FilePath $npmPath `
        -ArgumentList @("run", "start", "--", "-H", $BindHost, "-p", "$Port") `
        -WorkingDirectory $frontendRoot `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $nodeStdoutLog `
        -RedirectStandardError $feErr2
    Write-Log "child_pid=$($script:ChildProcess.Id) stderr_log=$feErr2"

    Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Cleanup-ChildProcess } | Out-Null
    try {
        Wait-Process -Id $script:ChildProcess.Id
    } finally {
        Cleanup-ChildProcess
    }
} catch {
    $sel = if (Test-Path Variable:nodePath) { $nodePath } else { "" }
    Write-FatalErr -FatalError "start_desktop_frontend_failed" -ExceptionObj $_ -SelectedNode $sel
    Write-Error $_
    exit 1
}
