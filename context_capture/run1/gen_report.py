# -*- coding: utf-8 -*-
import json, os

BASE = r"D:\dev\eval\context_capture\run1"
FILES = {
    "PI":       os.path.join(BASE, "pi",  "fs_write_001", "000002_20260826T005305519654.json"),
    "OpenCode": os.path.join(BASE, "oc",  "fs_write_001", "000004_20260826T005952562889.json"),
    "DeepSeek": os.path.join(BASE, "dsh", "fs_write_001", "000005_20260826T010143263386.json"),
}

def load(name):
    d = json.load(open(FILES[name], encoding="utf-8"))
    return d["request"], d

data = {n: load(n) for n in FILES}
reqs = {n: data[n][0] for n in FILES}
raws = {n: data[n][1] for n in FILES}

def get_tools(req):
    out = {}
    for t in req.get("tools", []):
        fn = t.get("function", t)
        nm = fn.get("name")
        params = fn.get("parameters", fn.get("input_schema", {})) or {}
        out[nm] = {
            "description": (fn.get("description") or "").strip(),
            "properties": params.get("properties", {}),
            "required": params.get("required", []),
        }
    return out

tools = {n: get_tools(reqs[n]) for n in FILES}
systems = {n: next((m["content"] for m in reqs[n].get("messages", []) if m["role"] == "system"), "") for n in FILES}
users = {n: [m for m in reqs[n].get("messages", []) if m["role"] == "user"] for n in FILES}

L = []
def w(s=""): L.append(s)

w("# 三套 Agent Harness 输入 Context 逐字段对比报告")
w()
w("> 任务：`fs_write_001`（disk 后端，写 `report.txt`）。")
w("> 捕获方式：统一 LLM 反向代理（`capture_proxy.py`）在真实执行中逐请求落盘完整 request body。")
w("> 对比对象：PI（`pi_bridge.ts`，第 1 轮，bridge 在首次工具调用后 hang）；OpenCode（`opencode` 真实 agent 调用 seq=4）；DeepSeek（`deepseek-harness`，初始 context seq=5）。")
w()
w("---")
w()

# 1. 概览
w("## 1. 请求级概览对比")
w()
w("| 字段 | PI | OpenCode | DeepSeek (dsh) |")
w("|---|---|---|---|")
w(f"| system prompt 长度 | {len(systems['PI'])} 字符 | {len(systems['OpenCode'])} 字符 | {len(systems['DeepSeek'])} 字符 |")
nmsg = {n: len(reqs[n].get('messages', [])) for n in FILES}
w(f"| messages 轮数（首轮） | {nmsg['PI']}（system+user） | {nmsg['OpenCode']}（system+user） | {nmsg['DeepSeek']}（system+user+runtime-context user） |")
w(f"| 工具数量 | {len(tools['PI'])} | {len(tools['OpenCode'])} | {len(tools['DeepSeek'])} |")
w(f"| model 字段 | `{reqs['PI'].get('model')}` | `{reqs['OpenCode'].get('model')}` | `{reqs['DeepSeek'].get('model')}` |")
w(f"| max_tokens | {reqs['PI'].get('max_tokens')} | {reqs['OpenCode'].get('max_tokens')} | {reqs['DeepSeek'].get('max_tokens')} |")
w(f"| stream | {reqs['PI'].get('stream')} | {reqs['OpenCode'].get('stream')} | {reqs['DeepSeek'].get('stream')} |")
w(f"| temperature | {reqs['PI'].get('temperature')} | {reqs['OpenCode'].get('temperature')} | {reqs['DeepSeek'].get('temperature')} |")
w(f"| tool_choice | — | `{reqs['OpenCode'].get('tool_choice')}` | — |")
w(f"| thinking 字段 | — | — | `{json.dumps(reqs['DeepSeek'].get('thinking'))}` |")
w(f"| 旁路调用（标题生成） | 无 | 有（seq=3，先于 agent 调用） | 有（seq=6，776B） |")
w()
w("**关键观察**：三套人设措辞、`model` 取值、`max_tokens`、是否流式、是否带 `thinking`、是否发标题旁路调用——**全部不同**。PI 是唯一不流式、唯一 `temperature=0`、唯一无旁路的。")
w()
w("---")
w()

# 2. System 全文
w("## 2. System Prompt 全文")
w()
for n in FILES:
    w(f"### 2.{list(FILES).index(n)+1} {n}（{len(systems[n])} 字符）")
    w()
    w("```text")
    w(systems[n])
    w("```")
    w()

