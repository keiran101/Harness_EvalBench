import json, sys
sys.path.insert(0, "D:/dev/eval/agent_eval")
from agent_eval.opencode_adapter import OpenCodeAgentAdapter
from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.environments.env import Env

reg = DatasetRegistry.from_dirs("D:/dev/eval/agent_eval/agent_eval/datasets/data/coding")
inst = reg.instantiate("base_fs_write_001", seed=0)
env = Env(inst.setup, backend="disk")
a = OpenCodeAgentAdapter()
result = a._call_cli(env.cwd, inst.instruction)
print("STEPS:", len(result.get("steps", [])), flush=True)
print("ANSWER:", json.dumps(result.get("answer"), ensure_ascii=False), flush=True)
print("ERROR:", json.dumps(result.get("error"), ensure_ascii=False)[:800], flush=True)
print("STATE:", json.dumps(env.get_state(), ensure_ascii=False), flush=True)
env.cleanup()
