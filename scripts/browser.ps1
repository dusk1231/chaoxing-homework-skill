<#
browser.ps1 — homework skill 的 R2 主通道：管理"专属 profile 的 Edge + 远程调试端口"。

为什么必须用专属 profile：
  Edge 136+ 起，对**默认 user-data-dir** 一律忽略 --remote-debugging-port（安全策略），
  所以想用 CDP 就必须给一个独立的 user-data-dir。顺带好处：自动化浏览器和你日常浏览的
  Edge 完全隔离，答题时不会互相抢焦点。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/browser.ps1 ensure
  powershell ... -File scripts/browser.ps1 login      # 首次：打开学习通登录页，扫码登一次
  powershell ... -File scripts/browser.ps1 status     # 探活 + 判断是否已登录
  powershell ... -File scripts/browser.ps1 stop
  powershell ... -File scripts/browser.ps1 profile    # 打印 profile / 端口 / node 路径

参数：
  -Port 9333       远程调试端口（默认 9333，与 cdp.mjs 一致）
  -ProfileDir      自定义 profile 目录（默认 %LOCALAPPDATA%\dsh-homework\edge-profile）
  -Url             打开指定页面（默认 about:blank）
  -Headless        无头模式（默认有头；扫码登录必须有头）
  -WaitSec 25      等待 CDP 就绪的秒数

退出码：0 成功 / 9 通道不通（起不来或端口没就绪）
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('ensure', 'start', 'stop', 'status', 'login', 'profile', 'doctor', 'goto')]
    [string]$Action,
    [int]$Port = 9333,
    [string]$ProfileDir = '',
    [string]$Url = '',
    [switch]$Headless,
    [int]$WaitSec = 25
)

$ErrorActionPreference = 'Stop'
# 5.1 默认按 GBK 解码子进程输出，会把 Node/Python 的 UTF-8 中文打成乱码；
# 先切 UTF8，别让用户看到一堆乱码。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillDir = Split-Path -Parent $scriptDir

if ([string]::IsNullOrWhiteSpace($ProfileDir)) {
    $ProfileDir = Join-Path $env:LOCALAPPDATA 'dsh-homework\edge-profile'
}

function Resolve-Edge {
    $cands = @(
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
    )
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}

function Resolve-Node {
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $cands = @(
        'D:\toor\ds\resources\runtime\primary-runtime\dependencies\node\bin\node.exe',
        (Join-Path $env:ProgramFiles 'nodejs\node.exe')
    )
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}

function Get-CdpStep { try { return Invoke-RestMethod "http://127.0.0.1:$Port/json/version" -TimeoutSec 3 } catch { return $null } }

function Test-CdpReady {
    $v = Get-CdpStep
    return [bool]$v
}

function Wait-Cdp([int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-CdpReady) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-ProfileProcs {
    # 只认命令行里带本次 profile 的 Edge 进程，绝不误杀用户日常浏览器
    $needle = $ProfileDir
    try {
        return @(Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -and $_.CommandLine.Contains($needle) })
    } catch {
        return @()
    }
}

