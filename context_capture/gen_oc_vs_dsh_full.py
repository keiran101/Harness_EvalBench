import json, os

OUT = r"D:\dev\eval\context_capture\oc_vs_dsh_full_comparison.md"
OC = r"D:\dev\eval\context_capture\run_full_oc\oc\fs_write_001\000002_20260826T094038472464.json"
DSH = r"D:\dev\eval\context_capture\run1\dsh\fs_write_001\000005_20260826T010143263386.json"

def load(fp):
    return json.load(open(fp, encoding="utf-8"))["request"]

oc, dsh = load(OC), load(DSH)

def sys_of(req):
    return next((m["content"] for m in req.get("messages", []) if m["role"] == "system"), "")

def tools(req):
    out = {}
    for t in req.get("tools", []):
        fn = t.get("function", t)
        out[fn.get("name")] = fn
    return out

oc_tools, dsh_tools = tools(oc), tools(dsh)
oc_sys, dsh_sys = sys_of(oc), sys_of(dsh)

L = []
def w(s=""): L.append(s)

w("# 完整版 OpenCode vs 完整版 DeepSeek(dsh) — Context 逐字段对比")
w()
w(f"> 任务: `fs_write_001` (disk 后端, 写 `report.txt`)")
w(f"> OpenCode = `OPENCODE_SLIM=0` 全量 schema; DeepSeek = 默认全量 25 工具 (无 slim 机制)")
w(f"> 注: 两版 context 的 token 估算均远超本地端点 n_ctx=4096, 端点侧都会被截断 (模型实际只读约 4096 token)。")
w()
w("## 1. 请求级概览")
w()
w("| 字段 | OpenCode (完整) | DeepSeek (完整) |")
w("|---|---|---|")
w(f"| 主调用字节 | {len(json.dumps(oc,ensure_ascii=False))} | {len(json.dumps(dsh,ensure_ascii=False))} |")
w(f"| token 估算(len//4) | ~{len(json.dumps(oc,ensure_ascii=False))//4} | ~{len(json.dumps(dsh,ensure_ascii=False))//4} |")
w(f"| n_messages | {len(oc.get('messages',[]))} | {len(dsh.get('messages',[]))} |")
w(f"| system 字符 | {len(oc_sys)} | {len(dsh_sys)} |")
w(f"| n_tools | {len(oc_tools)} | {len(dsh_tools)} |")
w(f"| 工具参数 property 总数 | {sum(len(t.get('parameters',{}).get('properties',{})) for t in oc_tools.values())} | {sum(len(t.get('parameters',{}).get('properties',{})) for t in dsh_tools.values())} |")
w(f"| model | {oc.get('model')} | {dsh.get('model')} |")
w(f"| max_tokens | {oc.get('max_tokens')} | {dsh.get('max_tokens')} |")
w(f"| stream | {oc.get('stream')} | {dsh.get('stream')} |")
w(f"| temperature | {oc.get('temperature')} | {dsh.get('temperature')} |")
w(f"| tool_choice | {oc.get('tool_choice')} | {dsh.get('tool_choice')} |")
w(f"| 旁路调用 | 是 (title 生成, 无工具) | 是 (session title, 776B) |")
w()
w("**尺寸结论**: DeepSeek 比 OpenCode 大约 12% (34167 vs 30467 字节, ~8541 vs ~7616 tok)。")
w("两者都 > 4096 n_ctx, 端点都会截断。OpenCode 用更长的 system (8909) 承担工具守则, DeepSeek 用更短的 system (4316) + 多一条 runtime-context user 消息 + 近 3 倍工具数。")
w()
w("## 2. System Prompt 全文")
w()
w(f"### 2.1 OpenCode system ({len(oc_sys)} 字符)")
w()
w("```")
w(oc_sys)
w("```")
w()
w(f"### 2.2 DeepSeek system ({len(dsh_sys)} 字符)")
w()
w("```")
w(dsh_sys)
w("```")
w()
w("## 3. System 差异要点")
w()
w("| 维度 | OpenCode | DeepSeek |")
w("|---|---|---|")
w("| 长度 | 8909 | 4316 |")
w("| 定位 | opencode CLI 人设 + **完整工具使用守则**内联 | DeepSeek Harness agent 人设, **守则较简** |")
w("| 工具说明位置 | 大量写入 system 文本 | 主要靠 tools schema, system 只讲原则 |")
w("| 运行时上下文 | 无独立消息, 隐含在 system | **拆成第 3 条 user 消息** (cwd/OS/sandbox 策略) |")
w("| 文件操作约定 | 讲 PATH/Windows 适配 | 讲 sandbox_permissions 治理 |")
w()
w("## 4. 工具清单对比矩阵")
w()
oc_names, dsh_names = set(oc_tools), set(dsh_tools)
shared = sorted(oc_names & dsh_names)
only_oc = sorted(oc_names - dsh_names)
only_dsh = sorted(dsh_names - oc_names)
w(f"- **共有工具 ({len(shared)})**: {', '.join(shared)}")
w(f"- **仅 OpenCode ({len(only_oc)})**: {', '.join(only_oc)}")
w(f"- **仅 DeepSeek ({len(only_dsh)})**: {', '.join(only_dsh)}")
w()
w("| 工具 | OpenCode | DeepSeek |")
w("|---|---|---|")
for nm in sorted(oc_names | dsh_names):
    a = "✅" if nm in oc_tools else "—"
    b = "✅" if nm in dsh_tools else "—"
    w(f"| {nm} | {a} | {b} |")
