import json, sys
sys.path.insert(0, "D:/dev/eval/agent_eval")
from agent_eval.opencode_adapter import OpenCodeAgentAdapter
from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.environments.env import Env

reg = DatasetRegistry.from_dirs("D:/dev/eval/agent_eval/agent_eval/datasets/data/coding")
inst = reg.instantiate("base_fs_write_001", seed=0)
env = Env(inst.setup, backend="disk")
print("cwd:", env.cwd, flush=True)
a = OpenCodeAgentAdapter()
traj = a.run(inst, env)
print("STEPS:", json.dumps([s.action for s in traj.steps], ensure_ascii=False), flush=True)
print("ANSWER:", json.dumps(traj.answer, ensure_ascii=False), flush=True)
state = env.get_state()
print("STATE:", json.dumps(state, ensure_ascii=False), flush=True)
env.cleanup()
