---
name: homework
description: 学习通/超星作业的标准作答路径：一次 JS 注入批量填写，杜绝逐项点击。已在真实作业上跑通（第3章43题、第5章40题、二元关系10题、CSS理论70题）。触发词：学习通、超星、作业、写作业、交作业、作业答题、客观题、xuexitong、chaoxing、homework。
version: 3.1.0
---

# 学习通作业（homework）

> ## 核心结论（先读这段）
>
> **默认通道 = R2（Node 直连 CDP）**，2026-10-30 起生效。
>
> **browser.ps1 ensure → goto 作业页 → 一次 evaluate 取题 → 离线算答案 → 一次 evaluate 填 → 一次 evaluate 提交 → 截图收尾。**
>
> 通道阶梯 **R2 → R1 → MCP**，任何一步失败都**先问用户**再换方案：
>
> | 阶梯 | 工具 | 什么时候用 |
> |---|---|---|
> | **R2 主通道** | `browser.ps1` + `cdp.mjs` | **默认**。零依赖（Node 22+ 自带 `WebSocket`），不碰键盘焦点、不碰剪贴板、不用截图找坐标；取题/填写/回读全是 evaluate 一次调用 |
> | **R1 后备** | `pw_fallback.py`（Playwright） | R2 起不来或 evaluate 失败时。**同一个 user-data-dir**，登录态无缝继承 |
> | **MCP 原方案** | `probe.ps1` / `ping.ps1` / `send.ps1` / MCP 三连 | R2、R1 都失败时的兜底。老通道，依赖键盘焦点 + 剪贴板，本机时好时坏 |
>
> **R2 三信号判定（任一不过就停）**：
> ① `browser.ps1 doctor` → `cdp = UP`；② `cdp.mjs health` 返回浏览器版本与页面列表；③ `cdp.mjs eval "1"` → `1`。
>
> **登录只做一次**：专属 profile 是干净的，第一次跑 `browser.ps1 login`，在弹出的窗口里扫码登录学习通，
> cookie 存 `%LOCALAPPDATA%\dsh-homework\edge-profile`，之后 `ensure` 自动复用。
> ⚠️ **不要再尝试拷贝用户日常 Edge 的 profile**——2026-10-30 实测：把 `Local State/Preferences/Secure Preferences/Network/Cookies`
> 复制到独立 user-data-dir 后，Edge 能起、CDP 通，但学习通会 302 回登录页（`fid/_uid` 等登录 cookie 没带过来）。
>
> **2026-10-29 补三条（都是那次 40 分钟换来的）**：
> ① 脚本必须**单行、无 `//` 行注释、每段 < 7000 字符**——控制台粘贴会压行（`//` 吞代码）
>    且约 8000 字符截断；`make_fill_js.py` 现在自动满足并自动分块。
>    （R2/R1 通道不粘贴进控制台，此约束仍保留给 MCP 兜底通道。）
> ② 注入前先 `ping.ps1` 判「控制台吃不吃键」，别用截图猜焦点。（MCP 通道专用）
> ③ **同一个注入动作失败两次就停手**，改成把脚本放剪贴板让用户自己 `Ctrl+V`——最快的路径。
>
> **2026-10-29 定规（用户明确要求，省时间）**：
> ④ **填满就提交，不再二次 verify**——`/h=` 回读 + 右侧答题卡全蓝即可，别再生成 `--verify` 脚本。
> ⑤ **默认直接点「提交」**，不再等用户确认；只有用户本次明确说「先给我看」才停。
> ⑥ **看到「分数 + 查看详情」界面 = 任务完成**，立即收尾，不要再点「查看详情」。
>
> **2026-10-30 定规（用户明确要求：失败必须问）**：
> ⑦ **任何通道失败（R2 或 R1），停下问用户「改用哪套方案」再继续**，不允许静默自动降级。
> ⑧ **R2 是默认且首选**；R2 失败换 R1；两者都失败才回 MCP 原方案。

---

## 铁律

> **铁律 1｜禁止逐项 UI 操作**
> 读题、填写、提交三个环节，禁止逐项 `Click` / `Type` / `Snapshot` 循环。
> 允许的 UI 操作只有：① 一次导航/切窗到作业页；② 打开 DevTools；③ 一次粘贴回车；④ 用户人工登录。

> **铁律 2｜一次注入，不要逐题**
> 所有题目的填写必须合并成**一个** JS 表达式，在控制台里**一次**回车跑完。

> **铁律 3｜先读后写，读要留证据**
> 读题必须拿到能解析出 `qid` / 选项 `data` / 编辑器 id 的**结构化数据**。
> 任何"应该差不多是这样"的猜测都不算读题。