# 3. System 差异要点
w("---")
w("## 3. System Prompt 差异要点")
w()
w("| 维度 | PI | OpenCode | DeepSeek |")
w("|---|---|---|---|")
w("| 自我定位 | “expert coding assistant operating **inside pi**” | “**You are opencode**, an interactive CLI tool” | “AI agent powered by **DeepSeek Harness** / deepseek-v4-flash” |")
w("| 工具列举方式 | 在 system 内逐条列出 4 个工具名+用途 | system 内大段描写 9 个工具（含 `Available agent types`、Usage 段落） | system 内**不**逐条列工具，只讲通用 agent 规则 |")
w("| 运行时上下文注入 | 无独立 runtime context 段 | 无 | **有第 3 条 user 消息**专门注入 `Current runtime context`（cwd、OS、sandbox 策略） |")
w("| 安全/约束强调 | 轻量（“make changes directly…”） | 强：禁止猜测 URL、强调 Windows 环境、长段工具使用守则 | 强：sandbox 权限模型、子代理/后台任务规则、plan mode |")
w("| 环境假设 | 通用 bash 文件系统 | **明确 Windows / PowerShell 5.1** | **明确 Windows / pwsh**，并描述 sandbox 文件系统 |")
w("| 子代理/任务编排 | 无 | 有 `task` 子代理工具描述 | 大量：subagent / subagent_fork / ralph / workflow / goal / job_* |")
w()
w("**结论**：PI 的 system 最短（2595 字符）且“工具即 system 内文本”；OpenCode 最长（8909 字符，把工具使用守则写进 system）；DeepSeek 居中（4316 字符），但把运行时上下文分离到**独立的 user 消息**而非 system——这是三者在“context 组织结构”上最本质的分歧。")
w()
w("---")
w()

# 4. 工具清单矩阵
all_tools = sorted(set(tools['PI']) | set(tools['OpenCode']) | set(tools['DeepSeek']))
w("## 4. 工具清单对比矩阵")
w()
w("| 工具名 | PI | OpenCode | DeepSeek | 备注 |")
w("|---|---|---|---|---|")
for t in all_tools:
    p = "✅" if t in tools['PI'] else "—"
    o = "✅" if t in tools['OpenCode'] else "—"
    d = "✅" if t in tools['DeepSeek'] else "—"
    note = ""
    if t == "edit" and len(tools['OpenCode']['edit']['properties']) == 0:
        note = "OC 的 edit schema 被 slim 插件清空（无参数定义）"
    if t in ("bash",) and "pwsh" in tools['DeepSeek']:
        note = "DSH 对应物为 `pwsh`（PowerShell）"
    if t in ("read","edit","write") and "sandbox_permissions" in tools['DeepSeek'][t]['properties']:
        note = "DSH 额外带 sandbox_permissions + justification"
    w(f"| `{t}` | {p} | {o} | {d} | {note} |")
w()
w(f"共 {len(all_tools)} 个去重工具：PI {len(tools['PI'])} / OC {len(tools['OpenCode'])} / DSH {len(tools['DeepSeek'])}。三者**完全共有**的工具仅 `read / write` 两个；`edit` 三家都有但 schema 形同陌路；`bash` 仅 PI/OC 有，DSH 改名为 `pwsh`。")
w()
w("---")
w()

# 5. 核心文件工具 schema 逐字段对比
w("## 5. 核心文件工具 Schema 逐字段对比")
w()
core = ["read", "edit", "write", "bash"]
mapping = {
    "read": {"PI":"read","OpenCode":"read","DeepSeek":"read"},
    "edit": {"PI":"edit","OpenCode":"edit","DeepSeek":"edit"},
    "write":{"PI":"write","OpenCode":"write","DeepSeek":"write"},
    "bash": {"PI":"bash","OpenCode":"bash","DeepSeek":"pwsh"},
}
for label, mp in mapping.items():
    w(f"### 5.{list(core).index(label)+1} `{label}`")
    w()
    # param union
    paramsets = {}
    for h, tname in mp.items():
        if tname in tools[h]:
            paramsets[h] = tools[h][tname]
    allp = sorted(set().union(*[set(p["properties"].keys()) for p in paramsets.values()])) if paramsets else []
    w("| 参数 | " + " | ".join(f"{h}（`{mp[h]}`)" for h in mp) + " |")
    w("|---|" + "|".join(["---"]*len(mp)) + "|")
    for pp in allp:
        row = []
        for h in mp:
            tname = mp[h]
            if tname in tools[h]:
                props = tools[h][tname]["properties"]
                if pp in props:
                    ptype = props[pp].get("type", "?")
                    reqd = "✓" if pp in tools[h][tname]["required"] else ""
                    row.append(f"{ptype}{('·必填' if reqd else '')}")
                else:
                    row.append("—")
        w(f"| `{pp}` | " + " | ".join(row) + " |")
    # description diff
    w()
    w("**description 差异：**")
    for h in mp:
        tname = mp[h]
        if tname in tools[h]:
            w(f"- **{h}**：{tools[h][tname]['description'][:160]}")
    w()

