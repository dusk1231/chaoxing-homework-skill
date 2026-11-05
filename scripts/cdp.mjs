#!/usr/bin/env node
/* cdp.mjs — 零依赖 CDP 客户端（Node 22+ 自带全局 WebSocket，不需要 npm install ws）
 *
 * 这是 homework skill 的 **R2 主通道**：直接跟 Edge 的 DevTools 协议说话，
 * 不碰键盘焦点、不碰剪贴板、不用截图找坐标。
 *
 * 用法（port 默认 9333，可用 --port 或环境变量 CDP_PORT 覆盖）：
 *   node cdp.mjs health                       # 探活 + 列出页面
 *   node cdp.mjs targets                      # 只列页面
 *   node cdp.mjs goto <url> [--new]           # 导航（默认复用已有页面）
 *   node cdp.mjs eval  --file fill.js         # 在页面里执行脚本，打印返回值
 *   node cdp.mjs eval  "document.title"       # 直接执行表达式
 *   node cdp.mjs click "<css selector>"       # 点一个元素
 *   node cdp.mjs cookies --domain chaoxing    # 读 cookie（含 HttpOnly）
 *   node cdp.mjs shot  out.png                # 截图
 *
 * 通用选项：
 *   --match <子串>   只挑 URL/标题包含该子串的页面（默认挑最后一个 http(s) 页面）
 *   --save <文件>    eval 的结果写入文件（题目 JSON 很大时用，避免 stdout 截断）
 *   --shot <文件>    eval 结束后截图（提交后留证据）
 *   --timeout <ms>   单次调用超时，默认 60000
 *   --show           连浏览器级会话（一般不用）
 *
 * **copy() 兼容层**：页面里如果调用 copy(x)（老脚本写剪贴板的写法），
 * 这里会被劫持成"把 x 当返回值"，所以 extract_dom.js / make_fill_js.py 生成的
 * fill.js、verify.js **一个字都不用改**就能在 R2 下跑。
 *
 * 退出码：0 成功 / 1 失败（连不上、页面找不到、JS 抛错）/ 2 用法错误
 */

import fs from 'node:fs';
import process from 'node:process';

// ---------- 参数 ----------
const argv = process.argv.slice(2);
const cmd = argv.shift();
const opts = {};
const pos = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a.startsWith('--')) {
    const k = a.slice(2);
    const nxt = argv[i + 1];
    if (nxt !== undefined && !nxt.startsWith('--')) { opts[k] = nxt; i++; }
    else { opts[k] = true; }
  } else pos.push(a);
}

const PORT = Number(opts.port || process.env.CDP_PORT || 9333);
const TIMEOUT = Number(opts.timeout || 60000);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function die(msg, code = 1) {
  console.error('FAIL ' + msg);
  process.exit(code);
}

// ---------- CDP 基础 ----------
async function http(path, method = 'GET') {
  const r = await fetch(`http://127.0.0.1:${PORT}${path}`, { method });
  if (!r.ok) throw new Error(`HTTP ${r.status} ${path}`);
  const txt = await r.text();
  try { return JSON.parse(txt); } catch { return txt; }
}

async function waitHealthy(tries = 40, gap = 500) {
  for (let i = 0; i < tries; i++) {
    try { return await http('/json/version'); } catch { await sleep(gap); }
  }
  die(`CDP 端口 ${PORT} 连不上（浏览器没起？先跑 scripts/browser.ps1 ensure）`);
}

class Session {
  constructor(ws) { this.ws = ws; this.seq = 0; this.pending = new Map(); }

