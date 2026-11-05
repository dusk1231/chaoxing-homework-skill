# send.ps1 — 把一段 js 送进 DevTools 控制台并执行（替换掉历次临时脚本）
#
# 为什么需要它：2026-10-29 那次为了"粘贴+回车"，临时写了 key.ps1 / key2.ps1 /
# inj1.ps1 / inj2.ps1 / planb.ps1 五个脚本，每个都重新 Add-Type、重新找窗口，
# 句柄还硬编码。这里一次做全：动态找窗口 → 聚焦控制台 → 清输入 → 粘贴 → 回车 → 回读。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File send.ps1 fill.js
#   powershell -NoProfile -ExecutionPolicy Bypass -File send.ps1 fill.js -X 1450 -Y 978
#   powershell -NoProfile -ExecutionPolicy Bypass -File send.ps1 fill.js -NoEnter
#
# 参数：
#   -File   要注入的 js（会被压成单行，与 clip.ps1 set 同规则）
#   -X -Y   控制台提示行坐标（可选；必须来自截图，不能猜）
#   -NoEnter 只粘贴不回车（用于先确认粘进去了）
#   -Wait   回车后等多久再回读剪贴板（毫秒，默认 2500）
#   -Max    长度上限（默认 7000；DevTools 控制台约 8000 会截断）
#
# 退出码：0 成功 · 1 找不到 Edge · 7 参数/IO · 8 脚本超长（请用 make_fill_js.py 分块）

param(
    [Parameter(Position = 0)][string]$File = "",
    [int]$X = 0,
    [int]$Y = 0,
    [switch]$NoEnter,
    [int]$Wait = 2500,
    [int]$Max = 7000
)

. "$PSScriptRoot\_win.ps1"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

if (-not $File) {
    Write-Output "usage: send.ps1 <file.js> [-X x] [-Y y] [-NoEnter]"
    exit 7
}
if (-not (Test-Path $File)) {
    Write-Output "FILE_NOT_FOUND: $File"
    exit 7
}

$t = Read-JsFile $File
if ($t.Length -gt $Max) {
    Write-Output ("TOO_LONG chars=" + $t.Length + " > " + $Max)
    Write-Output "DevTools 控制台单次粘贴约 8000 字符会被截断，超长必然语法错。"
    Write-Output "请用 make_fill_js.py 生成（默认自动分块 7000/段），再按 paste_order 逐段 send。"
    exit 8
}

$h = Find-EdgeWindow
if ($h -eq [IntPtr]::Zero) {
    Write-Output "NO_EDGE_WINDOW: 先让用户打开作业页"
    exit 1
}

Set-Clipboard -Value $t
Write-Output ("send chars=" + $t.Length + "  hwnd=" + $h + "  file=" + (Split-Path $File -Leaf))

$focused = Focus-Edge $h
if (-not $focused) {
    Write-Output "focus=FAIL(前台锁)：Edge 没拿到焦点，按键会打到别的窗口，已停止发送"
    Write-Output "处理：手动点一下 Edge 窗口（或 Alt+Tab 切过去）再重跑本命令"
    exit 1
}
Write-Output "focus=ok"
Send-Combo @($VK.CTRL, $VK.SHIFT, $VK.J)      # 聚焦/打开控制台
Start-Sleep -Milliseconds 1200

if ($X -gt 0 -and $Y -gt 0) { Click-At $X $Y }

Send-Combo @($VK.CTRL, $VK.A)
Send-KeyTap $VK.DEL
Send-Combo @($VK.CTRL, $VK.V)
Start-Sleep -Milliseconds 900

if (-not $NoEnter) { Send-KeyTap $VK.ENTER }
Start-Sleep -Milliseconds $Wait

$c = Get-ClipSafe
if ($null -eq $c) {
    Write-Output "CLIPBOARD_READ_FAIL"
    exit 0
}
Write-Output ("clip_after=" + $c.Length)
if ($c.Length -gt 0) {
    Write-Output ("head=" + $c.Substring(0, [Math]::Min(220, $c.Length)))
}
if ($c -eq $t) {
    Write-Output "note=剪贴板没变化：可能没执行（换行/焦点问题），先跑 ping.ps1 判通道"
}
exit 0
