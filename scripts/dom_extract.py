#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dom_extract.py — P1 DOM 通道：把浏览器作业页 DOM 一次性解析成结构化题目 JSON。

设计原则（对应 SKILL.md 铁律）：
  * 只做「一次性整页提取」，绝不逐项 Click/Type。
  * 输入是一个完整的 DOM/HTML 文本（由 Windows-MCP Snapshot(use_dom=True) 拿到，
    或由 Edge CDP / 用户粘贴保存的文件提供）。
  * 输出是题目数组 + 每个输入框的稳定选择器，供后续一次性批量填值使用。

用法：
  # 从文件读取（Windows-MCP 的 use_dom 结果、或 curl/CDP 保存的 html）
  py dom_extract.py --input page.html --out questions.json

  # 从 stdin 读取（管道）
  py dom_extract.py --stdin --out questions.json

  # 只看提取摘要
  py dom_extract.py --input page.html --summary

退出码：
  0  提取成功且至少发现 1 道题
  3  输入不含题干/选项/输入框（这是 SKILL.md 路径 A 的合法失败证据，需附片段）
  4  输入文件不可读/为空
"""

import argparse
import json
import re
import sys
from html.parser import HTMLParser

# ---------------------------------------------------------------- 题目类型判定
TYPE_CHOICE = "choice"      # 单选/多选：radio/checkbox
TYPE_FILL = "fill"          # 填空：input[type=text] 或 textarea
TYPE_ESSAY = "essay"        # 简答/论述：大 textarea
TYPE_UNKNOWN = "unknown"

# 学习通作业页常见容器 class（多版本并存，按命中优先级排列）
QUESTION_BLOCK_HINTS = [
    "questionLi",       # 旧版作业页
    "TiMu",             # 新版作业页
    "mark_item",
    "question-item",
    "subject",
]
STEM_HINTS = ["mark_name", "Zy_TItle", "stem", "question-title", "timu"]
OPTION_HINTS = ["answerList", "Zy_ulTop", "option", "choice"]

# 空态/未登录的判定特征
LOGIN_MARKERS = [
    "passport2.chaoxing.com",
    "请输入手机号",
    "fanyalogin",
]
EMPTY_MARKERS = [
    "暂无作业",
    "没有作业",
    "作业已过期",
    "已完成",
]


class Node:
    """极简 DOM 节点：只保留解析所需字段。"""

    __slots__ = ("tag", "attrs", "children", "parent", "text_parts")

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children = []
        self.parent = parent
        self.text_parts = []

    # ---- 便捷属性
    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def has_class_hint(self, hints):
        cls = " ".join(self.classes)
        ident = (self.attrs.get("id") or "")
        blob = (cls + " " + ident).lower()
        return any(h.lower() in blob for h in hints)

    def text(self):
        buf = list(self.text_parts)
        for c in self.children:
            buf.append(c.text())
        return re.sub(r"\s+", " ", "".join(buf)).strip()

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def find_all(self, pred):
        return [n for n in self.walk() if pred(n)]


class TreeBuilder(HTMLParser):
    """把 HTML 构建成 Node 树；忽略 script/style 内容。"""

    VOID = {"br", "img", "input", "hr", "meta", "link", "source", "area", "base", "col"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {}, None)
        self.cur = self.root
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in self.VOID:
            self.cur = node

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in self.VOID:
            return
        # 向上回溯到匹配节点，容错处理不规范 HTML
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if self._skip_depth:
            return
        if data.strip():
            self.cur.text_parts.append(data)


def build_tree(html):
    tb = TreeBuilder()
    tb.feed(html)
    tb.close()
    return tb.root


# ---------------------------------------------------------------- 选择器生成
def css_selector(node):
    """生成尽量稳定的 CSS 选择器（优先 id / 学习通自带 name / class 链）。"""
    if node.attrs.get("id"):
        return "#" + node.attrs["id"]
    parts = []
    cur = node
    depth = 0
    while cur is not None and cur.tag != "#document" and depth < 6:
        seg = cur.tag
        if cur.attrs.get("name"):
            seg += f"[name='{cur.attrs['name']}']"
            parts.append(seg)
            break
        cls = [c for c in cur.classes if not c.startswith("js-")][:2]
        if cls:
            seg += "." + ".".join(cls)
        parts.append(seg)
        cur = cur.parent
        depth += 1
    return " > ".join(reversed(parts))


def xpath_selector(node):
    """同时给出 XPath，供 JS 注入时使用（兼容性更好）。"""
    if node.attrs.get("id"):
        return f"//*[@id='{node.attrs['id']}']"
    segs = []
    cur = node
    while cur is not None and cur.tag != "#document":
        idx = 1
        if cur.parent is not None:
            sibs = [c for c in cur.parent.children if c.tag == cur.tag]
            idx = sibs.index(cur) + 1 if cur in sibs else 1
        segs.append(f"{cur.tag}[{idx}]")
        cur = cur.parent
    return "/" + "/".join(reversed(segs))


# ---------------------------------------------------------------- 题目提取
def find_question_blocks(root):
    """找出题目容器。多套策略，命中即用。"""
    blocks = []
    seen = set()

    for hint in QUESTION_BLOCK_HINTS:
        for n in root.walk():
            if id(n) in seen:
                continue
            if n.has_class_hint([hint]) and n.tag not in ("html", "body"):
                # 容器必须含输入控件或选项列表，避免误收标题栏
                has_input = any(x.tag in ("input", "textarea") for x in n.walk())
                if has_input:
                    blocks.append(n)
                    seen.add(id(n))
        if blocks:
            return blocks

    # 兜底：以每个 input/textarea 为锚点，向上找最近的、含文本的祖先作为题目容器
    for inp in root.find_all(lambda n: n.tag in ("input", "textarea")):
        cur = inp.parent
        hops = 0
        while cur is not None and hops < 6:
            if cur.text() and len(cur.text()) > 4:
                if id(cur) not in seen:
                    blocks.append(cur)
                    seen.add(id(cur))
                break
            cur = cur.parent
            hops += 1
    return blocks


def detect_type(block):
    types = {n.attrs.get("type", "text").lower()
             for n in block.find_all(lambda x: x.tag == "input")}
    if "radio" in types:
        return TYPE_CHOICE
    if "checkbox" in types:
        return TYPE_CHOICE
    tas = block.find_all(lambda x: x.tag == "textarea")
    if tas:
        # 大 textarea 视为简答
        rows = max((int(t.attrs.get("rows", "0") or 0) for t in tas), default=0)
        return TYPE_ESSAY if rows >= 4 else TYPE_FILL
    if types & {"text", "search", ""}:
        return TYPE_FILL
    return TYPE_UNKNOWN


def extract_options(block):
    """提取选项：兼容 label 包裹、li 列表、以及 radio 的 value。"""
    opts = []

    # 1) radio/checkbox + 相邻 label 文本
    for inp in block.find_all(lambda n: n.tag == "input"
                              and n.attrs.get("type", "").lower() in ("radio", "checkbox")):
        label = ""
        # 找同父或祖父的 label
        cur = inp.parent
        for _ in range(3):
            if cur is None:
                break
            if cur.tag == "label":
                label = cur.text()
                break
            for sib in cur.children:
                if sib.tag == "label":
                    label = sib.text()
                    break
            if label:
                break
            cur = cur.parent
        opts.append({
            "value": inp.attrs.get("value", ""),
            "label": label,
            "selector": css_selector(inp),
            "xpath": xpath_selector(inp),
        })

    # 2) 无 input 的纯文本选项（部分题型由 JS 渲染成 li）
    if not opts:
        for hint in OPTION_HINTS:
            for n in block.walk():
                if n.has_class_hint([hint]) and n.tag in ("ul", "ol", "div"):
                    for li in n.children:
                        if li.tag in ("li", "div", "span") and li.text():
                            opts.append({"value": "", "label": li.text(),
                                         "selector": css_selector(li),
                                         "xpath": xpath_selector(li)})
                    if opts:
                        return opts
    return opts


def extract_stem(block):
    """题干：优先带题干 class 的节点，否则取容器内最长的一段纯文本。"""
    for hint in STEM_HINTS:
        for n in block.walk():
            if n.has_class_hint([hint]):
                t = n.text()
                if len(t) > 2:
                    return t, css_selector(n)
    # 兜底：容器全文中，去掉选项文本后最长的一行
    full = block.text()
    return full[:400], css_selector(block)


def extract_inputs(block, qtype):
    """需要填值的控件（填空/简答/以及隐藏的作答域）。"""
    out = []
    for n in block.walk():
        if n.tag == "textarea":
            out.append({"kind": "textarea", "selector": css_selector(n),
                        "xpath": xpath_selector(n), "name": n.attrs.get("name", "")})
        elif n.tag == "input":
            t = n.attrs.get("type", "text").lower()
            if t in ("text", "search", "", "hidden"):
                # hidden 常用于提交答案，单独标记
                out.append({"kind": "hidden" if t == "hidden" else "input",
                            "selector": css_selector(n),
                            "xpath": xpath_selector(n),
                            "name": n.attrs.get("name", "")})
    return out


def parse_page(html):
    """主入口：HTML → 结构化结果。"""
    root = build_tree(html)

    # 未登录 / 空态识别（作为明确的失败证据返回）
    low = html.lower()
    for m in LOGIN_MARKERS:
        if m.lower() in low:
            return {"ok": False, "reason": "login_required",
                    "evidence": html[:300]}
    for m in EMPTY_MARKERS:
        if m in html:
            return {"ok": False, "reason": "empty_or_finished",
                    "evidence": html[:300]}

    blocks = find_question_blocks(root)
    questions = []
    for i, b in enumerate(blocks, 1):
        qtype = detect_type(b)
        stem, stem_sel = extract_stem(b)
        q = {
            "index": i,
            "type": qtype,
            "stem": stem,
            "stem_selector": stem_sel,
            "options": extract_options(b) if qtype == TYPE_CHOICE else [],
            "inputs": extract_inputs(b, qtype),
            "container_selector": css_selector(b),
            "container_xpath": xpath_selector(b),
        }
        # 丢弃明显不是题目的块（无题干且无输入）
        if not q["stem"] and not q["inputs"] and not q["options"]:
            continue
        questions.append(q)

    if not questions:
        return {"ok": False, "reason": "no_questions_found",
                "evidence": re.sub(r"\s+", " ", html)[:500]}

    return {
        "ok": True,
        "count": len(questions),
        "questions": questions,
        "page_title": (root.find_all(lambda n: n.tag == "title") or [None])[0].text()
                      if root.find_all(lambda n: n.tag == "title") else "",
    }


# ---------------------------------------------------------------- 批量填值计划
def build_fill_plan(parsed, answers):
    """把「答案」映射成一次性的填值指令数组。

    answers 形如 {"1": "A", "2": "text answer", "3": ["A","C"]}
    返回的 plan 交给 js 注入脚本一次执行，避免逐项 Type。
    """
    plan = []
    for q in parsed["questions"]:
        key = str(q["index"])
        if key not in answers:
            continue
        ans = answers[key]
        if q["type"] == TYPE_CHOICE:
            want = ans if isinstance(ans, list) else [ans]
            want = [str(w).strip().upper() for w in want]
            for opt in q["options"]:
                label = (opt["label"] or "")[:1].upper()
                val = (opt["value"] or "").strip().upper()
                if label in want or val in want:
                    plan.append({"action": "check", "selector": opt["selector"],
                                 "xpath": opt["xpath"], "index": q["index"]})
        else:
            text = ans if isinstance(ans, str) else " ".join(map(str, ans))
            targets = [t for t in q["inputs"] if t["kind"] in ("input", "textarea")]
            for t in targets[:1]:
                plan.append({"action": "set_value", "selector": t["selector"],
                             "xpath": t["xpath"], "value": text, "index": q["index"]})
    return plan


def main():
    ap = argparse.ArgumentParser(description="一次性提取学习通作业页 DOM → 结构化题目")
    ap.add_argument("--input", help="HTML/DOM 文件路径")
    ap.add_argument("--stdin", action="store_true", help="从 stdin 读取")
    ap.add_argument("--out", help="输出 JSON 路径（默认 stdout）")
    ap.add_argument("--answers", help="答案 JSON（用于生成批量填值计划）")
    ap.add_argument("--summary", action="store_true", help="只打印摘要")
    args = ap.parse_args()

    if args.stdin:
        html = sys.stdin.read()
    elif args.input:
        try:
            with open(args.input, encoding="utf-8", errors="replace") as f:
                html = f.read()
        except OSError as e:
            print(json.dumps({"ok": False, "reason": "io_error", "detail": str(e)},
                             ensure_ascii=False))
            return 4
    else:
        ap.error("需要 --input 或 --stdin")

    if not html.strip():
        print(json.dumps({"ok": False, "reason": "empty_input"}, ensure_ascii=False))
        return 4

    parsed = parse_page(html)

    if parsed.get("ok") and args.answers:
        try:
            with open(args.answers, encoding="utf-8") as f:
                answers = json.load(f)
            parsed["fill_plan"] = build_fill_plan(parsed, answers)
        except Exception as e:
            parsed["fill_plan_error"] = str(e)

    if args.summary:
        if not parsed.get("ok"):
            print(f"FAIL {parsed['reason']}: {parsed.get('evidence','')[:200]}")
            return 3
        print(f"OK {parsed['count']} questions")
        for q in parsed["questions"]:
            n_opt = len(q["options"])
            print(f"  Q{q['index']} [{q['type']}] opts={n_opt} "
                  f"inputs={len(q['inputs'])} :: {q['stem'][:60]}")
        return 0

    out = json.dumps(parsed, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"written {args.out}")
    else:
        print(out)

    return 0 if parsed.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())
