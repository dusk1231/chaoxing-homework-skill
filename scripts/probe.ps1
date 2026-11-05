# probe.ps1 — 一次调用判定本机该走哪条通道（homework skill 配套）
#
# 为什么需要它：2026-10-27 那次，Edge 的 UIA 树整体退化，但 SKILL 里写的还是
# 「先 win.ps1 tabs」——于是把 win.ps1 的每个 action 都试了一遍，6 次往返全空。
#
# 2026-10-29 又发现一个更隐蔽的情况：probe 报 UIA_OK（因为 documents=1），
# 但 win.ps1 tabs=0、dump=0 字符 —— 树里有个空 Document，实际上半死。
# 所以现在不再只看"有没有 Document"，而是**真的去取 600 个字符的正文**：
# 取不到就当 DEAD，别再去试 dump。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File probe.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File probe.ps1 -Json    # 机器可读
#
# 判定：
#   UIA_OK    有 EdgeTab 或能取到正文 → win.ps1 tabs/select-tab/dump 可用
#   UIA_HALF  有 Document 但取不到正文 → dump 一定空，别再试；注入走 ping/send
#   UIA_DEAD  EdgeTab 与正文都没有   → win.ps1 全部失效，只用 ping/send
#   NO_EDGE_WINDOW  找不到 Edge

param([switch]$Json)

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$AE = [System.Windows.Automation.AutomationElement]
$wc = New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, "Chrome_WidgetWin_1")
$wins = $AE::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $wc)

$result = @{
    edge_window = $null
    hwnd        = $null
    pid         = $null
    nodes       = 0
    edge_tabs   = 0
    documents   = 0
    dump_chars  = 0
    console     = $false
    verdict     = "NO_EDGE_WINDOW"
    channel     = ""
}

foreach ($w in $wins) {
    $n = $w.Current.Name
    if ($n -like "*Edge*" -and $n -notlike "*DeepSeek*") {
        $result.edge_window = $n
        $result.hwnd = $w.Current.NativeWindowHandle
        $result.pid = $w.Current.ProcessId
        $all = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                          [System.Windows.Automation.Condition]::TrueCondition)
        $result.nodes = $all.Count
        $tci = New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, "EdgeTab")
        $result.edge_tabs = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tci).Count
        $dcond = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty,
                    [System.Windows.Automation.ControlType]::Document)
        $docs = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $dcond)
        $result.documents = $docs.Count

        # 真的取一次正文：能取到才算 UIA 活着（这是 2026-10-29 补的判据）
        foreach ($d in $docs) {
            try {
                $tp = $d.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
                if ($tp) {
                    $txt = $tp.DocumentRange.GetText(600)
                    if ($txt) { $result.dump_chars += $txt.Length }
                }
            } catch { }
            if ($result.dump_chars -gt 0) { break }
        }

        foreach ($e in $all) {
            if ($e.Current.ClassName -like 'cm-content*') { $result.console = $true; break }
        }
        break
    }
}

if ($null -eq $result.edge_window) {
    $result.verdict = "NO_EDGE_WINDOW"
    $result.channel = "先让用户打开 Edge 作业页"
} elseif ($result.edge_tabs -eq 0 -and $result.dump_chars -eq 0) {
    $result.verdict = "UIA_DEAD"
    $result.channel = "win.ps1 全废：用 ping.ps1 判通道 + send.ps1 / clip.ps1 注入"
} elseif ($result.dump_chars -eq 0) {
    $result.verdict = "UIA_HALF"
    $result.channel = "有 Document 但取不到正文，dump 一定是空：别看 documents 计数，直接走 ping/send"
} else {
    $result.verdict = "UIA_OK"
    $result.channel = "win.ps1 tabs/select-tab/dump 可用；注入仍推荐 send.ps1"
}

if ($Json) {
    Write-Output ($result | ConvertTo-Json -Compress)
} else {
    Write-Output ("window    = " + $result.edge_window)
    Write-Output ("hwnd      = " + $result.hwnd + "  pid=" + $result.pid)
    Write-Output ("nodes     = " + $result.nodes + "  edgeTabs=" + $result.edge_tabs + "  documents=" + $result.documents + "  dumpChars=" + $result.dump_chars)
    Write-Output ("console   = " + $result.console)
    Write-Output ("VERDICT   = " + $result.verdict)
    Write-Output ("CHANNEL   = " + $result.channel)
}
if ($result.verdict -eq "NO_EDGE_WINDOW") { exit 1 }
exit 0