> **铁律 4｜填满即提交（2026-10-29 用户改规，覆盖旧版）**
> 回读 `/h=` 全 ok、右侧答题卡全蓝 ⇒ **直接点「提交」→ 弹「确认提交？」点「确定」**，不停下来等确认。
> 只有用户本次**额外要求**「先给我看答案」时，才交付到「已填完、未提交」并等一句「确认提交」。
> 提交后在「分数 + 查看详情」页面收尾即可，**不要点查看详情**。
> ⚠️ 旧规则（每题都要显式确认）已作废——用户 2026-10-29 明确：除非额外要求，否则不用问我，直接提交。

> **铁律 5｜公式/图片选项必须真看图**
> 选项是 `<img class="ans-formula-moudle">` / `ans-edrawmath-moudle` 时，
> 必须把 PNG 下载下来看过才能确定。**不得按选项顺序猜。**

> **铁律 6｜先复用工作区，再写新的**
> 动手前先 `ls` 工作区和 skill 的 `scripts/`：
> 上一轮很可能已经留下 `extract_*.js` / `*_fill.js` / `edge.ps1` / `inject*.ps1`。
> **能改就不重写**。2026-10-27 那次从零写了 `inject3/4/5/6` 四个脚本全失败，
> 而工作区里早就有 `edge.ps1` + `inject2.ps1` 可以直接对照。

> **铁律 7｜坐标只能来自截图，不能来自猜测**
> 任何需要点击的坐标，必须先用 `Screenshot`（或 `Snapshot`）看到再点。
> 控制台提示行的位置随滚动变化——`inject3/4/5/6` 四次全挂在同一个猜错的坐标上。

> **铁律 8｜验证只做一次，用页面自己的信号**
> 填完只看两个信号：① 注入回读 `N:ok/h=X` 全部 ok；② 右侧答题卡 1..N **全蓝**。
> **禁止再跑 `--verify` 二次注入**（2026-10-29 那次就是多花了几轮工具调用在这上面，用户点名太久）。
> 分数页出现即完成。

> **铁律 9｜通道失败必须问用户，不许静默降级（2026-10-30 用户定规）**
> R2 是默认首选；R2 失败 → 换 R1（Playwright）；R1 也失败 → 回 MCP 原方案。
> **每次换通道都要停下来问用户一句「要不要改用 R1 / MCP 原方案」**，得到明确答复再动手。
> 唯一允许自己修的例外：R2 的「浏览器没起 / 端口没就绪 / 页面不在」这种一次性可修错误，修一次再判。

---

## 第 0 步｜R2 主通道（默认，别跳过）

```powershell
cd $env:USERPROFILE\.dsh\skills\homework

# ① 探活：要求 cdp=UP
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/browser.ps1 doctor

# ② 起浏览器（等价 doctor 后再跑这一条；幂等，已起就只报 READY）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/browser.ps1 ensure

# ③ 打开作业页（URL 从用户给的链接/浏览器复制）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/browser.ps1 goto -Url "https://mooc1-api.chaoxing.com/mooc-ans/mooc2/work/dowork?xxx"

# ④ 取题：结果直接落盘（抄本不用管剪贴板）
node scripts/cdp.mjs eval --file scripts/extract_dom.js --save questions.json

# ⑤ 算答案 → 写 answers.json → 生成 fill.js（见第 3/4 步）
# ⑥ 填 + 回读（一次调用；有 --shot 就顺手截图）
node scripts/cdp.mjs eval --file fill.js --shot after_fill.png
#    输出必须是: done 1:ok/h=A 2:ok/h=B ... （全 ok 才能往下走）

# ⑦ 提交（提交按钮 + 确认弹窗一把过）+ 截图留证
node scripts/cdp.mjs eval --file scripts/submit.js --shot after_submit.png
#    返回 SUBMITTED <按钮> / SUBMITTED_PAGE / ALREADY_DONE / CONFIRM_TIMEOUT
```

**R2 的常用子命令**（`node scripts/cdp.mjs`）：

| 命令 | 用途 |
|---|---|
| `health` | 探活 + 列页面（浏览器版本 + 页面标题/URL） |
| `targets` | 只列页面 |
| `goto <url> [--new]` | 导航（默认复用最后一个 http(s) 页面；`--new` 开新标签） |
| `eval --file x.js [--save f] [--shot p]` | 执行脚本并取返回值；脚本里的 `copy(x)` 会被劫持成"返回值" |
| `eval "<表达式>"` | 直接执行表达式（如 `document.title`） |
| `click "<css>"` | 点一个元素（`CLICKED` / `NO_ELEMENT`） |
| `cookies [--domain chaoxing]` | 读 cookie 名（含 HttpOnly），判断登录态 |
| `shot <out.png>` | 截图 |

