#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_fill_js.py — questions.json + answers.json → 一次性注入脚本。

用法：
  py make_fill_js.py --questions questions.json --answers answers.json --out fill.js
  py make_fill_js.py --questions questions.json --answers answers.json --out verify.js --verify

answers.json 的 key 可以是题号，也可以是 qid：
  { "1": "D", "2": "B", "19": "深度优先", "20": "对", "26": "<p>...</p>" }
  { "406342253": "D", ... }            # 也认
选择题填的是「页面 [data] 的真实选项值」（不是显示字母）；
多选写 "A,D"；判断题写 对/错、A/B、true/false；填空多空用 "a|b"。

———— 2026-10-29 修复（这两个坑各浪费了 20 分钟，别再踩）————
1) 旧模板里带 // 行注释，而 clip.ps1 会把换行压成空格 → 压行后第一条注释
   吞掉后面所有代码，控制台报 Uncaught SyntaxError: Unexpected end of input。
   现在输出前强制剥掉行注释（quote-aware，不误伤字符串里的 //）。
2) DevTools 控制台单次粘贴会被截断（实测约 8000 字符），超长脚本必然语法错。
   现在默认 --max-chars 7000，超长自动拆成：
     fill.js            ← 第 1 段（含 window.__PLAN 初始化）
     fill_p2.js ...     ← 后续 concat 段
     fill_pN.js         ← 执行器（最后粘这一段）
   逐段「Ctrl+V + 回车」即可，每段都远低于截断线。
