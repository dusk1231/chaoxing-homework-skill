# -*- coding: utf-8 -*-
"""fix_bom.py — 保证 .ps1 是「UTF-8 带 BOM + CRLF」。

PowerShell 5.1 读无 BOM 的 UTF-8 会当 GBK，中文注释变乱码甚至直接语法错
（2026-10-30 那次 browser.ps1 被编辑器重写成无 BOM，报 'The string is missing the terminator'）。

用法：
  py scripts/fix_bom.py <file> [more files...]
  py scripts/fix_bom.py --dir scripts          # 处理整个目录

输出每个文件的处理结果；已经合规的不动它（除了统一 CRLF）。
"""
import os
import sys


def fix(path):
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig")
    had_bom = raw[:3] == b"\xef\xbb\xbf"
    had_crlf = b"\r\n" in raw
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    new = text.encode("utf-8-sig")
    if new != raw:
        with open(path, "wb") as f:
            f.write(new)
    changes = []
    if had_bom is False:
        changes.append("bom+")
    if had_crlf is False:
        changes.append("crlf+")
    return ",".join(changes) if changes else "ok"


def main():
    argv = sys.argv[1:]
    if not argv:
        print("usage: py fix_bom.py <file>... | --dir <dir>")
        return 2
    targets = []
    if argv[0] == "--dir":
        d = argv[1]
        for name in sorted(os.listdir(d)):
            if name.lower().endswith(".ps1"):
                targets.append(os.path.join(d, name))
    else:
        targets = [a for a in argv if not a.startswith("--")]
    if not targets:
        return 2
    for t in targets:
        try:
            print("%s -> %s" % (t, fix(t)))
        except Exception as e:  # noqa: BLE001
            print("%s -> ERROR %r" % (t, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