> **R2 为什么稳**：CDP 直接跟浏览器进程说话，没有焦点/剪贴板/UIA 树这三样随时可能坏的东西。
> `copy()` 兼容层让 `extract_dom.js` / `fill.js` / `verify.js` **一个字都不用改**就能在 R2 下跑
> （`make_fill_js.py` 生成的脚本里那句 `copy(msg)`，在 R2 里变成返回值）。
>
> **R2 也会挂的两种情况**，都能自检：
> - 浏览器没起 / 端口没就绪 → `cdp.mjs health` 报 `FAIL CDP 端口 9333 连不上` → 跑 `browser.ps1 ensure` 看输出；
> - 页面不在 → `cdp.mjs eval` 报 `找不到目标页面` → 确认 `browser.ps1 goto -Url` 的 URL 是作业页。
> 这两条都修不好 → **停下来问用户：换 R1（Playwright）还是 MCP 原方案。**

**R1 后备**（R2 失败时，用户确认后执行）：

```powershell
# 先停掉 R2 的 Edge（profile 同一时刻只能被一个实例占用）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/browser.ps1 stop

py scripts/pw_fallback.py --profile "%LOCALAPPDATA%\dsh-homework\edge-profile" \
    --goto "https://mooc1-api.chaoxing.com/mooc-ans/mooc2/work/dowork?xxx" \
    --file scripts/extract_dom.js --save questions.json
py scripts/pw_fallback.py --profile "%LOCALAPPDATA%\dsh-homework\edge-profile" \
    --file fill.js --shot after_fill.png
```

参数：`--profile`（与 R2 相同的 user-data-dir）· `--file/--expr/--goto` · `--save` · `--shot` ·
`--login`（有头打开学习通登录页，扫码一次）· `--match <子串>`（挑某个标签页）。

---

## 第 0 步｜MCP 原方案的通道判定（仅 R2+R1 都失败时才用）

> 这一节及其后续所有 `win.ps1` / `send.ps1` / `ping.ps1` / MCP 三连的内容，
> **只在用户确认「改用 MCP 原方案」之后才走**。R2/R1 正常时永远不要碰。
>
> ```powershell
> powershell -NoProfile -ExecutionPolicy Bypass -File scripts/probe.ps1
> ```

输出：

```
window    = 作业作答 和另外 1 个页面 - 个人 - Microsoft Edge
hwnd      = 2296412  pid=31236
nodes     = 125  edgeTabs=0  documents=2  dumpChars=600
console   = True
VERDICT   = UIA_OK
CHANNEL   = win.ps1 tabs/select-tab/dump 可用；注入仍推荐 send.ps1
```

| VERDICT | 含义 | 走哪条 |
|---|---|---|
| `UIA_OK` | 有 EdgeTab，**或**真能取到 600 字符正文（`dumpChars>0`） | `win.ps1` 的 tabs/dump 可用；注入用 `send.ps1` |
| `UIA_HALF` | 有 `Document` 但 `dumpChars=0`（空壳 Document） | `dump` 一定是空，**别再试**；直接走 `ping.ps1`/`send.ps1` |
| `UIA_DEAD` | `edgeTabs=0` 且 `dumpChars=0` | **`win.ps1` 全部失效**，只能 `ping.ps1` + `send.ps1`/`clip.ps1` |
| `NO_EDGE_WINDOW` | 找不到 Edge | 先让用户打开作业页 |

> **判据是「真的取到正文」，不是 `documents` 计数。**
> 2026-10-27 那次节点数只有 2，`win.ps1 tabs/url/text/dump` 四个 action 全空——逐个试，白花 10 分钟。
> 2026-10-29 又出现了更坑的一种：`documents=1` 让旧 probe 报 `UIA_OK`，但 `dump` 实际返回 0 字符。
> 所以现在 probe 会**真去取 600 字符**，取不到就报 `UIA_HALF`。

---

## 第 0.5 步｜MCP 原方案通道探针（30 秒，别再猜）

> R2/R1 正常时**永远不用跑**这一节。只有走 MCP 原方案时才需要。

`probe.ps1` 只回答“UIA 能不能用”，`ping.ps1` 回答“**控制台到底吃不吃键**”。
2026-10-29 那次就是在这上面耗了 20 分钟：粘贴进去了但回车没执行，和键盘根本没进控制台，
屏幕上看起来一模一样。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ping.ps1 -Wait 20
```

- 它把 `copy("PIN"+"G <token>")` 放上剪贴板 → 你按提示 Ctrl+V + 回车 → 它轮询剪贴板
- 剪贴板变成 `PING <token>` → **`PING_OK`**，全链路（粘贴/执行/copy 回读）通
- 超时 → **`PING_FAIL`**（退出码 9），别再瞎试，直接换人肉粘贴

> `-Auto` 会让脚本自己聚焦控制台并粘贴回车；本机实测时好时坏，
> **坏的时候不要反复重试**，见下面「人肉粘贴」这条最快路径。

---

## 第 1 步｜提取题目

> 这一节是 **MCP 原方案** 的注入路径。R2/R1 请直接用第 0 步的
> `node scripts/cdp.mjs eval --file scripts/extract_dom.js --save questions.json`（不需要 `send.ps1`/剪贴板/焦点）。

### 通道 A｜send.ps1（默认）+ MCP 三连（后备）

**默认做法**：`send.ps1` 一条命令做完「动态找窗口 → 聚焦控制台 → 清输入 → 粘贴 → 回车 → 回读」，
窗口句柄不再硬编码（历次临时脚本都写死 `1640922`，Edge 一重启就废）。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/send.ps1 fill.js
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/send.ps1 fill.js -X 1450 -Y 978   # 需要先点提示行时
```

