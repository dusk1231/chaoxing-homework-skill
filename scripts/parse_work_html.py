#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse_work_html.py — 学习通 dowork 作业页 → 结构化题目 JSON。

输入可以是：
  * view-source 页经 UI Automation TextPattern 导出的 dump（带行号，脚本自动剥）
  * DevTools 里 `copy(document.documentElement.outerHTML)` 拿到的原始 HTML
  * api_client.py fetch 保存的 HTML

输出每题：
  {num, qid, type, qtype, stem, options:[{letter,data,text,imgs}], editor, answer_field}

用法：
  py parse_work_html.py --input page_dump.txt --out questions.json
  py parse_work_html.py --input page_dump.txt --summary
  py parse_work_html.py --input page_dump.txt --list-images
"""

import argparse
import json
import re
import sys

TYPE_FILL = "填空题"
TYPE_ESSAY = "设计题"
# 大题的各种叫法：只要页面用 textarea(id=answer<qid>) 承载，都会被结构判定兜住，
# 这里只作为无 textarea 时的兜底
ESSAY_TYPES = ("设计题", "简答题", "论述题", "编程题", "计算题", "名词解释", "材料分析", "综合题")


def strip_line_numbers(text):
    """view-source dump 每行前有 '\\t<数字>\\t' 或单独一行数字，剥掉。"""
    text = re.sub(r"(?m)^[ \t]*\d+[ \t]*\t", "", text)
    text = re.sub(r"(?m)^[ \t]*\d+[ \t]*$", "", text)
    return text


def strip_tags(html):
    s = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    s = re.sub(r"<img[^>]*>", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    s = s.replace("&amp;", "&").replace("&quot;", '"')
    s = re.sub(r"[ \t\u3000]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s)
    return s.strip()


def split_questions(html):
    """按题目块切分。兼容 analyze 到的 padBom50 questionLi 结构。"""
    marks = list(re.finditer(r'<div class="[^"]*questionLi[^"]*"', html))
    if not marks:
        # 退化：直接按 id="question\d+" 切
        marks = list(re.finditer(r'<div[^>]*id="question\d+"', html))
    blocks = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(html)
        block = html[m.start():end]
        # 最后一题的块会一直延伸到页尾（含脚本/扩展注入文本），先切掉尾巴。
        # 注意：不能切在 "<script" —— 每个填空后面紧跟一个 UEditor 初始化脚本，
        # 按 <script 切会把多空题的第二个空起全部丢掉（第5章踩过这个回归）。
        for stop in ("作业作答结尾", "</body>"):
            pos = block.find(stop, 200)
            if pos > 0:
                block = block[:pos]
        blocks.append(block)
    return blocks


def parse_block(block):
    qid_m = re.search(r'id="question(\d+)"', block)
    if not qid_m:
        return None
    qid = qid_m.group(1)

    type_m = re.search(r'typeName="([^"]+)"', block)
    qtype_m = re.search(r'id="answertype%s"[^>]*value="(\d+)"' % qid, block)
    num_m = re.search(r'aria-label="题目\s*(\d+)\.', block)

    stem_m = re.search(r'<h3[^>]*class="[^"]*mark_name[^"]*"[^>]*>(.*?)</h3>', block, re.S)
    stem_html = stem_m.group(1) if stem_m else ""
    stem_imgs = [u for u in re.findall(r'<img[^>]+src="([^"]+)"', stem_html)
                 if "spacer.gif" not in u and "word.gif" not in u]
    stem = strip_tags(stem_html)
    stem = re.sub(r"^\s*\d+\.\s*", "", stem)
    stem = re.sub(r"^\s*\((单选题|多选题|填空题|判断题|设计题)\)\s*", "", stem)

    # ---- 选项：按 answerBg 块切（单选 .answerBg / 多选可能带后缀，故用正则切）----
    options = []
    multi_span = False
    parts = re.split(r'<div class="clearfix answerBg[^"]*"', block)[1:]
    for part in parts:
        span_tag = re.search(r'<span[^>]*data="[^"]*"[^>]*>', part)
        if not span_tag:
            continue
        if "num_option_dx" in span_tag.group(0):
            multi_span = True
        span_m = re.search(r'data="([^"]*)"', span_tag.group(0))
        data = span_m.group(1)
        letter_m = re.search(r'>([A-Z])</span>', part[:span_tag.end() + 40])
        letter = letter_m.group(1) if letter_m else ""
        body_m = re.search(r'class="fl answer_p"[^>]*>(.*?)</div>', part, re.S)
        body = body_m.group(1) if body_m else ""
        imgs = [u for u in re.findall(r'<img[^>]+src="([^"]+)"', body)
                if "spacer.gif" not in u and "word.gif" not in u]
        text = strip_tags(body)
        options.append({"letter": letter, "data": data, "text": text, "imgs": imgs})

    # ---- 输入框 ----
    # 填空题可能是多空：编辑器 id 为 answerEditor<qid>1 .. answerEditor<qid>N
    editors = re.findall(r'<textarea[^>]*id="(answerEditor%s\d+)"' % qid, block)
    if not editors:
        editors = re.findall(r'<textarea[^>]*id="(answerEditor\d+)"', block)
    editor = None
    answer_field = None
    essay_m = re.search(r'<textarea[^>]*id="(answer%s)"' % qid, block)
    if essay_m:
        editor = essay_m.group(1)
    if editors and editor is None:
        editor = editors[0]
    # tiankongsize 是"空数"的权威来源
    size_m = re.search(r'name="tiankongsize%s"[^>]*value="(\d+)"' % qid, block)
    blanks = int(size_m.group(1)) if size_m else (len(editors) or (1 if editor else 0))

    hidden_m = re.search(r'id="answer%s"[^>]*name="answer%s"' % (qid, qid), block)
    if hidden_m:
        answer_field = "answer" + qid

    qtype = int(qtype_m.group(1)) if qtype_m else None
    tname = type_m.group(1) if type_m else ""

    # kind 判定优先看"结构"（有没有编辑器/选项），再看题型名，避免新题型名漏判
    multiple = ("多选" in tname) or (qtype == 1) or multi_span
    if editors:                                   # answerEditor<qid>N 存在 → 填空
        kind = "fill"
    elif editor:                                  # textarea id=answer<qid> → 大题
        kind = "essay"
    elif options and multiple:
        kind = "multi"
    elif options:
        kind = "choice"
    elif any(ESSAY_HINT in tname for ESSAY_HINT in ESSAY_TYPES) or qtype == 4:
        kind = "essay"
    else:
        kind = "choice"

    return {
        "num": int(num_m.group(1)) if num_m else None,
        "qid": qid,
        "type": tname,
        "qtype": qtype,
        "kind": kind,
        "multiple": bool(multiple),
        "stem": stem,
        "options": options,
        "editor": editor,
        "editors": editors,
        "blanks": blanks,
        "answer_field": answer_field,
    }


def parse_text(raw):
    html = strip_line_numbers(raw)
    qs = []
    for b in split_questions(html):
        q = parse_block(b)
        if q and q["num"] is not None:
            qs.append(q)
    qs.sort(key=lambda x: x["num"])
    for i, q in enumerate(qs, 1):
        if q["num"] is None:
            q["num"] = i
    return qs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="questions.json")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--list-images", action="store_true")
    ap.add_argument("--answers-template", metavar="OUT",
                    help="生成 answers.json 骨架（每题保留占位值，人工替换后即可用）")
    args = ap.parse_args()

    try:
        # utf-8-sig：win.ps1 dump / clip.ps1 get 产出的文件都带 BOM
        raw = open(args.input, encoding="utf-8-sig", errors="replace").read()
    except OSError as e:
        print(json.dumps({"ok": False, "kind": "io_error", "detail": str(e)}, ensure_ascii=False))
        return 4
    if not raw.strip():
        print(json.dumps({"ok": False, "kind": "empty"}, ensure_ascii=False))
        return 4

    qs = parse_text(raw)
    if not qs:
        snippet = re.sub(r"\s+", " ", raw)[:300]
        print(json.dumps({"ok": False, "kind": "no_questions", "evidence": snippet},
                         ensure_ascii=False, indent=1))
        return 3

    if args.list_images:
        payload = {}
        for q in qs:
            imgs = {}
            for o in q["options"]:
                if o["imgs"]:
                    imgs[o["letter"]] = o["imgs"]
            if imgs:
                payload[q["num"]] = imgs
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    if args.summary:
        for q in qs:
            opt = " ".join("%s=%s" % (o["letter"], o["data"]) for o in q["options"])
            print("%2d. %-6s %-4s %s | %s" % (
                q["num"], q["type"], q["kind"], q["stem"][:40].replace("\n", " "), opt))
            img_opts = [o["letter"] for o in q["options"] if o["imgs"]]
            if img_opts:
                print("      [图片选项] " + ",".join(img_opts))
            if q["editor"]:
                tag = "[编辑器 x%d] " % q["blanks"] if q["kind"] == "fill" and q["blanks"] > 1 else "[编辑器] "
                print("      " + tag + (", ".join(q["editors"]) or q["editor"]))
        print("---- total %d ----" % len(qs))
        return 0

    if args.answers_template:
        tpl = {}
        for q in qs:
            if q["kind"] in ("choice", "multi"):
                tpl[str(q["num"])] = ""
            elif q["kind"] == "fill":
                tpl[str(q["num"])] = "|".join([""] * max(1, q["blanks"]))
            else:
                tpl[str(q["num"])] = ""
        with open(args.answers_template, "w", encoding="utf-8") as f:
            json.dump(tpl, f, ensure_ascii=False, indent=1)
        print(json.dumps({"ok": True, "saved": args.answers_template,
                          "items": len(tpl),
                          "hint": "选择题填字母；多空填空用 a|b|c；大题填 HTML 或纯文本"},
                         ensure_ascii=False))
        return 0

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"ok": True, "count": len(qs), "questions": qs}, f,
                  ensure_ascii=False, indent=1)
    print(json.dumps({"ok": True, "count": len(qs), "saved": args.out,
                      "next": "填 answers.json 后跑 make_fill_js.py"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
