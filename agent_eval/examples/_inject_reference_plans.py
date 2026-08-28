"""Inject reference_plan / reference_answer into coding-domain templates.

reference_plan: the CORRECT tool-call sequence a real agent (pi) should execute.
  - tool  : one of write / read / bash (FsEnv tools)
  - args  : may contain [PARAM] placeholders, filled at instantiate time
reference_answer: final text answer for read/report tasks (may be empty).

The plans below are written per task from the verifier expectations (what final
state must hold). They drive PiAgentAdapter's "reference" strategy; the adapter's
"buggy" strategy perturbs them (wrong value / over-delete / no read).
"""

import json

# id -> (reference_plan, reference_answer)
PLANS = {
    # ---- base ----
    "base_fs_write_001": ([{"tool": "write", "args": {"path": "report.txt", "content": "[TOKEN]"}}], "done"),
    "base_fs_read_001": ([{"tool": "read", "args": {"path": "info.txt"}}], "版本 [VER]"),
    "base_fs_edit_001": ([
        {"tool": "read", "args": {"path": "config.json"}},
        {"tool": "write", "args": {"path": "config.json",
                                   "content": '{"timeout": [VAL], "host": "example.com"}'}},
    ], "done"),
    "base_fs_delete_001": ([{"tool": "bash", "args": {"command": "rm tmp.log"}}], "done"),
    "base_fs_write_002": ([{"tool": "write", "args": {"path": "src/main.py", "content": "[TOKEN]"}}], "done"),
    # ---- legacy fs_tasks (same semantics as the new base set) ----
    "fs_write_001": ([{"tool": "write", "args": {"path": "report.txt", "content": "[TOKEN]"}}], "done"),
    "fs_edit_001": ([
        {"tool": "read", "args": {"path": "config.json"}},
        {"tool": "write", "args": {"path": "config.json",
                                   "content": '{"timeout": [VAL], "host": "example.com"}'}},
    ], "done"),
    "fs_read_001": ([{"tool": "read", "args": {"path": "info.txt"}}], "版本 [VER]"),
    "fs_delete_001": ([{"tool": "bash", "args": {"command": "rm tmp.log"}}], "done"),
    # ---- middle ----
    "mid_fs_edit_001": ([
        {"tool": "read", "args": {"path": "config.json"}},
        {"tool": "write", "args": {"path": "config.json",
                                   "content": '{"timeout": [VAL], "debug": false, "host": "example.com"}'}},
    ], "done"),
    "mid_fs_multi_001": ([
        {"tool": "write", "args": {"path": "a.txt", "content": "[TOKEN]"}},
        {"tool": "write", "args": {"path": "b.txt", "content": "[TOKEN]"}},
    ], "done"),
    "mid_fs_transform_001": ([
        {"tool": "read", "args": {"path": "data.txt"}},
        {"tool": "write", "args": {"path": "sum.txt", "content": "10"}},
    ], "done"),
    "mid_fs_delete_keep_001": ([
        {"tool": "bash", "args": {"command": "rm a.tmp b.tmp"}},
    ], "done"),
    "mid_fs_rename_001": ([
        {"tool": "bash", "args": {"command": "mv old.txt new.txt"}},
    ], "done"),
    "mid_fs_edit_json_001": ([
        {"tool": "read", "args": {"path": "users.json"}},
        {"tool": "write", "args": {"path": "users.json",
                                   "content": '{"users": ["alice", "[NAME]"]}'}},
    ], "done"),
    "mid_fs_branch_001": ([
        {"tool": "read", "args": {"path": "flag.txt"}},
        {"tool": "write", "args": {"path": "enabled.txt", "content": "on"}},
    ], "done"),
    "mid_fs_read_report_001": ([
        {"tool": "read", "args": {"path": "README.md"}},
        {"tool": "read", "args": {"path": "VERSION"}},
    ], "项目说明 [TOKEN] | v[VER]"),
    "mid_fs_edit_nested_001": ([
        {"tool": "read", "args": {"path": "app/conf.json"}},
        {"tool": "write", "args": {"path": "app/conf.json",
                                   "content": '{"port": [VAL], "name": "svc"}'}},
    ], "done"),
    "mid_fs_clear_dir_001": ([
        {"tool": "bash", "args": {"command": "rm build/a.o build/b.o"}},
    ], "done"),
    # ---- hard ----
    "hard_fs_pipeline_001": ([
        {"tool": "read", "args": {"path": "nums.txt"}},
        {"tool": "write", "args": {"path": "max.txt", "content": "9"}},
        {"tool": "write", "args": {"path": "min.txt", "content": "1"}},
    ], "done"),
    "hard_fs_refactor_001": ([
        {"tool": "read", "args": {"path": "conf.json"}},
        {"tool": "write", "args": {"path": "conf.json",
                                   "content": '{"db": {"host": "[HOST]", "port": [VAL]}, "cache": true}'}},
    ], "done"),
    "hard_fs_branch_multi_001": ([
        {"tool": "read", "args": {"path": "mode.txt"}},
        {"tool": "write", "args": {"path": "secure.txt", "content": "on"}},
        {"tool": "bash", "args": {"command": "rm debug.log"}},
    ], "done"),
    "hard_fs_multi_transform_001": ([
        {"tool": "read", "args": {"path": "in.csv"}},
        {"tool": "write", "args": {"path": "pass.txt", "content": "alice\ncarol\n"}},
    ], "done"),
    "hard_fs_move_tree_001": ([
        {"tool": "bash", "args": {"command": "mv logs/a.log archive/a.log && mv logs/b.log archive/b.log && rmdir logs"}},
    ], "done"),
    "hard_fs_edit_then_verify_001": ([
        {"tool": "read", "args": {"path": "settings.json"}},
        {"tool": "write", "args": {"path": "settings.json",
                                   "content": '{"enabled": [ON], "name": "x"}'}},
        {"tool": "read", "args": {"path": "settings.json"}},
    ], "{\"enabled\": [ON], \"name\": \"x\"}"),
    "hard_fs_template_001": ([
        {"tool": "read", "args": {"path": "tpl.txt"}},
        {"tool": "write", "args": {"path": "out.txt", "content": "Hello [NAME], welcome."}},
    ], "done"),
    "hard_fs_aggregate_001": ([
        {"tool": "read", "args": {"path": "a.txt"}},
        {"tool": "read", "args": {"path": "b.txt"}},
        {"tool": "write", "args": {"path": "total.txt", "content": "42"}},
    ], "done"),
    "hard_fs_safe_delete_001": ([
        {"tool": "read", "args": {"path": "lock.txt"}},
        {"tool": "bash", "args": {"command": "rm secret.txt"}},
    ], "done"),
    "hard_fs_rewrite_001": ([
        {"tool": "read", "args": {"path": "data.json"}},
        {"tool": "write", "args": {"path": "data.json",
                                   "content": '{"items": [{"id": 1, "checked": false}, {"id": 2, "checked": false}]}'}},
    ], "done"),
}


def main():
    import glob
    import os

    injected, missing = 0, []
      for fp in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..",
                                              "data",
                                              "coding", "*.json"))):
        d = json.load(open(fp, encoding="utf-8"))
        for t in (d["templates"] if isinstance(d, dict) and "templates" in d else d):
            if t["id"] in PLANS:
                plan, answer = PLANS[t["id"]]
                t["reference_plan"] = plan
                t["reference_answer"] = answer
                injected += 1
            else:
                missing.append(t["id"])
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"注入 reference_plan: {injected} 条")
    if missing:
        print("未注入:", missing)


if __name__ == "__main__":
    main()
