#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""api_client.py — P2 API 通道：复用浏览器 cookie 直连学习通底层接口。

核心约束（对应 SKILL.md 铁律）：
  * 「填写/暂存」与「提交」在代码层面就是两个独立子命令，提交必须显式 --confirm。
  * 只做数据通道，不做任何 UI 自动化。
  * 所有失败都打印「状态码 + 响应片段」作为证据，供 SKILL.md 路径 B 判定。

子命令：
  courses                      列出课程（含 courseId / classId / cpi）
  list      --course <name|id> 列出该课程作业（标题/状态/剩余时间/workId）
  fetch     --url <dowork_url> 拉取作业详情页，产出可供 dom_extract.py 解析的 HTML
  save      --work <id> --answers <json>
                               暂存答案（不提交）
  submit    --work <id> --confirm
                               提交答案（独立步骤，必须显式确认）

cookie 来源（按优先级）：
  1. --cookie-file <path>       JSON: {"domain": {"name": "value"}} 或 Netscape cookies.txt
  2. 环境变量 XT_COOKIE         形如 "k1=v1; k2=v2"
  3. 默认 ~/.dsh/xuexitong/cookies.json
  4. --cookie "k1=v1; k2=v2"    直接命令行传入

退出码：
  0 成功
  5 需要登录（cookie 缺失或已失效）——附状态码与跳转 URL
  6 接口返回 4xx/5xx 或空响应——附证据
  7 参数/IO 错误
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0")

BASE = "https://mooc1.chaoxing.com"
BASE_ALT = "https://mooc1-1.chaoxing.com"
BASE_API = "https://mooc1-api.chaoxing.com"

DEFAULT_COOKIE_FILE = os.path.join(os.path.expanduser("~"), ".dsh",
                                   "xuexitong", "cookies.json")
STATE_DIR = os.path.join(os.path.expanduser("~"), ".dsh", "xuexitong")
ENC_FILE = os.path.join(STATE_DIR, "enc_map.json")