function Start-AutomationEdge([string]$startUrl) {
    $exe = Resolve-Edge
    if (-not $exe) { throw 'EDGE_NOT_FOUND' }
    New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
    if ([string]::IsNullOrWhiteSpace($startUrl)) { $startUrl = 'about:blank' }
    $argList = @(
        "--user-data-dir=`"$ProfileDir`"",
        "--remote-debugging-port=$Port",
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-features=msEdgeFirstRunExperience',
        '--disable-crash-reporter',
        '--disable-session-crashed-bubble'
    )
    if ($Headless) { $argList += '--headless=new' }
    $argList += "`"$startUrl`""
    $p = Start-Process -FilePath $exe -ArgumentList ($argList -join ' ') -PassThru
    return $p
}

function Get-LoginState {
    $node = Resolve-Node
    if (-not $node) { return 'NODE_MISSING' }
    try {
        $raw = & $node (Join-Path $scriptDir 'cdp.mjs') cookies --domain chaoxing --port $Port 2>$null
        $obj = $raw | ConvertFrom-Json
        if ($obj.names -contains 'fid' -or $obj.names -contains '_uid' -or $obj.names -contains 'uf') { return 'LOGGED_IN' }
        return 'NOT_LOGGED_IN'
    } catch {
        return 'UNKNOWN'
    }
}

switch ($Action) {
    'profile' {
        $node = Resolve-Node
        Write-Output "profile   = $ProfileDir"
        Write-Output "port      = $Port"
        Write-Output "edge      = $(Resolve-Edge)"
        Write-Output "node      = $node"
        Write-Output "skill_dir = $skillDir"
        break
    }
    'doctor' {
        $exe = Resolve-Edge
        $node = Resolve-Node
        Write-Output "edge   = $exe"
        Write-Output "node   = $node"
        Write-Output "profile= $ProfileDir"
        Write-Output "procs  = $((Get-ProfileProcs | Measure-Object).Count)"
        Write-Output "cdp    = $(if (Test-CdpReady) { 'UP' } else { 'DOWN' })"
        if (-not $exe) { exit 9 }
        if (-not $node) { exit 9 }
        break
    }
    'start' {
        if (Test-CdpReady) { Write-Output "READY already port=$Port"; break }
        $startUrl = $Url
        if ([string]::IsNullOrWhiteSpace($startUrl)) { $startUrl = 'about:blank' }
        $p = Start-AutomationEdge $startUrl
        Write-Output "launched pid=$($p.Id) profile=$ProfileDir"
        if (Wait-Cdp $WaitSec) { Write-Output "READY port=$Port"; break }
        Write-Output 'FAIL cdp_not_ready'
        exit 9
    }
    'ensure' {
        if (Test-CdpReady) { Write-Output "READY already port=$Port"; break }
        if (-not (Resolve-Edge)) { Write-Output 'FAIL edge_not_found'; exit 9 }
        $p = Start-AutomationEdge $Url
        Write-Output "launched pid=$($p.Id)"
        if (Wait-Cdp $WaitSec) {
            Write-Output "READY port=$Port"
            Write-Output ("login=" + (Get-LoginState))
            break
        }
        Write-Output 'FAIL cdp_not_ready'
        exit 9
    }
    'stop' {
        $procs = Get-ProfileProcs
        if (-not $procs.Count) { Write-Output 'no automation edge running'; break }
        foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
        Start-Sleep -Milliseconds 1200
        Write-Output "stopped $(($procs | Measure-Object).Count) proc(s)"
        break
    }
    'status' {
        if (-not (Test-CdpReady)) { Write-Output "CDP_DOWN port=$Port"; exit 9 }
        $v = Get-CdpStep
        Write-Output ("CDP_UP browser=" + $v.Browser + " port=$Port")
        $node = Resolve-Node
        if ($node) {
            & $node (Join-Path $scriptDir 'cdp.mjs') targets --port $Port
        }
        Write-Output ("login=" + (Get-LoginState))
        break
    }
    'goto' {
        if ([string]::IsNullOrWhiteSpace($Url)) { Write-Output 'goto 需要 -Url'; exit 2 }
        if (-not (Test-CdpReady)) { Write-Output "FAIL cdp_down; 先跑 ensure"; exit 9 }
        $node = Resolve-Node
        & $node (Join-Path $scriptDir 'cdp.mjs') goto $Url --port $Port
        break
    }
    'login' {
        if (-not (Test-CdpReady)) {
            $p = Start-AutomationEdge 'https://passport2.chaoxing.com/login'
            if (-not (Wait-Cdp $WaitSec)) { Write-Output 'FAIL cdp_not_ready'; exit 9 }
        } else {
            $node = Resolve-Node
            & $node (Join-Path $scriptDir 'cdp.mjs') goto 'https://passport2.chaoxing.com/login' --port $Port
        }
        Write-Output 'ACTION_REQUIRED 请在弹出的自动化 Edge 窗口里用「手机号/扫码」登录学习通（只需一次，cookie 存在专属 profile 里）'
        Write-Output '登完回来跑: browser.ps1 status   （看到 login=LOGGED_IN 即可）'
        break
    }
}
