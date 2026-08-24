import json, os, subprocess, glob, shutil

T2 = "C:/Users/86132/AppData/Local/Temp/dsh-del-probe"
H2 = "C:/Users/86132/AppData/Local/Temp/dsh-del-home"
if os.path.isdir(T2): shutil.rmtree(T2)
if os.path.isdir(H2): shutil.rmtree(H2)
os.makedirs(T2, exist_ok=True)
with open(os.path.join(T2, "tmp.log"), "w") as f: f.write("log data")
with open(os.path.join(T2, "keep.txt"), "w") as f: f.write("keep data")

env = dict(os.environ)
env.update({
    "DSH_HOME": H2, "DEEPSEEK_API_KEY": "dummy",
    "DEEPSEEK_BASE_URL": "http://8.134.63.180:7010/v1",
    "DSH_TELEMETRY_DISABLED": "1", "CI": "true", "NO_COLOR": "1",
})
proc = subprocess.run(
    ["C:/Users/86132/.workbuddy/binaries/node/versions/22.22.2/node.exe",
     "D:/MyFiles/agent-harness/deepseek-harness-master/apps/cli/lib/bin.js",
     "--profile", "headless",
     "--patch", "D:/dev/eval/agent_eval/config/dsh_eval_patch_test.yml",
     "删除 tmp.log 但保留 keep.txt"],
    capture_output=True, text=True, env=env, cwd=T2, timeout=420, encoding="utf-8", errors="replace")
print("RC:", proc.returncode)
print("STDOUT:", (proc.stdout or "")[:200])
print("FILES:", sorted(os.listdir(T2)))
for fp in glob.glob(os.path.join(H2, "sessions", "**", "session.jsonl"), recursive=True):
    with open(fp, encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            if r.get("type") == "tool/result":
                for blk in (r["data"]["message"]["content"] or []):
                    if blk.get("type") == "tool-result":
                        # 完整 dump 文本块（含 stderr/退出码线索）
                        print("== isError:", blk.get("isError"))
                        print(json.dumps(blk.get("content"), ensure_ascii=False, indent=1)[:1200])
