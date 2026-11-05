# _win.ps1 — 窗口 / 键盘 共享工具（被 ping.ps1、send.ps1 点源引用）
#
# 为什么单独抽出来：2026-10-29 那次我为了把脚本送进控制台，临时写了
# key.ps1 / key2.ps1 / inj1.ps1 / inj2.ps1 / planb.ps1 五个脚本，每个都
# 重复一遍 Add-Type + 找窗口 + 发键。窗口句柄还被我硬编码成 1640922，
# Edge 一重启就全废。这里统一：动态找窗口 + 统一的按键函数。
#
# 用法（不要直接跑，点源引用）：
#   . "$PSScriptRoot\_win.ps1"
#   $h = Find-EdgeWindow
#   Focus-Edge $h
#   Send-Combo @($VK.CTRL, $VK.SHIFT, $VK.J)
#   Send-KeyTap $VK.ENTER

Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class HWin {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern void keybd_event(byte v, byte s, uint f, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern short VkKeyScan(char ch);
  [DllImport("user32.dll")] public static extern short VkKeyScanEx(char ch, IntPtr hkl);
}
'@

$script:VK = @{
    CTRL = 0x11; SHIFT = 0x10; ALT = 0x12
    ENTER = 0x0D; ESC = 0x1B; DEL = 0x2E; TAB = 0x09
    A = 0x41; C = 0x43; J = 0x4A; L = 0x4C; V = 0x56; F12 = 0x7B
}

function Get-HWTitle([IntPtr]$h) {
    $sb = New-Object System.Text.StringBuilder 512
    [HWin]::GetWindowText($h, $sb, 512) | Out-Null
    return $sb.ToString()
}

# 动态找 Edge 主窗口（标题像 Edge，且不是 DSH 自己的窗口）
function Find-EdgeWindow {
    $script:found = [IntPtr]::Zero
    $cb = [HWin+EnumProc] {
        param($h, $l)
        if ([HWin]::IsWindowVisible($h)) {
            $t = Get-HWTitle $h
            if ($t -like "*Edge*" -and $t -notlike "*DeepSeek*" -and $t -notlike "*DevTools*") {
                $r = New-Object System.Text.StringBuilder 256
                [HWin]::GetClassName($h, $r, 256) | Out-Null
                if ($r.ToString() -like "Chrome_WidgetWin*") {
                    $script:found = $h
                    return $false
                }
            }
        }
        return $true
    }
    [HWin]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    return $script:found
}

# 抢前台。注意：直接 SetForegroundWindow 会被 Windows 前台锁拒绝（返回 False 也不抛错），
# 于是键全打到原来的窗口上——2026-10-29 两次"注入失败"都是这个原因。
# 解法：先轻点一下 Alt，系统会把当前进程当成"用户刚操作过"，随后 SetForegroundWindow 才放行。
function Focus-Edge($h) {
    if ([HWin]::GetForegroundWindow() -ne $h) {
        Send-KeyTap $VK.ALT 40
        Start-Sleep -Milliseconds 90
    }
    [HWin]::ShowWindow($h, 9) | Out-Null          # SW_RESTORE
    [HWin]::BringWindowToTop($h) | Out-Null
    [HWin]::SetForegroundWindow($h) | Out-Null
    Start-Sleep -Milliseconds 500
    return ([HWin]::GetForegroundWindow() -eq $h)
}

function Send-KeyDown([int]$vk) { [HWin]::keybd_event([byte]$vk, 0, 0, [UIntPtr]::Zero) }
function Send-KeyUp([int]$vk)   { [HWin]::keybd_event([byte]$vk, 0, 2, [UIntPtr]::Zero) }

function Send-KeyTap([int]$vk, [int]$ms = 60) {
    Send-KeyDown $vk
    Start-Sleep -Milliseconds $ms
    Send-KeyUp $vk
    Start-Sleep -Milliseconds 40
}

# 组合键：Send-Combo @($VK.CTRL, $VK.SHIFT, $VK.J)
function Send-Combo([int[]]$keys) {
    for ($i = 0; $i -lt $keys.Length; $i++) { Send-KeyDown $keys[$i]; Start-Sleep -Milliseconds 50 }
    for ($i = $keys.Length - 1; $i -ge 0; $i--) { Send-KeyUp $keys[$i]; Start-Sleep -Milliseconds 40 }
}

function Click-At([int]$x, [int]$y) {    [HWin]::SetCursorPos($x, $y) | Out-Null
    Start-Sleep -Milliseconds 120
    [HWin]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [HWin]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 300
}

# 读回剪贴板（带重试，PowerShell 5.1 偶发 CLIPBOARD 占用）
function Get-ClipSafe([int]$retry = 5) {
    for ($i = 0; $i -lt $retry; $i++) {
        try { return (Get-Clipboard -Raw) } catch { Start-Sleep -Milliseconds 300 }
    }
    return $null
}

# 把 js 文件压成单行（与 clip.ps1 set 完全同一规则）
function Read-JsFile([string]$path) {
    $t = [IO.File]::ReadAllText((Resolve-Path $path), [Text.Encoding]::UTF8)
    $t = $t.TrimStart([char]0xFEFF)
    return ($t -replace "\r?\n", " ")
}

# 用真实按键"打字"（不是粘贴）。DevTools 的 self-XSS 保护只拦粘贴，不拦打字，
# 所以控制台是新会话时，先 Send-Text "allow pasting" + 回车，后面的 Ctrl+V 才放行。
# 只支持 ASCII（VkKeyScan 按当前键盘布局解析）。
function Send-Text([string]$s, [int]$gap = 12) {
    foreach ($ch in $s.ToCharArray()) {
        $scan = [HWin]::VkKeyScan($ch)
        if ($scan -eq -1) { continue }
        $code = $scan -band 0xFF
        $needShift = ((($scan -shr 8) -band 0x01) -ne 0)
        if ($needShift) { Send-KeyDown $VK.SHIFT; Start-Sleep -Milliseconds 15 }
        Send-KeyDown $code
        Start-Sleep -Milliseconds $gap
        Send-KeyUp $code
        if ($needShift) { Send-KeyUp $VK.SHIFT; Start-Sleep -Milliseconds 10 }
    }
    Start-Sleep -Milliseconds 60
}