"""

import argparse
import json
import os
import sys

TRUE_TOKENS = {"对", "正确", "是", "true", "t", "√", "1"}
FALSE_TOKENS = {"错", "错误", "否", "false", "f", "×", "0"}
DEFAULT_MAX_CHARS = 7000


def norm_tokens(raw):
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    for sep in ["，", ",", "、", ";", "；", "/", " ", "|"]:
        s = s.replace(sep, ",")
    return [t.strip() for t in s.split(",") if t.strip()]


def resolve_choice(q, raw):
    """把用户写的答案映射成页面 data 值。返回 (datas, error)"""
    tokens = norm_tokens(raw)
    datas = []
    for tok in tokens:
        hit = None
        up = tok.upper()
        for o in q["options"]:
            if o["data"] == tok:
                hit = o["data"]
                break
        if hit is None and len(tok) == 1:
            for o in q["options"]:
                if o["letter"].upper() == up:
                    hit = o["data"]
                    break
        if hit is None:
            for o in q["options"]:
                if o["text"] and (o["text"] == tok or o["text"].startswith(tok)):
                    hit = o["data"]
                    break
        if hit is None and q["type"] == "判断题":
            datas_alphabet = [o["data"] for o in q["options"]]
            if set(datas_alphabet) == {"true", "false"}:
                if tok in TRUE_TOKENS:
                    hit = "true"
                elif tok in FALSE_TOKENS:
                    hit = "false"
        if hit is None:
            return [], "无法映射答案 %r（可选 data: %s / 字母: %s）" % (
                tok,
                [o["data"] for o in q["options"]],
                [o["letter"] for o in q["options"]])
        datas.append(hit)
    return datas, None


def build_plan(questions, answers):
    """answers 的 key 支持题号或 qid。返回 (plan, errors)"""
    by_num = {str(q["num"]): q for q in questions}
    by_qid = {str(q["qid"]): q for q in questions}
    plan = []
    errors = []
    for key, raw in answers.items():
        key = str(key).strip()
        q = by_qid.get(key) or by_num.get(key)
        if q is None:
            errors.append("answers 里的 %s 找不到对应题目" % key)
            continue
        if q["kind"] in ("choice", "multi"):
            datas, err = resolve_choice(q, raw)
            if err:
                errors.append("第%s题：%s" % (q["num"], err))
                continue
            plan.append({"num": q["num"], "qid": q["qid"], "kind": "choice",
                         "multi": bool(q.get("multiple")) or len(datas) > 1,
                         "datas": datas})
        elif q["kind"] == "fill":
            editors = q.get("editors") or ([q["editor"]] if q.get("editor") else [])
            if not editors:
                errors.append("第%s题：未找到填空编辑器 id" % q["num"])
                continue
            n = q.get("blanks") or len(editors)
            if len(editors) != n:
                errors.append("第%s题：页面有 %d 个空，但只解析到 %d 个编辑器 %s —— 解析失败，"
                              "不要硬填（检查是否在 <script 处切断了题目块）"
                              % (q["num"], n, len(editors), editors))
                continue
            if isinstance(raw, (list, tuple)):
                texts = [str(x) for x in raw]
            else:
                s = str(raw)
                texts = [t.strip() for t in s.split("|")] if n > 1 else [s]
            if len(texts) != n:
                errors.append("第%s题有 %d 个空，answers 给了 %d 个（多空请用 list 或 'a|b|c'）"
                              % (q["num"], n, len(texts)))
                continue
            plan.append({"num": q["num"], "qid": q["qid"], "kind": "fill",
                         "editors": editors, "texts": texts})
        else:  # essay
            if not q.get("editor"):
                errors.append("第%s题：未找到设计题编辑器 id" % q["num"])
                continue
            content = str(raw)
            if "<" not in content:
                content = content.replace("&", "&amp;").replace("<", "&lt;")
                content = "".join("<p>%s</p>" % ln for ln in content.split("\n") if ln.strip())
            plan.append({"num": q["num"], "qid": q["qid"], "kind": "essay",
                         "editors": [q["editor"]], "html": content})
    plan.sort(key=lambda x: x["num"])
    return plan, errors


def strip_line_comments(js):
    """剥掉 // 行注释；跳过 '...' "..." `...` 字符串内部。"""
    out = []
    i = 0
    n = len(js)
    quote = None
    while i < n:
        c = js[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(js[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "/":
            j = js.find("\n", i)
            if j < 0:
                break
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def flatten(js):
    """注释剥掉后压成单行（clip.ps1 也会压，这里先压好，输出即所见）。"""
    js = js.lstrip("\ufeff")
    lines = [ln.strip() for ln in strip_line_comments(js).splitlines()]
    return " ".join(ln for ln in lines if ln)


FILL_RUNNER = """
(function(){
var P=window.__PLAN||[],log=[];
function fe(q){return document.querySelectorAll('.answerBg[qid="'+q+'"], .answerBgDx[qid="'+q+'"]');}
function ck(e){var a=e.querySelector('.num_option'),b=e.querySelector('.num_option_dx');
return !!((a&&a.className.indexOf('check_answer')>=0)||(b&&b.className.indexOf('check_answer_dx')>=0));}
function pick(p){
 var els=fe(p.qid);
 if(!els.length){log.push(p.num+':NO_ELEMENT');return;}
 var want=p.datas||[],got=0,i,s;
 if(!p.multi){
  for(i=0;i<els.length;i++){
   s=els[i].querySelector('[data]');
   if(s&&want.indexOf(s.getAttribute('data'))<0&&ck(els[i])){
    if(typeof addChoice==='function'){addChoice(els[i]);}else{els[i].click();}
   }
  }
 }
 for(i=0;i<els.length;i++){
  s=els[i].querySelector('[data]');
  if(!s){continue;}
  if(want.indexOf(s.getAttribute('data'))<0){continue;}
  if(ck(els[i])){got++;continue;}
  if(p.multi&&typeof addMultipleChoice==='function'){addMultipleChoice(els[i]);}
  else if(typeof addChoice==='function'){addChoice(els[i]);}
  else{els[i].click();}
  got++;
 }
 var h=document.getElementById('answer'+p.qid);
 var hv=h?(h.value||'(空)'):'NO_HIDDEN';
 log.push(p.num+':'+(got===want.length?'ok':'PARTIAL('+got+'/'+want.length+')')+'/h='+hv);
}
function setEds(p){
 var eds=p.editors||[p.editor],contents=p.texts||[p.html],bad=[];
 for(var k=0;k<eds.length;k++){
  try{
   if(typeof UE==='undefined'||!UE.getEditor){bad.push('NO_UE');break;}
   var ed=UE.getEditor(eds[k]);
   if(!ed){bad.push('NO_EDITOR('+eds[k]+')');continue;}
   ed.setContent(contents[k]);
  }catch(e){bad.push('ERR('+e.message+')');}
 }
 log.push(p.num+':'+(bad.length?'FAIL['+bad.join(';')+']':'ok'));
}
for(var i=0;i<P.length;i++){
 var p=P[i];
 if(p.kind==='choice'){pick(p);}else{setEds(p);}
}
var msg='done '+log.join(' ');
try{copy(msg);}catch(e){}
return msg;
})()
"""

VERIFY_RUNNER = """
(function(){
var P=window.__PLAN||[],out=[];
function fe(q){return document.querySelectorAll('.answerBg[qid="'+q+'"], .answerBgDx[qid="'+q+'"]');}
function ck(e){var a=e.querySelector('.num_option'),b=e.querySelector('.num_option_dx');
return !!((a&&a.className.indexOf('check_answer')>=0)||(b&&b.className.indexOf('check_answer_dx')>=0));}
for(var i=0;i<P.length;i++){
 var p=P[i],v='';
 try{
  if(p.kind==='choice'){
   var els=fe(p.qid),sel=[];
   for(var j=0;j<els.length;j++){
    if(ck(els[j])){var s=els[j].querySelector('[data]');sel.push(s?s.getAttribute('data'):'?');}
   }
   v=sel.join(',')||'(空)';
   var hid=document.getElementById('answer'+p.qid);
   if(hid){v+=' [hidden='+(hid.value||'(空)')+']';}
  }else{
   var eds=p.editors||[p.editor],parts=[];
   for(var k=0;k<eds.length;k++){
    var ed=(typeof UE!=='undefined'&&UE.getEditor)?UE.getEditor(eds[k]):null;
    parts.push('len='+String(ed?ed.getContent():'').length);
   }
   v=parts.join(',');
  }
 }catch(e){v='ERR:'+e.message;}
 out.push(p.num+'='+v);
}
var msg='VERIFY '+out.join(' | ');
try{copy(msg);}catch(e){}
return msg;
})()
"""


def pack(plan, budget):
    """按 JSON 长度把 plan 切成若干段，每段序列化后不超过 budget。"""
    groups, cur, size = [], [], 0
    for p in plan:
        s = len(json.dumps(p, ensure_ascii=False)) + 2
        if cur and size + s > budget:
            groups.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += s
    if cur:
        groups.append(cur)
    return groups


def build_outputs(plan, verify, out_path, max_chars):
    """返回 (files, mode)。files = [(path, js, role)]"""
    runner = flatten(VERIFY_RUNNER if verify else FILL_RUNNER)
    whole = "void(window.__PLAN=" + json.dumps(plan, ensure_ascii=False) + ");" + runner
    if len(whole) <= max_chars:
        return [(out_path, whole, "all")], "single"

    stem, ext = os.path.splitext(out_path)
    if not ext:
        stem, ext = out_path, ".js"
    budget = max_chars - len(runner) - 80
    if budget < 400:
        budget = 400
    groups = pack(plan, budget)
    files = []
    for i, g in enumerate(groups):
        if i == 0:
            js = "void(window.__PLAN=" + json.dumps(g, ensure_ascii=False) + ");"
        else:
            js = "void(window.__PLAN=window.__PLAN.concat(" + json.dumps(g, ensure_ascii=False) + "));"
        name = "%s%s" % (stem, ext) if i == 0 else "%s_p%d%s" % (stem, i + 1, ext)
        files.append((name, js, "part%d" % (i + 1)))
    last = "%s_p%d%s" % (stem, len(groups) + 1, ext)
    files.append((last, runner, "runner"))
    return files, "chunked"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True)
    ap.add_argument("--answers", required=True)
    ap.add_argument("--out", default="fill.js")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                    help="单次粘贴上限（默认 7000；DevTools 控制台约 8000 会截断）")
    args = ap.parse_args()

    try:
        qdata = json.load(open(args.questions, encoding="utf-8-sig"))
        answers = json.load(open(args.answers, encoding="utf-8-sig"))
    except OSError as e:
        print(json.dumps({"ok": False, "kind": "io_error", "detail": str(e)}, ensure_ascii=False))
        return 7
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "kind": "bad_json", "detail": str(e)}, ensure_ascii=False))
        return 7

    questions = qdata.get("questions", qdata if isinstance(qdata, list) else [])
    if not questions:
        print(json.dumps({"ok": False, "kind": "no_questions"}, ensure_ascii=False))
        return 3

    plan, errors = build_plan(questions, answers)
    if errors:
        print(json.dumps({"ok": False, "kind": "unresolved_answers", "errors": errors},
                         ensure_ascii=False, indent=1))
        return 7

    covered = {p["num"] for p in plan}
    missing = [q["num"] for q in questions if q["num"] not in covered]
    if missing:
        print(json.dumps({"ok": False, "kind": "missing_answers",
                          "missing": missing,
                          "detail": "这些题没有答案，会被整题跳过；确认是否漏答"},
                         ensure_ascii=False, indent=1))
        return 7

    files, mode = build_outputs(plan, args.verify, args.out, args.max_chars)
    manifest = []
    for path, js, role in files:
        if "\n" in js or "//" in js:
            print(json.dumps({"ok": False, "kind": "bad_output",
                              "detail": "输出里还残留换行或 // 注释，压行后会坏"},
                             ensure_ascii=False))
            return 7
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(js)
        manifest.append({"file": path, "role": role, "chars": len(js)})

    print(json.dumps({
        "ok": True,
        "mode": "verify" if args.verify else "fill",
        "layout": mode,
        "items": len(plan),
        "max_chars": args.max_chars,
        "total_chars": sum(m["chars"] for m in manifest),
        "files": manifest,
        "paste_order": [m["file"] for m in manifest],
        "hint": ("逐段 Ctrl+V + 回车，顺序不能乱" if mode == "chunked" else "一次 Ctrl+V + 回车"),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