成功时它打印 `clip_after=<长度>` 和 `head= done 1:ok/h=A ...`（脚本里的 `copy()` 把结果写回剪贴板）；
若提示 `note=剪贴板没变化`，先跑 `ping.ps1` 判定通道，**不要连续重试**。

**后备（`send.ps1` 出不来的时候）**：MCP 三连，三次工具调用，最稳但也最慢。

```
1) Screenshot  → 确认 DevTools 控制台提示行 (>) 的坐标
2) Click       → 点提示行
3) Type        → "allow pasting" 回车      ← DevTools 的 self-XSS 粘贴保护，必须先解锁
4) clip.ps1 set scripts/extract_dom.js     ← 把 JS 放上剪贴板
5) Click 提示行 → Shortcut "ctrl+v" → Shortcut "Return"
6) clip.ps1 get questions.json             ← 结果落在剪贴板
```

**最快路径（2026-10-29 实测）**：键盘往 DevTools 里送不稳的时候，
直接把脚本放进剪贴板、让用户自己 `Ctrl+V` + 回车，**2 分钟搞定**，比继续修注入器快得多。

`extract_dom.js` 的输出 schema 与 `parse_work_html.py` 完全一致，直接喂 `make_fill_js.py`。

> **踩过的坑**
> - **`allow pasting` 必须真的输进提示行**。脚本里发 `SendKeys` 时如果焦点不在控制台，
>   这行字会打到别处，后面粘贴永远被拦。
> - **坐标必须来自截图**。控制台提示行位置随滚动变，写死坐标必挂。
> - **`Set-Clipboard` + `SendKeys ^v` 在 PowerShell 里不可靠**（焦点被抢）。
>   MCP 的 `Shortcut "ctrl+v"` 走的是真实键盘事件，稳。
> - **结果回读用 `copy(...)`**：注入脚本最后一句必须是 `copy(msg)`，
>   否则结果只在控制台里显示，取不回来。`make_fill_js.py` 已内置这一句。

### 通道 B｜win.ps1 dump（仅 UIA_OK 时）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/win.ps1 tabs
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/win.ps1 select-tab 作业作答
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/win.ps1 dump -Out page_dump.txt
py scripts/parse_work_html.py --input page_dump.txt --out questions.json
```

`dump` 带行号前缀，`parse_work_html.py` 会自动剥。

> **不要用 `Ctrl+W` 关标签**——很容易关掉作业页本身（踩过）。
> 要离开 view-source，用 `win.ps1 select-tab <子串>` 切回去。

---

## 第 2 步｜公式/图片选项必须下载看图

```bash
py scripts/parse_work_html.py --input page_dump.txt --list-images > images.json
"D:/toor/ds/resources/runtime/primary-runtime/dependencies/node/bin/node.exe" \
    scripts/dl_imgs.mjs --images images.json --outdir imgs
