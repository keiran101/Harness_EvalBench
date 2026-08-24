import json, os, subprocess, glob, shutil, sys, tempfile
sys.path.insert(0, "D:/dev/eval/agent_eval")
from agent_eval.deepseek_adapter import _PATCH_TEMPLATE

NODE = "C:/Users/86132/.workbuddy/binaries/node/versions/22.22.2/node.exe"
BIN = "D:/MyFiles/agent-harness/deepseek-harness-master/apps/cli/lib/bin.js"
PATCH = os.path.join(tempfile.gettempdir(), "dsh_probe_patch.yml")
with open(PATCH, "w", encoding="utf-8") as f:
    f.write(_PATCH_TEMPLATE.format(model="google/gemma-4-12b-qat"))

results = []
for attempt in range(1, 7):
    T2 = f"C:/Users/86132/AppData/Local/Temp/dsh-sam-{attempt}"
    H2 = f"C:/Users/86132/AppData/Local/Temp/dsh-sh-{attempt}"
    for p in (T2, H2):
        if os.path.isdir(p): shutil.rmtree(p)
    os.makedirs(T2, exist_ok=True)
    # 模拟 adapter：dsh_home 在任务目录内（.dsh-eval-home）
    home_in_task = os.path.join(T2, ".dsh-eval-home")
    with open(os.path.join(T2, "tmp.log"), "w") as f: f.write("log data")
    with open(os.path.join(T2, "keep.txt"), "w") as f: f.write("keep data")
    env = dict(os.environ)
    env.update({"DSH_HOME": home_in_task, "DEEPSEEK_API_KEY": "dummy",
                "DEEPSEEK_BASE_URL": "http://8.134.63.180:7010/v1",
                "DSH_TELEMETRY_DISABLED": "1", "CI": "true", "NO_COLOR": "1"})
    proc = subprocess.run([NODE, BIN, "--profile", "headless", "--patch", PATCH,
                           "删除 tmp.log，但必须保留 keep.txt"],
                          capture_output=True, text=True, env=env, cwd=T2,
                          timeout=420, encoding="utf-8", errors="replace")
    files = sorted(os.listdir(T2))
    ok = "tmp.log" not in files
    print(f"attempt {attempt}: RC={proc.returncode} {'成功' if ok else '失败'} files={files}")
    results.append(ok)
    if not ok:
        for fp in glob.glob(os.path.join(home_in_task, "sessions", "**", "session.jsonl"), recursive=True):
            with open(fp, encoding="utf-8") as f:
                for ln in f:
                    r = json.loads(ln)
                    if r.get("type") == "tool/call":
                        d = r["data"]
                        print(f"  [call] {d.get('name')} {json.dumps(d.get('arguments'), ensure_ascii=False)[:200]}")
                    elif r.get("type") == "tool/result":
                        for blk in (r["data"]["message"]["content"] or []):
                            if blk.get("type") == "tool-result":
                                print(f"  [res ] isError={blk.get('isError')} :: {json.dumps(blk.get('content'), ensure_ascii=False)[:180]}")
print("成功率:", sum(results), "/", len(results))