  static async open(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => {
      const t = setTimeout(() => rej(new Error('WebSocket 打开超时')), 15000);
      ws.onopen = () => { clearTimeout(t); res(); };
      ws.onerror = () => { clearTimeout(t); rej(new Error('WebSocket 连接失败')); };
    });
    const s = new Session(ws);
    ws.onmessage = (ev) => {
      let m;
      try { m = JSON.parse(ev.data); } catch { return; }
      if (m.id && s.pending.has(m.id)) {
        const { res, rej, t } = s.pending.get(m.id);
        s.pending.delete(m.id);
        clearTimeout(t);
        if (m.error) rej(new Error(m.error.message || JSON.stringify(m.error)));
        else res(m.result);
      }
    };
    return s;
  }

  send(method, params = {}, timeout = TIMEOUT) {
    const id = ++this.seq;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((res, rej) => {
      const t = setTimeout(() => { this.pending.delete(id); rej(new Error(`${method} 超时 ${timeout}ms`)); }, timeout);
      this.pending.set(id, { res, rej, t });
    });
  }

  close() { try { this.ws.close(); } catch {} }
}

async function pages() {
  const list = await http('/json/list');
  return (Array.isArray(list) ? list : []).filter(
    (t) => t.type === 'page' && !/^devtools:/.test(t.url || '')
  );
}

async function pickPage() {
  const all = await pages();
  const match = opts.match;
  let cands = all;
  if (match) cands = all.filter((t) => (t.url || '').includes(match) || (t.title || '').includes(match));
  else cands = all.filter((t) => /^https?:/.test(t.url || ''));
  // 只有 about:blank 时也要能用（首次 ensure 后读 cookie 就靠这条）
  if (!cands.length) cands = all;
  if (!cands.length) return null;
  return cands[cands.length - 1];
}

async function pageSession() {
  const t = await pickPage();
  if (!t) die(`找不到目标页面（已开：${(await pages()).map((p) => p.url).join(' | ') || '无'}）`);
  const s = await Session.open(t.webSocketDebuggerUrl);
  return { s, t };
}

// copy() 兼容层：老脚本用 copy(x) 回写剪贴板，这里改成"把 x 变成返回值"
// expr 形态：脚本本身是**一个表达式**（extract_dom.js / submit.js 都是 IIFE），能拿到返回值
// stmt 形态：脚本是多条语句（make_fill_js.py 的分块段，靠 copy() 回读），兜底用
function wrapCopy(src, mode) {
  const head = `(function(){var __out=null;var copy=function(x){__out=String(x);};`;
  const tail =
    `if(__out!==null)return __out;` +
    `if(__ret===undefined||__ret===null)return null;` +
    `if(typeof __ret.then==='function')return __ret;` +
    `return __ret;})()`;
  if (mode === 'stmt') return `${head} (function(){ ${src} })(); var __ret; ${tail}`;
  return `${head} var __ret=(\n${src}\n); ${tail}`;
}

function isSyntaxError(d) {
  if (!d) return false;
  const cls = d.exception && (d.exception.className || '');
  const txt = (d.exception && (d.exception.description || d.exception.value)) || d.text || '';
  return /SyntaxError/.test(cls) || /SyntaxError/.test(String(txt));
}

async function evalOnPage(source) {
  const { s, t } = await pageSession();
  const forms = source.isRaw ? [source.code] : [wrapCopy(source.code, 'expr'), wrapCopy(source.code, 'stmt')];
  try {
    let lastErr = null;
    for (let i = 0; i < forms.length; i++) {
      const r = await s.send('Runtime.evaluate', {
        expression: forms[i],
        returnByValue: true,
        awaitPromise: true,
        userGesture: true,
      }, TIMEOUT);
      if (!r.exceptionDetails) return r.result ? r.result.value : undefined;
      lastErr = r.exceptionDetails;
      if (!isSyntaxError(r.exceptionDetails) || i === forms.length - 1) break;
    }
    const d = lastErr;
    const msg = (d.exception && (d.exception.description || d.exception.value)) || d.text || 'JS 异常';
    die(String(msg).split('\n')[0] + `  [${(t.url || '').slice(0, 80)}]`);
  } finally { s.close(); }
}

async function shotTo(path) {
  const { s } = await pageSession();
  try {
    const r = await s.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    fs.writeFileSync(path, Buffer.from(r.data, 'base64'));
    return fs.statSync(path).size;
  } finally { s.close(); }
}