```

然后逐张 `read_image` 确认字母对应关系。
（`p.ananas.chaoxing.com` 与 `mooc1-api.chaoxing.com/ananas/latex/...` 都可用 Node 直连，
系统 curl/schannel 会 `SEC_E_NO_CREDENTIALS`，别用 curl。）

---

## 第 3 步｜算答案，写 answers.json

```json
{ "1": "B", "2": "C", "19": "深度优先", "20": "对", "26": "<p>...</p>" }
```

- 选择题填选项**字母**（或 `data` 值，脚本会映射）；
- 多选题用逗号：`"54": "A,B,C,D"`；
- 判断题写 `对`/`错`（也接受 `true`/`false`、`A`/`B`）；
- 填空题填纯文本，多空用 `|` 分隔：`"8": "a|b"`；
- 设计题/简答题填 HTML 片段。

> **选项字母和显示位置是错位的**：学习通的 `[data]` 属性才是真实选项值，
> 而它在页面上显示为 A/B/C/D 的顺序可能被打乱（CSS 那份卷子就是这样）。
> 所以**必须用 `data` 而不是"第几个选项"**，`extract_dom.js` 已经按 `data` 输出。

---

## 第 4 步｜生成一次性注入脚本

```bash
py scripts/make_fill_js.py --questions questions.json --answers answers.json --out fill.js
py scripts/make_fill_js.py --questions questions.json --answers answers.json --out verify.js --verify
```

`fill.js` 做三件事：
1. 选择题 → `.answerBg[qid]` 里 `[data]` 匹配的 **div**（不是 span），未选中时调 `addChoice(el)`；
2. 填空题 → `UE.getEditor('answerEditor<qid>N').setContent(text)`；
3. 设计题 → `UE.getEditor('answer<qid>').setContent(html)`。

脚本自带：漏答检查、空数/编辑器数一致性校验、**写完回读隐藏域 `/h=`**。

### 输出必须满足两条硬约束（2026-10-29 各踩一次）

| 约束 | 为什么 | 现在谁保证 |
|---|---|---|
| **单行、无 `//` 行注释** | 控制台粘贴前要压行，`//` 会吞掉后面全部代码 → `Unexpected end of input` | `make_fill_js.py` 生成时自动剥注释并压行，还会自检残留 |
| **每段 < 7000 字符** | DevTools 控制台单次粘贴约 **8000 字符**会被截断，截断后必然语法错 | `make_fill_js.py --max-chars`（默认 7000）自动分块 |

超长时它会自动产出并打印 `paste_order`：

```json
{ "layout": "chunked", "files": [
    { "file": "fill.js",       "role": "part1",  "chars": 5162 },
    { "file": "fill_p2.js",    "role": "part2",  "chars": 2552 },
    { "file": "fill_p3.js",    "role": "runner", "chars": 1768 } ],
  "hint": "逐段 Ctrl+V + 回车，顺序不能乱" }
```

第 1 段建 `window.__PLAN`，中间段 `concat`，**最后一段才是执行器**——顺序错了就没答案可选。

---

## 第 5 步｜注入 + 回读

```powershell
# 单段
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/send.ps1 fill.js
# 分块（按 make_fill_js.py 打印的 paste_order 顺序，一段一条命令）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/send.ps1 fill.js
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/send.ps1 fill_p2.js
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/send.ps1 fill_p3.js
# 手工兜底：把命令换成 clip.ps1 set <file>，让用户自己 Ctrl+V + 回车
```

成功输出：

```
done 1:ok/h=A 2:ok/h=A 3:ok/h=B ... 54:ok/h=ABCD 58:ok/h=true
```

- `ok/h=X` = 该题隐藏域已写入 X，是真证据；
- `PARTIAL(1/2)/h=A` = 只选中一半，检查多选是否被当成单选；
- `NO_ELEMENT` = qid 不对，回第 1 步重取；
- `NO_HIDDEN` = 页面结构变了，隐藏域 id 不再是 `answer<qid>`。

---

## 第 6 步｜提交

**R2 一把过**（默认）：

```powershell
node scripts/cdp.mjs eval --file scripts/submit.js --shot after_submit.png
```

返回 `SUBMITTED <按钮>` / `SUBMITTED_PAGE` / `ALREADY_DONE` / `CONFIRM_TIMEOUT`。
最后 `read_image` 看截图：出现「分数 + 查看详情」= **完成，立即收尾**（铁律 6）。

MCP 原方案的提交坐标不固定（DevTools 停靠会压缩页面），按截图定位「提交」按钮；
确认弹窗里的「提交」在弹窗内，别点成 DevTools 或导航栏上的同名按钮
（2026-10-29 那次点 (1860,100) 实际点到了 DevTools 的「自定义和控制 DevTools」）。

> **铁律 4**：填满就提交。`/h=` 回读 + 右侧答题卡全蓝即可，不再跑 `--verify` 二次注入。
> **铁律 5**：默认直接提交，只有用户本次明确说「先给我看」才停。

---

## 题型支持矩阵

| 题型 | `kind` | 写入方式 | 实测状态 |
|---|---|---|---|
| 单选题 | `choice` | `.answerBg[qid]` 的 div → `addChoice(el)` | ✅ 第3章 12 + 第5章 24 + CSS 53 |
| 判断题 | `choice` | 同上，`data` 是 `true`/`false` | ✅ 第3章 12 + 第5章 8 + CSS 13 |
| 填空题（单空） | `fill` | `UE.getEditor('answerEditor<qid>1').setContent()` | ✅ 第3章 14 + 第5章 5 |
| 填空题（多空） | `fill` | `answerEditor<qid>1..N` 逐空写，答案 `a\|b\|c` | ✅ 第3章 5 + 第5章 3 |
| 设计题/大题 | `essay` | `UE.getEditor('answer<qid>').setContent(html)` | ✅ 第5章 1 |
| 多选题 | `choice`+`multi` | `addMultipleChoice(el)`，判定看 `.num_option_dx` | ✅ CSS 54–57（首次真实页面跑通） |

