# win.ps1 — Edge 标签页 / 页面文本 / 剪贴板 的 UIA 快捷操作（homework skill 配套）
#
# 目的：把「枚举标签页、切标签、整页 dump、写剪贴板」这些每次都要手写一遍的
#       UIAutomation 代码固化下来，避免每次会话重复 20 行内联脚本。
#
# 用法（Activity 以 powershell 5.1 调用；本机没装 pwsh 7）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File win.ps1 <action> [args...]
#   tabs                       列出所有 Edge 标签页（带序号，供 select-tab 用）
#   select-tab <子串>          按名字子串切换到该标签页（不用 Ctrl+Tab / Ctrl+W，避免点错）
#   url                        打印当前标签页地址
#   dump [-Out 文件]           把所有长文档(>2000字)的 TextPattern 全文写文件（默认 page_dump.txt）
#   text [-N 300]              打印当前页面开头 N 个字符（快速确认是不是目标页）
#   clip <文件>                把文件内容(UTF-8)写入剪贴板，供 DevTools 控制台 Ctrl+V
#
# 示例：
#   powershell -NoProfile -ExecutionPolicy Bypass -File win.ps1 tabs
#   powershell -NoProfile -ExecutionPolicy Bypass -File win.ps1 select-tab 作业作答
#   powershell -NoProfile -ExecutionPolicy Bypass -File win.ps1 text -N 200
#   powershell -NoProfile -ExecutionPolicy Bypass -File win.ps1 dump -Out hw_dump.txt
#   powershell -NoProfile -ExecutionPolicy Bypass -File win.ps1 clip fill.js

param(
    [Parameter(Position = 0)][string]$Action = "tabs",
    [Parameter(Position = 1)][string]$Arg1 = "",
    [int]$N = 300,
    [string]$Out = "page_dump.txt"
)

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

# Windows PowerShell 5.1 在 GBK 控制台下输出中文会乱码，强制 UTF-8
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$AE = [System.Windows.Automation.AutomationElement]
$winCond = New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, "Chrome_WidgetWin_1")
$wins = $AE::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $winCond)

function Get-EdgeWindow {
    foreach ($w in $wins) {
        if ($w.Current.Name -like "*Edge*") { return $w }
    }
    return $null
}

$win = Get-EdgeWindow
if ($null -eq $win -and $Action -ne "clip") {
    Write-Output "NO_EDGE_WINDOW"
    exit 1
}

switch ($Action) {
    "tabs" {
        $tci = New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, "EdgeTab")
        $tabs = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tci)
        $i = 0
        foreach ($t in $tabs) {
            $i++
            Write-Output ("[$i] " + $t.Current.Name)
        }
        Write-Output ("---- $i tabs ----")
    }
    "select-tab" {
        if (-not $Arg1) { Write-Output "usage: select-tab <substring>"; exit 7 }
        $tci = New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, "EdgeTab")
        $tabs = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tci)
        $hit = $null
        foreach ($t in $tabs) {
            if ($t.Current.Name -like "*$Arg1*") { $hit = $t; break }
        }
        if ($null -eq $hit) { Write-Output "TAB_NOT_FOUND: $Arg1"; exit 3 }
        $sp = $null
        if ($hit.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$sp)) {
            $sp.Select()
            Write-Output ("selected: " + $hit.Current.Name)
        } else {
            Write-Output "NO_SELECTION_PATTERN"
            exit 7
        }
    }
    "url" {
        $econd = New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, "OmniboxViewViews")
        foreach ($e in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $econd)) {
            $vp = $null
            if ($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$vp)) {
                if ($vp.Current.Value) { Write-Output $vp.Current.Value; break }
            }
        }
    }
    "text" {
        $dcond = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)
        foreach ($d in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $dcond)) {
            $tp = $null
            if ($d.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$tp)) {
                $t = $tp.DocumentRange.GetText([Math]::Min($N, 5000))
                if ($t -and $t.Trim().Length -gt 10) {
                    Write-Output ("=== DOC: " + $d.Current.Name + " ===")
                    Write-Output $t
                    break
                }
            }
        }
    }
    "dump" {
        $outList = New-Object System.Collections.Generic.List[string]
        $dcond = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)
        $cnt = 0
        foreach ($d in $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $dcond)) {
            $tp = $null
            if ($d.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$tp)) {
                $t = $tp.DocumentRange.GetText(-1)
                if ($t -and $t.Length -gt 2000) {
                    $cnt++
                    $outList.Add("########## DOC: " + $d.Current.Name + " | chars=" + $t.Length + " ##########")
                    $outList.Add($t)
                }
            }
        }
        $txt = $outList -join "`n"
        $txt | Out-File -FilePath $Out -Encoding utf8
        Write-Output ("docs=$cnt chars=" + $txt.Length + " -> " + $Out)
    }
    "clip" {
        if (-not $Arg1) { Write-Output "usage: clip <file>"; exit 7 }
        if (-not (Test-Path $Arg1)) { Write-Output "FILE_NOT_FOUND: $Arg1"; exit 7 }
        $t = [IO.File]::ReadAllText((Resolve-Path $Arg1), [Text.Encoding]::UTF8)
        Set-Clipboard -Value $t
        Write-Output ("clip chars=" + $t.Length)
    }
    default {
        Write-Output "unknown action: $Action"
        exit 7
    }
}
