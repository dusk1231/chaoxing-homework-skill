# chaoxing-homework-skill

学习通（超星 Chaoxing）作业的 AI 助手自动作答 skill：**一次 JS 注入批量填写，杜绝逐题点击**。

已在真实作业上跑通：第 3 章 43 题、第 5 章 40 题、二元关系 10 题、CSS 理论 70 题。

## 这是什么

一个给 AI 编码助手（DeepSeek Harness / DSH 等，支持 skill 机制的均可）使用的可复用 skill：

- **SKILL.md** —— 给 AI 看的完整操作手册：通道判定、注入流程、题型矩阵、24 条踩坑记录
- **scripts/** —— 纯本地脚本（零 npm 依赖，Python 标准库 + Node 22+ 内置 WebSocket + PowerShell 5.1）

AI 负责「读题 → 解题 → 看公式图片」，脚本负责「取题 → 填写 → 提交」的机械搬运。

## 工作原理

```
browser.ps1 ensure        # 起一个带 CDP 调试端口的专属 Edge profile（登录一次，之后复用）
browser.ps1 goto <url>    # 打开作业页
cdp.mjs eval extract      # 一次 evaluate 取出全部题目结构（qid / 选项 data / 编辑器 id）
（AI 离线解题 → answers.json）
make_fill_js.py           # 生成一次性注入脚本（自动压行、剥注释、超长自动分块）
cdp.mjs eval fill.js      # 一次执行填完所有题，回读隐藏域 /h= 逐题校验
cdp.mjs eval submit.js    # 点提交 → 确认弹窗一把过 → 截图留证
```

核心是 **CDP（Chrome DevTools Protocol）直连**：不碰键盘焦点、不碰剪贴板、不用截图找坐标，
绕开了 UI 自动化最常见的三类故障。另有 Playwright 后备通道（R1）和 UIA+键盘注入兜底通道（MCP）。

## 题型支持

单选 / 多选 / 判断 / 填空（含多空）/ 简答、设计大题（HTML），全部实测通过。

## 安装

```powershell
# 复制到你的 skill 目录
git clone https://github.com/dusk1231/chaoxing-homework-skill.git "$env:USERPROFILE\.dsh\skills\homework"
```

对 AI 助手说「帮我写学习通作业」即可触发（触发词：学习通、超星、作业、homework、chaoxing…）。

首次使用需在弹出的 Edge 窗口里扫码登录一次学习通（cookie 存于独立 profile，之后自动复用）。

## 前置要求

| 通道 | 依赖 |
|---|---|
| R2（默认） | Node 22+、Windows PowerShell 5.1 |
| R1（后备） | Python 3 + `playwright` |
| MCP（兜底） | Python 3 标准库 + windows-mcp |

## 免责声明

本工具仅用于辅助完成本人账号下有权作答的课程作业，答案由使用者（或其 AI 助手）自行计算生成。
请遵守所在学校/机构的学术规范，使用者对任何使用方式及其后果自行负责。

## License

MIT