**判定优先看结构而不是题型名**：有 `answerEditor<qid>N` → 填空；有 `textarea#answer<qid>` → 大题；
有 `.num_option_dx` → 多选；其余有选项 → 单选/判断。

> **多空题必须核对「空数 == 编辑器数」**：空数以 `name="tiankongsize<qid>"` 为准。
> 不等时 `make_fill_js.py` 直接报错拒绝生成——上一版曾把 `Cookie|Set-Cookie`
> 整串写进第 1 空（第5章 Q30/31/32）。

---

## 速度基线

| 环节 | 第3章(43) | 第5章(40) | CSS(70) 教训后 | Edge HTML(91) | **R2（2026-10-30 起默认）** |
|---|---|---|---|---|---|
| 通道判定 | 2 min | 5 min | **1 min**（probe.ps1 一条命令） | **1 min**（probe + ping） | **~10 秒**（`browser.ps1 doctor`） |
| 提取题目 | 5 min | 8 min | **2 min**（extract_dom.js + clip） | **2 min** | **<5 秒**（一次 evaluate 直接落盘） |
| 算答案 | 15 min | 12 min | 12 min（必要成本） | 8 min | 8 min（必要成本） |
| 注入 + 校验 + 提交 | 9 min | 25 min | **4 min**（MCP 三连） | **3 min**（send 或人肉粘贴） | **<10 秒**（fill.js + submit.js 各一次调用） |
| 合计 | ~30 min | ~50 min | **~20 min** | **~14 min** | **~10 min**（瓶颈只剩算答案） |

**两次长尾都是同一个病**：2026-10-27 花 20 分钟在通道判定，2026-10-29 花 20 分钟在注入器。
瓶颈从来不是算答案，是**在错误的通道上反复重写脚本**。

判断标准：一个注入动作失败**两次**就停手，改用「脚本放剪贴板 + 用户自己 Ctrl+V」——
那次前面 12 分钟全是白试，最后这招 2 分钟完事。**这不是认输，是最短的路径。**

R2 之后「注入」彻底消失（没有焦点/剪贴板/粘贴），剩下的唯一成本就是算答案本身。

---

## 页面结构速查（学习通 dowork 页）

| 元素 | 结构 |
|---|---|
| 题目块 | `<div class="padBom50 questionLi ..." typeName="单选题" id="question<qid>" data="<qid>">` |
| 题干 | `<h3 class="mark_name ...">N.(单选题)<p>...</p></h3>` |
| 选项容器 | `<div class="answerBg" qid="<qid>" qtype="0" onclick="addChoice(this)">` |
| 选项值 | 容器内 `<span data="A" class="choice<qid> num_option">`（**span 上只有字母，正文在兄弟 div.answer_p**） |
| 答案隐藏域 | `<input type="hidden" id="answer<qid>" name="answer<qid>" value="">` |
| 填空题编辑器 | `<textarea id="answerEditor<qid>1">`（`UE.getEditor(...)`）|
| 设计题编辑器 | `<textarea id="answer<qid>">` |
| 空数 | `<input type="hidden" name="tiankongsize<qid>" value="N">` |
| `qtype` | 0=单选 2=填空 3=判断 4=设计 |

**`addChoice(el)` 是 toggle 语义**：已选中的再调一次会取消。
参数必须是 `.answerBg` 这个 **div**（页面写的就是 `addChoice(this)`），
传 `[data]` 那个 span 进去只会改样式、**隐藏域仍是空**——CSS 那次第一版就是这么错的。

---

## 已知坑（都是真踩过的，别再踩）

1. **UIA 树会整体退化**：只剩 `Chrome_RenderWidgetHostHWND` + `Intermediate D3D Window`，
   `EdgeTab`/`OmniboxViewViews`/`Document` 全无，`win.ps1` 四个 action 全空。
   → 用 `probe.ps1` 一次判定，别逐个试。
2. **DevTools 的 self-XSS 粘贴保护**：直接 `Ctrl+V` 会被 "Warning: Don't paste code…" 拦住，
   必须先手动在提示行输入 `allow pasting` 回车。
3. **PowerShell 里 `SendKeys ^v` 不可靠**：焦点会被抢走，粘贴打到别处。
   → 用 MCP 的 `Shortcut "ctrl+v"`，它走真实键盘事件。
4. **坐标不能猜**：控制台提示行位置随滚动变化。`inject3/4/5/6` 四次全挂在猜错的坐标上。
5. **结果必须 `copy()` 回剪贴板**：否则结果只在控制台显示，脚本取不到。
6. **`clip.ps1 get` 落盘的文件带 BOM**（PowerShell 5.1 的锅），
   Python 用 `utf-8` 读会 `Unexpected UTF-8 BOM`。→ 脚本一律用 `utf-8-sig` 读（已修）。
