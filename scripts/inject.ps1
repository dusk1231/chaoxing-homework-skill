# inject.ps1 — 一条命令完成「Edge 前台 → 确保 DevTools 控制台 → 粘贴 → 回车 → 回收结果」
#
# 为什么需要它：第5章那次，光「把 JS 注入页面」就花了 20+ 分钟，
#   因为 F12 会跟着系统焦点跑到别的窗口、控制台输入框要先点再粘、
#   结果还要再单独一次调用去读。每一步都是一次往返。
#   把整串动作收进一个脚本后，注入只剩 1 次工具调用。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File inject.ps1 -File fill.js
#   powershell -NoProfile -ExecutionPolicy Bypass -File inject.ps1 -File verify.js -Timeout 40
#
# 输出：控制台里匹配 ^(done|VERIFY) 的结果行；失败时打印诊断。

param(
    [Parameter(Mandatory = $true)][string]$File,
    [int]$Timeout = 25,
    # 注意：DevTools 控制台把返回值渲染成带单引号的字符串（'done 1:ok ...'），
    # 用 ^ 锚定会永远匹配不上 —— 第3、5章都在这上面白等过。
    [string]$ResultPattern = '(done|VERIFY)'
)

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

$sig = @'
using System;
using System.Runtime.InteropServices;
public class W32B {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@
if (-not ("W32B" -as [type])) { Add-Type -TypeDefinition $sig }

function Get-EdgeWindow {
    $AE = [System.Windows.Automation.AutomationElement]
    $wc = New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, "Chrome_WidgetWin_1")
    $wins = $AE::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $wc)
    foreach ($w in $wins) {
        if ($w.Current.Name -like "*Edge*" -and $w.Current.Name -notlike "*DevTools*") { return $w }
    }
    return $null
}

function Find-ConsolePrompt($win) {
    $all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                        [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($e in $all) {
        $c = $e.Current
        if ($c.ControlType.ProgrammaticName -ne 'ControlType.Edit') { continue }
        if ($c.ClassName -like 'cm-content*' -or $c.Name -match '控制台提示|Console prompt') {
            return $e
        }
    }
    return $null
}

function Find-ConsoleTab($win) {
    $all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                        [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($e in $all) {
        $c = $e.Current
        if ($c.ControlType.ProgrammaticName -eq 'ControlType.TabItem' -and $c.Name -match '^控制台$|^Console$') {
            return $e
        }
    }
    return $null
}

$win = Get-EdgeWindow
if ($null -eq $win) { Write-Output "FAIL: NO_EDGE_WINDOW"; exit 1 }

# 1) 还原 + 置前
$h = [IntPtr]$win.Current.NativeWindowHandle
[void][W32B]::ShowWindow($h, 9)
Start-Sleep -Milliseconds 300
[void][W32B]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 400

# 2) 找控制台输入框；没有就开 DevTools；还不行就点「控制台」页签
$prompt = Find-ConsolePrompt $win
if ($null -eq $prompt) {
    [System.Windows.Forms.SendKeys]::SendWait("{F12}")
    Start-Sleep -Milliseconds 1800
    $win = Get-EdgeWindow
    $prompt = Find-ConsolePrompt $win
}
if ($null -eq $prompt) {
    $tab = Find-ConsoleTab $win
    if ($null -ne $tab) {
        $sp = $null
        if ($tab.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$sp)) { $sp.Select() }
        Start-Sleep -Milliseconds 800
        $prompt = Find-ConsolePrompt $win
    }
}
if ($null -eq $prompt) { Write-Output "FAIL: NO_CONSOLE_PROMPT（DevTools 没开或不在控制台页签）"; exit 3 }

# 3) 写剪贴板
if (-not (Test-Path $File)) { Write-Output "FAIL: FILE_NOT_FOUND $File"; exit 7 }
$js = [IO.File]::ReadAllText((Resolve-Path $File), [Text.Encoding]::UTF8)
Set-Clipboard -Value $js

# 4) 聚焦 → 粘贴 → 回车
try { $prompt.SetFocus() } catch { }
Start-Sleep -Milliseconds 250
[System.Windows.Forms.SendKeys]::SendWait("^v")
Start-Sleep -Milliseconds 600
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")

# 5) 等结果
$deadline = (Get-Date).AddSeconds($Timeout)
$result = $null
$before = 0
# 控制台里可能残留历史输出，先数一遍，之后只认"新增"的最后一条
$win0 = Get-EdgeWindow
if ($null -ne $win0) {
    $all0 = $win0.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                          [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($e0 in $all0) {
        $c0 = $e0.Current
        if ($c0.ControlType.ProgrammaticName -in @('ControlType.Text', 'ControlType.Edit') -and $c0.Name -match $ResultPattern) { $before++ }
    }
}
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 600
    $win = Get-EdgeWindow
    if ($null -eq $win) { continue }
    $all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                        [System.Windows.Automation.Condition]::TrueCondition)
    $hits = New-Object System.Collections.Generic.List[string]
    foreach ($e in $all) {
        $c = $e.Current
        if ($c.ControlType.ProgrammaticName -in @('ControlType.Text', 'ControlType.Edit')) {
            if ($c.Name -and $c.Name -match $ResultPattern) { $hits.Add($c.Name) }
        }
    }
    if ($hits.Count -gt $before) {
        $result = $hits[$hits.Count - 1]   # 取最新一条
        break
    }
}

if ($result) {
    Write-Output ("OK: " + $result)
    exit 0
} else {
    Write-Output ("FAIL: NO_RESULT within ${Timeout}s（可能被 DevTools 粘贴保护拦下，或脚本报错）")
    exit 6
}
