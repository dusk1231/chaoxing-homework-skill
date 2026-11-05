# clip.ps1 — 剪贴板读写（homework skill 配套）
#
# 为什么需要它：本机 Edge 的 UIA 树可能整体不可用，这时「把 JS 送进控制台」
# 和「把结果取回来」都只能靠剪贴板。约定：注入脚本最后一句必须是 copy(...)。
#
# 用法（PowerShell 5.1，本机没有 pwsh 7）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File clip.ps1 set fill.js
#   powershell -NoProfile -ExecutionPolicy Bypass -File clip.ps1 get out.txt
#   powershell -NoProfile -ExecutionPolicy Bypass -File clip.ps1 get          # 只打印
#   powershell -NoProfile -ExecutionPolicy Bypass -File clip.ps1 len          # 打印字符数
#
# 2026-10-29 起 set 会做三件事（都是踩过的坑）：
#   1) 去掉 UTF-8 BOM（PowerShell 会把 BOM 当字符串第一个字符粘进控制台）
#   2) 换行压成空格（多行粘贴会被拆开执行）
#   3) 超长 / 残留 // 行注释 时直接告警 —— 压行后 // 会吞掉后面全部代码，
#      控制台报 Uncaught SyntaxError: Unexpected end of input；单次粘贴约
#      8000 字符会被截断。超长请用 make_fill_js.py 自动分块。
#   -Max 改阈值（默认 7000）；-Strict 时超长直接 exit 8，便于脚本化拦截。
#
# 注意：clip.ps1 必须存成 UTF-8 带 BOM，否则 5.1 会按 GBK 读坏中文注释。

param(
    [Parameter(Position = 0)][string]$Action = "get",
    [Parameter(Position = 1)][string]$Arg1 = "",
    [int]$Max = 7000,
    [switch]$Strict
)

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

switch ($Action) {
    "set" {
        if (-not $Arg1) { Write-Output "usage: clip.ps1 set <file>"; exit 7 }
        if (-not (Test-Path $Arg1)) { Write-Output "FILE_NOT_FOUND: $Arg1"; exit 7 }

        $t = [IO.File]::ReadAllText((Resolve-Path $Arg1), [Text.Encoding]::UTF8)
        $t = $t.TrimStart([char]0xFEFF)
        # 多行 JS 在控制台粘贴会被拆成多段执行，统一压成一行
        $t = $t -replace "\r?\n", " "
        Set-Clipboard -Value $t
        Write-Output ("clip set chars=" + $t.Length)

        if ($t.Contains("//")) {
            Write-Output "WARN 内容里还有 // 行注释：压行后会把后面代码全部注释掉（Unexpected end of input）"
            Write-Output "     用 make_fill_js.py 生成即可（会自动剥注释），或改用 /* */ 块注释"
        }
        if ($t.Length -gt $Max) {
            Write-Output ("WARN 超长 " + $t.Length + " > " + $Max + "：控制台单次粘贴约 8000 字符会被截断")
            Write-Output "     用 make_fill_js.py 生成（默认 --max-chars 7000 自动分块），按 paste_order 逐段粘"
            if ($Strict) { exit 8 }
        }
    }
    "get" {
        $c = $null
        for ($i = 0; $i -lt 5; $i++) {
            try { $c = Get-Clipboard -Raw; break } catch { Start-Sleep -Milliseconds 300 }
        }
        if ($null -eq $c) { Write-Output "FAIL: CLIPBOARD_READ"; exit 6 }
        if ($Arg1) {
            [IO.File]::WriteAllText($Arg1, $c, [Text.Encoding]::UTF8)
            Write-Output ("clip saved chars=" + $c.Length + " -> " + $Arg1)
        } else {
            Write-Output $c
        }
    }
    "len" {
        $c = Get-Clipboard -Raw
        Write-Output ("clip chars=" + $c.Length)
    }
    default {
        Write-Output "unknown action: $Action"
        exit 7
    }
}