# ------------------------------------------------------------------ cookie 层
def parse_cookie_string(s):
    out = {}
    for part in s.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def load_cookie_file(path):
    """支持两种格式：JSON {domain:{k:v}} 或 Netscape cookies.txt。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    raw_s = raw.lstrip()
    if raw_s.startswith("{"):
        data = json.loads(raw_s)
        flat = {}
        if all(isinstance(v, dict) for v in data.values()):
            for _dom, kv in data.items():
                flat.update(kv)
        else:
            flat = data
        return {str(k): str(v) for k, v in flat.items()}
    # Netscape 格式：domain \t flag \t path \t secure \t expiry \t name \t value
    flat = {}
    for line in raw.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) >= 7:
            flat[cols[5]] = cols[6]
    return flat


def load_cookies(args):
    if getattr(args, "cookie", None):
        return parse_cookie_string(args.cookie), "cli"
    if getattr(args, "cookie_file", None):
        return load_cookie_file(args.cookie_file), args.cookie_file
    env = os.environ.get("XT_COOKIE")
    if env:
        return parse_cookie_string(env), "env"
    if os.path.exists(DEFAULT_COOKIE_FILE):
        return load_cookie_file(DEFAULT_COOKIE_FILE), DEFAULT_COOKIE_FILE
    return {}, None


# ------------------------------------------------------------------ HTTP 层
class Resp:
    def __init__(self, status, url, body, headers):
        self.status = status
        self.url = url
        self.body = body
        self.headers = headers

    @property
    def snippet(self):
        return re.sub(r"\s+", " ", self.body or "")[:300]

    @property
    def redirected_to_login(self):
        return "passport2.chaoxing.com" in (self.url or "")


def request(url, cookies, method="GET", data=None, timeout=30, referer=None):
    """发一次请求；失败不抛，返回 Resp 或抛给调用方统一处理。"""
    body = None
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    if cookies:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    if data is not None:
        body = urllib.parse.urlencode(data, doseq=True).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Resp(r.status, r.geturl(),
                        r.read().decode("utf-8", errors="replace"), dict(r.headers))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return Resp(e.code, e.geturl() if hasattr(e, "geturl") else url, raw, {})


def robust_request(url, cookies, tries=4, **kw):
    """学习通前端节点偶发 RST，重试几次。"""
    last = None
    for i in range(tries):
        try:
            r = request(url, cookies, **kw)
            if r.status < 500:
                return r
            last = r
        except Exception as e:      # 连接被重置等
            last = e
        time.sleep(1.2 * (i + 1))
    if isinstance(last, Resp):
        return last
    raise last if last else RuntimeError("request failed")


def fail(kind, resp=None, detail=""):
    """统一的失败输出：状态码 + 响应片段，作为路径 B 的证据。"""
    payload = {"ok": False, "kind": kind}
    if resp is not None:
        payload.update({"status": resp.status, "final_url": resp.url,
                        "snippet": resp.snippet})
    if detail:
        payload["detail"] = detail
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 5 if kind == "login_required" else 6


# ------------------------------------------------------------------ 业务接口
def list_courses(cookies):
    url = f"{BASE_ALT}/visit/courselistdata"
    r = robust_request(url, cookies, method="POST", data={
        "courseType": "1", "courseFolderId": "0",
        "courseFolderSize": "-1", "digest": "_all",
    }, referer=f"{BASE_ALT}/")
    if r.redirected_to_login:
        return None, r
    if r.status >= 400 or not r.body.strip():
        return None, r

    out = []
    for chunk in r.body.split('<li class="course ')[1:]:
        cid = re.search(r'courseId="(\d+)"', chunk)
        clz = re.search(r'clazzId="(\d+)"', chunk)
        pid = re.search(r'personId="(\d+)"', chunk)
        name = re.search(r'title="([^"]{2,80})"', chunk)
        if cid and clz:
            out.append({
                "courseId": cid.group(1),
                "classId": clz.group(1),
                "cpi": pid.group(1) if pid else "",
                "name": (name.group(1) if name else "?").strip(),
            })
    return out, r


def load_enc_map():
    if os.path.exists(ENC_FILE):
        try:
            with open(ENC_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def parse_work_list(html):
    items = []
    pat = r'<li[^>]*data="([^"]*work/task[^"]*)"[^>]*aria-label="([^"]*)"(.*?)</li>'
    for m in re.finditer(pat, html, re.S):
        url, label, body = m.group(1), m.group(2), m.group(3)
        title, _, status = label.partition(";")
        rem = re.search(r"(剩余[\d小时天分钟]+)", re.sub(r"<[^>]+>", "", body))
        wid = re.search(r"workId=(\d+)", url)
        aid = re.search(r"answerId=(\d+)", url)
        items.append({
            "title": title.strip(),
            "status": status.strip() or "?",
            "remaining": rem.group(1) if rem else "",
            "workId": wid.group(1) if wid else "",
            "answerId": aid.group(1) if aid else "",
            "detail_url": urllib.parse.urljoin(BASE, url.replace("&amp;", "&")),
        })
    return items


def list_works(cookies, course_query):
    courses, r = list_courses(cookies)
    if courses is None:
        return None, r, None
    target = None
    for c in courses:
        if course_query == c["courseId"] or course_query in c["name"]:
            target = c
            break
    if target is None:
        return [], r, None

    enc = load_enc_map().get(target["courseId"])
    if not enc:
        return [], r, target      # 缺少 stuenc/enc，需要用户提供
    url = (f"{BASE}/mooc2/work/list?courseId={target['courseId']}"
           f"&classId={target['classId']}&cpi={target['cpi']}&ut=s"
           f"&stuenc={enc.get('stuenc','')}&enc={enc.get('work_enc','')}")
    rr = robust_request(url, cookies, referer=f"{BASE}/")
    if rr.redirected_to_login:
        return None, rr, target
    return parse_work_list(rr.body), rr, target


# ------------------------------------------------------------------ 子命令
def cmd_courses(args):
    cookies, src = load_cookies(args)
    if not cookies:
        return fail("login_required", detail="未找到 cookie，请先按 SKILL.md 前置条件提供")
    courses, r = list_courses(cookies)
    if courses is None:
        return fail("login_required" if r.redirected_to_login else "http_error", r)
    print(json.dumps({"ok": True, "cookie_source": src, "count": len(courses),
                      "courses": courses}, ensure_ascii=False, indent=2))
    return 0


def cmd_list(args):
    cookies, src = load_cookies(args)
    if not cookies:
        return fail("login_required", detail="未找到 cookie")
    items, r, target = list_works(cookies, args.course)
    if items is None:
        return fail("login_required" if r.redirected_to_login else "http_error", r)
    if target is None:
        return fail("course_not_found", r, f"未匹配课程：{args.course}")
    payload = {"ok": True, "cookie_source": src, "course": target,
               "count": len(items), "homework": items}
    if not items:
        payload["hint"] = ("若确实有作业，请补 stuenc/work_enc：打开课程作业页，"
                           "复制地址栏 work/list 的 stuenc 与 enc 参数，"
                           "用 seed-enc 子命令写入")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_seed_enc(args):
    os.makedirs(STATE_DIR, exist_ok=True)
    enc = load_enc_map()
    enc[str(args.course_id)] = {"stuenc": args.stuenc, "enc": args.enc,
                                "added": time.strftime("%Y-%m-%d")}
    with open(ENC_FILE, "w", encoding="utf-8") as f:
        json.dump(enc, f, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": True, "saved": ENC_FILE,
                      "course_id": args.course_id}, ensure_ascii=False))
    return 0


def cmd_fetch(args):
    """拉取作业详情 HTML，交给 dom_extract.py 解析（P1 的数据来源）。"""
    cookies, src = load_cookies(args)
    if not cookies:
        return fail("login_required", detail="未找到 cookie")
    r = robust_request(args.url, cookies, referer=f"{BASE}/")
    if r.redirected_to_login:
        return fail("login_required", r)
    if r.status >= 400:
        return fail("http_error", r)
    if not r.body.strip():
        return fail("empty_response", r)
    out = args.out or "homework_page.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.body)
    print(json.dumps({"ok": True, "status": r.status, "saved": out,
                      "bytes": len(r.body),
                      "next": f"py scripts/dom_extract.py --input {out} --out questions.json"},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_save(args):
    """暂存答案：只写入，不提交。"""
    cookies, src = load_cookies(args)
    if not cookies:
        return fail("login_required", detail="未找到 cookie")
    with open(args.answers, encoding="utf-8") as f:
        answers = json.load(f)

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "workId": args.work,
                          "answers_count": len(answers),
                          "note": "未发送任何请求（--dry-run）"},
                         ensure_ascii=False, indent=2))
        return 0

    # 学习通暂存端点：addStudentWorkNew（保留作答不提交）
    url = f"{BASE}/work/addStudentWorkNew"
    r = robust_request(url, cookies, method="POST", data=answers,
                       referer=f"{BASE}/mooc2/work/dowork?workId={args.work}")
    if r.redirected_to_login:
        return fail("login_required", r)
    if r.status >= 400:
        return fail("http_error", r)
    print(json.dumps({"ok": True, "stage": "saved_not_submitted",
                      "status": r.status, "snippet": r.snippet},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_submit(args):
    """提交：高风险，必须 --confirm 才执行。"""
    if not args.confirm:
        print(json.dumps({
            "ok": False, "kind": "confirmation_required",
            "message": "提交是不可逆的高风险操作。请确认后用 --confirm 重新执行。",
            "would_submit": args.work,
        }, ensure_ascii=False, indent=2))
        return 7

    cookies, src = load_cookies(args)
    if not cookies:
        return fail("login_required", detail="未找到 cookie")
    with open(args.answers, encoding="utf-8") as f:
        answers = json.load(f)

    url = f"{BASE}/work/addStudentWorkNew"
    payload = dict(answers)
    payload["submit"] = "true"
    r = robust_request(url, cookies, method="POST", data=payload,
                       referer=f"{BASE}/mooc2/work/dowork?workId={args.work}")
    if r.redirected_to_login:
        return fail("login_required", r)
    if r.status >= 400:
        return fail("http_error", r)
    print(json.dumps({"ok": True, "stage": "submitted", "status": r.status,
                      "snippet": r.snippet}, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description="学习通 API 数据通道（cookie 复用）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--cookie-file")
        p.add_argument("--cookie")

    p = sub.add_parser("courses"); common(p); p.set_defaults(fn=cmd_courses)

    p = sub.add_parser("list"); common(p)
    p.add_argument("--course", required=True, help="课程名片段或 courseId")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("seed-enc"); p.add_argument("--course-id", required=True)
    p.add_argument("--stuenc", required=True); p.add_argument("--enc", required=True)
    p.set_defaults(fn=cmd_seed_enc)

    p = sub.add_parser("fetch"); common(p)
    p.add_argument("--url", required=True); p.add_argument("--out")
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("save"); common(p)
    p.add_argument("--work", required=True)
    p.add_argument("--answers", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_save)

    p = sub.add_parser("submit"); common(p)
    p.add_argument("--work", required=True)
    p.add_argument("--answers", required=True)
    p.add_argument("--confirm", action="store_true",
                   help="显式确认提交（不可逆）")
    p.set_defaults(fn=cmd_submit)

    args = ap.parse_args()
    try:
        return args.fn(args)
    except FileNotFoundError as e:
        print(json.dumps({"ok": False, "kind": "io_error", "detail": str(e)},
                         ensure_ascii=False))
        return 7
    except Exception as e:
        print(json.dumps({"ok": False, "kind": "unexpected",
                          "detail": f"{type(e).__name__}: {e}"},
                         ensure_ascii=False))
        return 6


if __name__ == "__main__":
    sys.exit(main())