7. **`view-source` dump 带行号**：每行前有 `\t<数字>\t`，`parse_work_html.py` 会自动剥。
8. **判断题的 `data` 是 `true`/`false`**，不是 `A`/`B`。
9. **UEditor 必须有实例**：`setContent` 会触发 `contentChange` → `loadEditorAnswerd`，这是落库关键。
10. **公式选项是图片**：题干里 `spacer.gif` 是行内公式占位，选项里 `ans-formula-moudle` 必须下载看。
11. **`addChoice` 会 toggle**，且**参数是 div 不是 span**（见上）。
12. **`Ctrl+W` 会关掉当前标签**：第3章那次想关 view-source，结果把作业页也带走。
    **关标签前先 `probe.ps1` / `win.ps1 tabs` 确认**。
13. **最后一题的块会延伸到页尾**：早期版本会把最后一道判断题误判成多选。已修。
    ⚠️ **切尾巴时绝不能按 `<script` 截断**——每个填空后面紧跟 UEditor 初始化 `<script>`，
    按它切会把多空题的第 2 个空起全丢掉。
14. **DevTools 控制台返回值带一层单引号**：`'done ...'`，用 `^done` 锚定匹配不到。
15. **`.ps1` 必须存成 UTF-8 带 BOM + CRLF**：5.1 读无 BOM 的 UTF-8 会当 GBK，中文注释变乱码甚至语法错。
    2026-10-30 改 `browser.ps1` 时编辑器重写丢了 BOM，`stop` 直接解析失败
    （报 `The string is missing the terminator`），还连带让 Playwright 拿到被占用的 profile。
    → 改完任何 `.ps1` 先跑 `py scripts/fix_bom.py --dir scripts`。
16. **本机没有 `pwsh`（PowerShell 7）**，只有 `powershell`（5.1），一律 `powershell -File`。
17. **`Ctrl+U` 在本机 Edge 上不生效**。取 HTML 更可靠的是控制台 `copy(outerHTML)`。
18. **`USER_CONTROL` 错误 = 用户正在操作鼠标**，不是通道失败。
    连续返回 5–6 次时应该 `sleep 15` 等干净，或先离线算完答案再碰浏览器，**不要高频重试**。
19. **提取脚本先跑 1 题验证字段再全量**：CSS 那次 `ex1.js` 没检查选项文本结构
    （`span[data]` 里只有字母，正文在 `div.answer_p`），拿到的选项全错位，只好重写重跑。
20. **`//` 行注释会吞掉压行后的整段脚本**（2026-10-29，浪费 ~20 min）：
    `clip.ps1 set` 把换行压成空格 → 第一条 `//` 之后全部被注释 → 控制台报
    `Uncaught SyntaxError: Unexpected end of input (at VM14x:4:8028)`。
    那个 `8028` 不是偶然，是**第一条注释的位置**。→ `make_fill_js.py` 现在生成时自动剥注释，
    `clip.ps1 set` 也会 `WARN` 提示残留 `//`。
21. **DevTools 控制台单次粘贴约 8000 字符会被截断**（同上那次）：9878 字符的 fill.js
    粘进去只剩 ~8028，截断处正好在 `function pick(p){`，报的也是 `Unexpected end of input`，
    极易误判成语法写错。→ 生成时按 `--max-chars 7000` 分块，`clip.ps1 set -Strict` / `send.ps1` 超长直接拒绝。
22. **DevTools 面板的键盘焦点不跟顶层窗口走**（同上那次）：`SetForegroundWindow(Edge)` 之后
    按键仍可能全落到网页上。点提示行、`Ctrl+Shift+J`、`F12` 关掉重开——都出现过“一次好一次坏”。
    屏幕上看不出区别，**只能用 `ping.ps1` 判定**，不要靠截图猜。
23. **探针不能自我匹配**：`ping.ps1` 第一版把 `copy("PING <token>")` 放上剪贴板，轮询时匹配到了
    payload 自己，于是永远 `PING_OK`。标记必须在页面里现场拼（`"PIN"+"G <token>"`），
    并排除 `$c -eq $payload`。**写探针先问一句：它会不会自己满足自己？**
24. **临时脚本不要硬编码窗口句柄**：那次写的 `key/key2/inj1/inj2/planb` 五个脚本都写死 `1640922`，
    Edge 一重启全废。→ 统一用 `_win.ps1` 的 `Find-EdgeWindow` 动态找。

---

## 脚本清单

