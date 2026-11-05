// dl_imgs.mjs — 下载学习通公式/图片选项。
//
// 为什么要 Node：本机系统 schannel 的 HTTPS 基本不可用（curl/Invoke-WebRequest 报
// SEC_E_NO_CREDENTIALS），而 dsh 自带 Node 的 OpenSSL 正常，能直连 chaoxing 图床。
//
// 用法：
//   node dl_imgs.mjs --images images.json --outdir imgs
//   node dl_imgs.mjs --url "https://p.ananas.chaoxing.com/star3/origin/xxx.png" --out imgs/x.png
//
// images.json 两种格式都认：
//   {"1": {"A": ["url1"], "B": ["url2"]}}        # parse_work_html.py --list-images 的输出
//   [{"name": "q1_A.png", "url": "https://..."}] # 直接给名字

import fs from 'fs';
import path from 'path';

const args = process.argv.slice(2);
function arg(name, def = null) {
  const i = args.indexOf('--' + name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0';
const abs = (u) => (u.startsWith('http') ? u : 'https://mooc1-api.chaoxing.com' + u);

async function grab(url, outPath) {
  const r = await fetch(abs(url), { headers: { 'User-Agent': UA, Referer: 'https://mooc1-api.chaoxing.com/' } });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const buf = Buffer.from(await r.arrayBuffer());
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, buf);
  return buf.length;
}

const single = arg('url');
if (single) {
  const out = arg('out', 'img.png');
  const n = await grab(single, out);
  console.log(`${out} ${n}B`);
  process.exit(0);
}

const imgFile = arg('images', 'images.json');
const outdir = arg('outdir', 'imgs');
const data = JSON.parse(fs.readFileSync(imgFile, 'utf8'));

const jobs = [];
if (Array.isArray(data)) {
  for (const it of data) jobs.push({ name: it.name, url: it.url });
} else {
  for (const [num, byLetter] of Object.entries(data)) {
    for (const [letter, urls] of Object.entries(byLetter)) {
      (urls || []).forEach((u, i) => {
        jobs.push({ name: `q${num}_${letter}${urls.length > 1 ? '_' + i : ''}.png`, url: u });
      });
    }
  }
}

if (!jobs.length) {
  console.log('没有图片任务（images.json 为空）');
  process.exit(0);
}

let ok = 0, bad = 0;
for (const j of jobs) {
  try {
    const n = await grab(j.url, path.join(outdir, j.name));
    console.log(`${j.name}\t${n}B`);
    ok++;
  } catch (e) {
    console.log(`${j.name}\tERR ${e.message}`);
    bad++;
  }
}
console.log(`---- ok=${ok} failed=${bad} -> ${outdir}`);
process.exit(bad ? 6 : 0);