# 6. 工具 schema 差异要点
w("---")
w("## 6. 工具 Schema 差异要点")
w()
w("1. **参数命名三套三样**（最刺眼的差异）：")
w("   - 文件路径参数：PI=`path` / OpenCode=`filePath` / DeepSeek=`file_path`。")
w("   - 文本替换：PI 用 `edits[]` 数组（`oldText`+`newText`）；OpenCode 的 `edit` 被清空为无参；DeepSeek 用单次 `old_string`+`new_string`+`replace_all`。")
w("2. **OpenCode 的 `edit`/`glob`/`grep`/`task`/`todowrite`/`webfetch` schema 参数为空**——这是 slim 插件（`config/opencode_slim.ts`）裁剪 tool definition 的副作用：hook 只保留了 jsonSchema 的壳，把 properties 清空，导致模型拿不到参数说明（功能靠 system 文本兜底）。")
w("3. **DeepSeek 给写类/执行类工具强加治理字段**：`write`/`edit`/`pwsh` 都带 `sandbox_permissions` 和 `justification`（需说明“为何需要此权限”），这是 DSH 独有的一套 sandbox 权限模型，PI/OC 完全没有。")
w("4. **bash 语义重定向**：PI/OC 的 `bash` 是通用 shell；DSH 改名为 `pwsh` 且强制 PowerShell，并多了 `description`/`timeoutMs`/`workdir`/`run_in_background` 等执行控制字段。OC 的 `bash` description 写明“Windows PowerShell (5.1)”。")
w("5. **工具面广度天差地别**：PI 4 个（纯文件操作）；OC 9 个（文件+搜索+任务子代理）；DSH 25 个（在 OC 基础上再叠加 goal/job/子代理编排/workflow/skill/联网搜索/读图）。DSH 把“agent 编排原语”直接做成工具。")
w("6. **`read` 能力**：PI/DSH 支持 `offset`/`limit` 与读图（DSH 另有 `read_image`）；OC 的 `read` 只有 `filePath` 一个参数（无分页）。")
w()
w("---")
w()

# 7. 其他请求级差异
w("## 7. 其他请求级差异")
w()
w("- **model 字段值**：PI/OC 都如实填 `google/gemma-4-12b-qat`（本地端点模型）；DSH 填的是自己的 `deepseek-v4-flash`——即 harness 按自身身份声明模型名，端点并不校验。")
w("- **max_tokens**：PI=2048（最小，留给定量输出）；OC=32000；DSH=256000。DSH 预留了极大生成窗口。")
w("- **stream**：PI 关流式（`stream` 字段缺失）；OC/DSH 开流式并带 `stream_options`。")
w("- **tool_choice**：仅 OC 显式设 `tool_choice`（强制工具调用）；另两者未设。")
w("- **thinking**：仅 DSH 在请求体带 `thinking` 字段（推理开关），端点会忽略但不报错。")
w("- **消息结构**：DSH 多出第 3 条 user 消息（`Current runtime context`），把环境/cwd/sandbox 策略作为独立消息注入；PI/OC 仅 system+user。")
w()
w("---")
w()
w("## 8. 附：核心工具完整 Schema（紧凑 JSON）")
w()
for label, mp in mapping.items():
    w(f"### `{label}`")
    w()
    for h in mp:
        tname = mp[h]
        if tname in tools[h]:
            w(f"**{h} / `{tname}`**")
            w("```json")
            w(json.dumps({"description": tools[h][tname]["description"],
                          "parameters": {"properties": tools[h][tname]["properties"],
                                         "required": tools[h][tname]["required"]}},
                         ensure_ascii=False, indent=2)[:1500])
            w("```")
            w()

out = "\n".join(L)
outpath = os.path.join(BASE, "context_comparison_report.md")
with open(outpath, "w", encoding="utf-8") as f:
    f.write(out)
print("written:", outpath, "bytes:", len(out.encode("utf-8")))
print("all_tools:", len(all_tools))