| 脚本 | 作用 |
|---|---|
| `scripts/browser.ps1` | **R2 主通道开关**：`doctor`（探活+路径）· `ensure`（起自动化 Edge，幂等）· `start` · `stop`（按 profile 精确杀进程，不碰用户浏览器）· `status`（探活+登录态）· `login`（首次扫码登录）· `goto -Url` · `profile`（打印 profile/端口/node 路径） |
| `scripts/cdp.mjs` | **R2 执行器**（零依赖，Node 22+ 全局 WebSocket）：`health` · `targets` · `goto` · `eval --file/--expr/--save/--shot` · `click` · `cookies` · `shot`；内置 `copy()` 兼容层，老脚本不用改 |
| `scripts/submit.js` | **R2 提交器**：点「提交」→ 等确认弹窗 → 点「确定」，只点肯定按钮，返回 `SUBMITTED/ALREADY_DONE/NO_SUBMIT_BUTTON/CONFIRM_TIMEOUT` |
| `scripts/pw_fallback.py` | **R1 后备**（Playwright）：同一个 user-data-dir，`--goto/--file/--expr/--save/--shot/--login/--match` |
| `scripts/fix_bom.py` | **修 .ps1 编码**：确保「UTF-8 带 BOM + CRLF」(`--dir scripts`)。改完任何 .ps1 都先跑它 |
| `scripts/probe.ps1` | MCP 方案通道判定（**仅 R2+R1 都失败时用**） |
| `scripts/ping.ps1` | **控制台探针**：`copy("PIN"+"G <token>")` → 轮询剪贴板，一次判定「粘贴+执行+copy 回读」全链路；`-Auto` 可自注入 |
| `scripts/send.ps1` | **通用注入**：动态找窗口 → 聚焦控制台 → 清输入 → 粘贴 → 回车 → 回读；超 7000 字符直接拒绝（exit 8） |
| `scripts/_win.ps1` | 共享工具（被 ping/send 点源）：`Find-EdgeWindow` / `Focus-Edge` / `Send-Combo` / `Click-At` / `Read-JsFile` |
| `scripts/clip.ps1` | **剪贴板读写**：`set <file>`（去 BOM + 压单行 + 超长/`//` 告警，`-Strict` 超长 exit 8）/ `get [out]` / `len` |
| `scripts/extract_dom.js` | **控制台提取题目**：输出 schema 同 `parse_work_html.py`，结果 `copy()` 到剪贴板 |
| `scripts/win.ps1` | 窗口操作：`tabs` / `select-tab` / `url` / `text` / `dump` / `clip`（**仅 UIA_OK 时可用**） |
| `scripts/inject.ps1` | 旧版一条命令注入（**UIA_OK 时**才有效；已被 `send.ps1` 取代） |
| `scripts/parse_work_html.py` | dowork 页 HTML/dump → `questions.json`；`--summary` / `--list-images` / `--answers-template` |
| `scripts/make_fill_js.py` | `questions.json` + `answers.json` → `fill.js` / `--verify` → `verify.js`；**自动剥 `//` 注释、压单行、按 `--max-chars 7000` 分块**；漏答检查、空数校验、隐藏域回读 |
| `scripts/dl_imgs.mjs` | 并发下载公式/图片选项（Node 直连，绕开 schannel） |
| `scripts/api_client.py` | 遗留备用：cookie 复用 + API（本机 cookie 取不到，通常不用） |
| `scripts/dom_extract.py` | 遗留备用：通用 DOM → 题目 JSON（`use_dom` 本机不可用） |

**退出码**：`0` 成功 · `2` 用法错误 · `3` 未发现题目 · `4` 输入为空 · `5` 需要登录 · `6` HTTP 错误 · `7` 参数/IO/漏答 · `8` 脚本超长（需分块） · `9` 通道不通（ping 超时）。

**依赖**（按通道）：

| 通道 | 依赖 |
|---|---|
| **R2（默认）** | Node 22+（只靠全局 `WebSocket`，**零 npm 依赖**）+ Windows PowerShell 5.1 + 专用 Edge profile |
| **R1（后备）** | Python 3 + `playwright`（本机已装 1.64.1）+ 同一个 Edge profile |
| **MCP 原方案** | Python 3 标准库 + Node + PowerShell 5.1 + MCP（windows-mcp） |

专用 profile：`%LOCALAPPDATA%\dsh-homework\edge-profile`（R2/R1 共用，同一时刻只能被一个实例占用 → 换通道前先 `browser.ps1 stop`）。

**环境注意**：
- 本机没有 `pwsh`（PowerShell 7），只有 `powershell`（5.1），一律 `powershell -File`。
- Chromium 系进程在沙箱里起不来（子进程走命名管道被禁）——`browser.ps1 ensure` 需要完全的文件权限。
- 改完任何 `.ps1` 先跑 `py scripts/fix_bom.py --dir scripts`。
- `py scripts/make_fill_js.py` 读文件用 `utf-8-sig`（兼容 PowerShell 写出的 BOM）。