// ---------- 子命令 ----------
async function main() {
  if (!cmd || cmd === '-h' || cmd === '--help') {
    console.log('cdp.mjs health|targets|goto|eval|click|cookies|shot  （--help 见文件头注释）');
    return;
  }

  if (cmd === 'health') {
    const v = await waitHealthy();
    const ps = await pages();
    console.log(JSON.stringify({
      ok: true,
      port: PORT,
      browser: v.Browser,
      pages: ps.map((p) => ({ title: (p.title || '').slice(0, 60), url: (p.url || '').slice(0, 120) })),
    }, null, 1));
    return;
  }

  if (cmd === 'targets') {
    await waitHealthy();
    const ps = await pages();
    console.log(JSON.stringify(ps.map((p) => ({ id: p.id, title: p.title, url: p.url })), null, 1));
    return;
  }

  if (cmd === 'goto') {
    const url = pos[0];
    if (!url) die('goto 需要 url', 2);
    await waitHealthy();
    const target = await pickPage();
    let sess;
    if (target && !opts.new) {
      sess = await Session.open(target.webSocketDebuggerUrl);
      await sess.send('Page.navigate', { url });
    } else {
      const created = await http(`/json/new?${encodeURIComponent(url)}`, 'PUT');
      sess = await Session.open(created.webSocketDebuggerUrl);
    }
    // 等 load
    for (let i = 0; i < 40; i++) {
      await sleep(400);
      const r = await sess.send('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true });
      if (r.result && r.result.value === 'complete') break;
    }
    const info = await sess.send('Runtime.evaluate', {
      expression: 'JSON.stringify({href:location.href,title:document.title})', returnByValue: true,
    });
    sess.close();
    console.log(info.result.value);
    return;
  }

  if (cmd === 'eval') {
    let source;
    if (opts.file) {
      const f = String(opts.file);
      if (!fs.existsSync(f)) die(`文件不存在: ${f}`, 2);
      source = { code: fs.readFileSync(f, 'utf8') };
    } else if (pos[0]) {
      source = { code: pos[0], isRaw: true };
    } else if (!process.stdin.isTTY) {
      source = { code: fs.readFileSync(0, 'utf8') };
    } else die('eval 需要表达式或 --file', 2);

    await waitHealthy();
    const val = await evalOnPage(source);
    let text = typeof val === 'object' ? JSON.stringify(val) : (val === undefined ? '' : String(val));

    if (opts.save) {
      fs.writeFileSync(String(opts.save), text, 'utf8');
      console.log(`SAVED ${opts.save} chars=${text.length}`);
    } else {
      console.log(text);
    }

    if (opts.shot) {
      const n = await shotTo(String(opts.shot));
      console.log(`SHOT ${opts.shot} bytes=${n}`);
    }
    return;
  }

  if (cmd === 'click') {
    const sel = pos[0];
    if (!sel) die('click 需要 css 选择器', 2);
    await waitHealthy();
    const val = await evalOnPage({
      isRaw: true,
      code:
        `(function(){var el=document.querySelector(${JSON.stringify(sel)});` +
        `if(!el)return 'NO_ELEMENT';el.scrollIntoView({block:'center'});el.click();return 'CLICKED';})()`,
    });
    console.log(val);
    return;
  }

  if (cmd === 'cookies') {
    await waitHealthy();
    const { s, t } = await pageSession();
    try {
      await s.send('Network.enable', {});
      let r = await s.send('Network.getAllCookies', {});
      const all = (r && r.cookies) || [];
      const dom = opts.domain ? String(opts.domain) : null;
      const sel = dom ? all.filter((c) => (c.domain || '').includes(dom)) : all;
      console.log(JSON.stringify({
        page: t.url.slice(0, 100),
        total: all.length,
        filtered: sel.length,
        names: [...new Set(sel.map((c) => c.name))].sort(),
      }, null, 1));
    } finally { s.close(); }
    return;
  }

  if (cmd === 'shot') {
    const out = pos[0];
    if (!out) die('shot 需要输出路径', 2);
    await waitHealthy();
    const n = await shotTo(out);
    console.log(`SHOT ${out} bytes=${n}`);
    return;
  }

  die(`未知子命令 ${cmd}`, 2);
}

main().catch((e) => die(e.message || String(e)));
