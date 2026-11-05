# ping.ps1 — 一条命令判定「DevTools 控制台到底吃不吃键、copy() 回不回得来」
#
# 为什么需要它：2026-10-29 那次"粘贴进去了但回车没执行"和"键盘根本没进控制台"
# 两种状态在屏幕上看几乎一样，我靠反复截图猜了 20 分钟。这个探针把判定收敛成
# 一次调用：往剪贴板放 copy("PING <token>")，让控制台跑一次，回读剪贴板。
#   · 剪贴板变成 PING <token>  → 通道通（粘贴、执行、copy 全链路 OK）
#   · 剪贴板没变               → 通道不通（焦点/粘贴保护/截断），别再瞎试
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File ping.ps1            # 只备货，等你手动粘
#   powershell -NoProfile -ExecutionPolicy Bypass -File ping.ps1 -Auto      # 自己尝试聚焦+粘贴+回车
#   powershell -NoProfile -ExecutionPolicy Bypass -File ping.ps1 -Wait 60   # 等更久
#
# 退出码：0 通 · 1 找不到 Edge · 9 不通（超时）

param(
    [switch]$Auto,
    [int]$Wait = 40
)

. "$PSScriptRoot\_win.ps1"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$h = Find-EdgeWindow
if ($h -eq [IntPtr]::Zero) {
    Write-Output "NO_EDGE_WINDOW: 先让用户打开 Edge 作业页"
    exit 1
}

$token = Get-Random -Minimum 100000 -Maximum 999999
# 标记在页面里现场拼接：payload 文本里刻意不含连续的 "PING <token>"，
# 否则剪贴板里躺着的 payload 会把自己判成"通道通"（第一版就是这么错的）。
$marker = "PING $token"
$payload = 'copy("PIN"+"G ' + $token + '")'
Set-Clipboard -Value $payload

Write-Output ("ping  token=" + $token + "  hwnd=" + $h)
Write-Output ("payload=" + $payload)

if ($Auto) {
    Focus-Edge $h
    Send-Combo @($VK.CTRL, $VK.SHIFT, $VK.J)
    Start-Sleep -Milliseconds 900
    Send-Combo @($VK.CTRL, $VK.A)
    Send-KeyTap $VK.DEL
    Send-Combo @($VK.CTRL, $VK.V)
    Start-Sleep -Milliseconds 800
    Send-KeyTap $VK.ENTER
    Write-Output "auto: 已聚焦控制台并尝试粘贴+回车"
} else {
    Write-Output ("请在 " + $Wait + " 秒内手动操作：F12 → 控制台 → 点提示行 → Ctrl+V → 回车")
    Write-Output "（已解除粘贴保护的话可直接粘；被拦先手动输入 allow pasting）"
}

$ok = $false
$elapsed = 0
for ($i = 0; $i -lt $Wait; $i++) {
    Start-Sleep -Seconds 1
    $elapsed = $i + 1
    $c = Get-ClipSafe 2
    if ($c -and $c.Contains($marker) -and $c -ne $payload) { $ok = $true; break }
}

if ($ok) {
    Write-Output ("PING_OK  " + $elapsed + "s  通道通：粘贴+执行+copy 回读都正常")
    exit 0
} else {
    Write-Output ("PING_FAIL  " + $Wait + "s 内没看到回写")
    Write-Output "排查顺序：① 提示行是否真的拿到焦点（点提示行，不是点输出区）"
    Write-Output "          ② 是否被 self-XSS 粘贴保护拦（手动输入 allow pasting 再粘）"
    Write-Output "          ③ 内容是否超长被截断（>8000 字符，用 make_fill_js.py 分块）"
    Write-Output "          ④ 都不行就退到「给用户脚本、用户自己粘」——这条 2026-10-29 实测最快"
    exit 9
}