w()
w("**结论**: 仅 5 个工具完全共有 (edit/glob/grep/read/write)。OpenCode 偏精简 CLI 工具集; DeepSeek 暴露 25 工具, 含大量 agent 编排能力 (subagent/subagent_fork/send_message/list_agents/job_*/create_goal/update_goal/skill/workflow/ralph) 与治理字段。")
w()
w("## 5. 核心工具 Schema 逐字段对比 (共有工具)")
w()
def params_of(name, d):
    t = d.get(name)
    if not t: return {}, t.get("description","") if t else ""
    p = t.get("parameters", {})
    return p.get("properties", {}), p.get("required", []), t.get("description","")

for nm in ["read", "edit", "write"]:
    oc_p, oc_r, oc_d = params_of(nm, oc_tools)
    dsh_p, dsh_r, dsh_d = params_of(nm, dsh_tools)
    w(f"### 5.{['read','edit','write'].index(nm)+1} `{nm}`")
    w()
    w(f"- OpenCode description: {oc_d[:120]}")
    w(f"- DeepSeek description: {dsh_d[:120]}")
    w()
    allp = sorted(set(oc_p) | set(dsh_p))
    w("| 参数 | OpenCode | DeepSeek |")
    w("|---|---|---|")
    for pp in allp:
        o = f"`{oc_p.get(pp,{}).get('type')}`" if pp in oc_p else "—"
        dd = f"`{dsh_p.get(pp,{}).get('type')}`" + (" (+sandbox_permissions/justification 治理)" if pp in dsh_p and nm in ("write","edit") else "")
        w(f"| {pp} | {o} | {dd} |")
    w(f"- required: OC={oc_r}  DSH={dsh_r}")
    w()

w("### 5.4 `bash`(OC) vs `pwsh`(DSH) — 外壳工具")
w()
oc_p, oc_r, oc_d = params_of("bash", oc_tools)
dsh_p, dsh_r, dsh_d = params_of("pwsh", dsh_tools)
w(f"- OpenCode `bash` description: {oc_d[:120]}")
w(f"- DeepSeek `pwsh` description: {dsh_d[:120]}")
w()
allp = sorted(set(oc_p) | set(dsh_p))
w("| 参数 | OpenCode `bash` | DeepSeek `pwsh` |")
w("|---|---|---|")
for pp in allp:
    o = f"`{oc_p.get(pp,{}).get('type')}`" if pp in oc_p else "—"
    dd = f"`{dsh_p.get(pp,{}).get('type')}`" + (" (+sandbox_permissions/justification)" if pp in dsh_p else "")
    w(f"| {pp} | {o} | {dd} |")
w(f"- required: OC={oc_r}  DSH={dsh_r}")
w()
w("## 6. 工具 Schema 核心差异")
w()
w("1. **参数命名**: OpenCode 用 camelCase (`filePath`, `old_string`, `new_string`, `replace_all`); DeepSeek 用 snake_case (`file_path`, `old_string`, `new_string`, `replace_all`)。")
w("2. **外壳工具名**: OpenCode `bash` / DeepSeek `pwsh` (PowerShell); 命令参数 OC=`command` / DSH=`code`。")
w("3. **治理字段**: DeepSeek 给 `write`/`edit`/`pwsh` 强加 `sandbox_permissions` + `justification`; OpenCode 无。")
w("4. **工具数/参数密度**: DSH 25 工具 / 65 属性 vs OC 9 工具 / 26 属性 — DSH 暴露的 agent 编排能力 (subagent/job/goal/skill) OC 完全没有。")
w("5. **system 与 tools 分工**: OC 把工具守则塞进 system (8909 字符); DSH 把守则压缩、运行时上下文独立成 user 消息, 工具 schema 自解释。")
w("6. **model 字段**: OC 用 eval 模型 `google/gemma-4-12b-qat`; DSH 硬编码 `deepseek-v4-flash` (adapter 内部转 DEEPSEEK_BASE_URL)。")
w()
w("## 7. 附录 — 完整 schema (紧凑 JSON)")
w()
w("### 7.1 OpenCode `write`")
w("```json")
w(json.dumps(oc_tools.get("write", {}), ensure_ascii=False, indent=2))
w("```")
w()
w("### 7.2 DeepSeek `write`")
w("```json")
w(json.dumps(dsh_tools.get("write", {}), ensure_ascii=False, indent=2))
w("```")
w()
w("### 7.3 OpenCode `read`")
w("```json")
w(json.dumps(oc_tools.get("read", {}), ensure_ascii=False, indent=2))
w("```")
w()
w("### 7.4 DeepSeek `read`")
w("```json")
w(json.dumps(dsh_tools.get("read", {}), ensure_ascii=False, indent=2))
w("```")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(L) + "\n")
print("written:", OUT, "lines:", len(L))
