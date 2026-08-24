import json, sys
sys.path.insert(0, "D:/dev/eval/agent_eval")
from agent_eval.deepseek_adapter import DeepSeekHarnessAdapter
from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.environments.env import Env

reg = DatasetRegistry.from_dirs("D:/dev/eval/agent_eval/agent_eval/datasets/data/coding")
inst = reg.instantiate("base_fs_delete_001", seed=0)
env = Env(inst.setup, backend="disk")
print("cwd:", env.cwd, flush=True)
a = DeepSeekHarnessAdapter()
result = a._call_cli(env.cwd, inst.instruction)
print("ANSWER:", json.dumps(result.get("answer"), ensure_ascii=False), flush=True)
print("ERROR:", json.dumps(result.get("error"), ensure_ascii=False), flush=True)
print("STEPS:", json.dumps(result.get("steps"), ensure_ascii=False), flush=True)
print("STATE:", json.dumps(env.get_state(), ensure_ascii=False), flush=True)
env.cleanup()
