# -*- coding: utf-8 -*-
"""pw_fallback.py — homework skill 的 R1 后备通道（Playwright，本机已装 1.64.1）。

它跑在**和 R2 同一个 user-data-dir** 上，所以登录态、题目页 URL 全都无缝继承；
R2 挂了切过来不用重新扫码。

用法：
  py scripts/pw_fallback.py --profile <dir> --file fill.js
  py scripts/pw_fallback.py --profile <dir> --expr "document.title"
  py scripts/pw_fallback.py --profile <dir> --goto <url> --shot page.png
  py scripts/pw_fallback.py --profile <dir> --login          # 有头打开学习通登录页
  py scripts/pw_fallback.py --profile <dir> --file fill.js --save result.txt

约定：
  · 页面里调用 copy(x) 会被劫持成"把 x 当返回值"（和 cdp.mjs 的兼容层一致），
    所以 extract_dom.js / fill.js / verify.js 不用改。
  · 默认无头；--login 时自动切有头。
  · 同一时刻**不能**有 R2 的 Edge 占着同一 profile —— 先跑 browser.ps1 stop。

退出码：0 成功 / 1 失败 / 2 用法错误 / 9 通道不通
"""
import argparse
import json
import os
import sys

WRAP = (
    "(function(){var __out=null;var copy=function(x){__out=String(x);};"
    "var __ret=(function(){ %s })();"
    "return (__out!==null)?__out:__ret;})()"
)


def die(msg, code=1):
    print("FAIL " + str(msg))
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="和 R2 相同的 user-data-dir")
    ap.add_argument("--file", help="要执行的 js 文件")
    ap.add_argument("--expr", help="直接执行表达式")
    ap.add_argument("--goto", help="先导航到这个 URL")
    ap.add_argument("--match", default="", help="只挑 URL 含该子串的标签页")
    ap.add_argument("--save", help="结果写入文件")
    ap.add_argument("--shot", help="结束时截图到该路径")
    ap.add_argument("--login", action="store_true", help="有头打开学习通登录页并停留")
    ap.add_argument("--hold", type=int, default=180, help="--login 时的停留秒数")
    ap.add_argument("--headed", action="store_true", help="有头运行")
    ap.add_argument("--timeout", type=int, default=60000)
    args = ap.parse_args()

    if not (args.file or args.expr or args.goto or args.login):
        die("至少要给 --file / --expr / --goto / --login 之一", 2)

    os.makedirs(args.profile, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        die("playwright 导入失败: %r" % (e,), 9)

    headless = not (args.headed or args.login)

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                args.profile,
                channel="msedge",
                headless=headless,
                args=["--no-first-run", "--no-default-browser-check",
                      "--disable-features=msEdgeFirstRunExperience"],
                viewport={"width": 1440, "height": 900},
            )
        except Exception as e:  # noqa: BLE001
            die("启动 Edge 失败（profile 被占用？先 browser.ps1 stop）: %r" % (e,), 9)

        try:
            page = None
            for pg in ctx.pages:
                if args.match and args.match in (pg.url or ""):
                    page = pg
            if page is None:
                page = ctx.pages[-1] if ctx.pages else ctx.new_page()

            if args.login:
                page.goto("https://passport2.chaoxing.com/login", timeout=args.timeout)
                print("ACTION_REQUIRED 在弹出的窗口里登录学习通，%d 秒后自动关闭" % args.hold)
                page.wait_for_timeout(args.hold * 1000)
                cookies = [c for c in ctx.cookies() if "chaoxing" in (c.get("domain") or "")]
                names = sorted({c["name"] for c in cookies})
                ok = any(n in names for n in ("fid", "_uid", "uf"))
                print("login=" + ("LOGGED_IN" if ok else "NOT_LOGGED_IN") + " names=" + ",".join(names))
                return

            if args.goto:
                page.goto(args.goto, wait_until="load", timeout=args.timeout)

            if args.file:
                with open(args.file, "r", encoding="utf-8-sig") as f:
                    expr = WRAP % f.read()
            elif args.expr:
                expr = args.expr
            else:
                expr = "JSON.stringify({href:location.href,title:document.title})"

            val = page.evaluate(expr)
            text = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)

            if args.save:
                with open(args.save, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text or "")
                print("SAVED %s chars=%d" % (args.save, len(text or "")))
            else:
                print(text)

            if args.shot:
                page.screenshot(path=args.shot, full_page=False)
                print("SHOT %s bytes=%d" % (args.shot, os.path.getsize(args.shot)))
        except Exception as e:  # noqa: BLE001
            die("执行失败: %r" % (e,))
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
