import sys, json
sys.path.insert(0, 'agent_eval')
from agent_eval.metrics.process import retrieval_coverage


class S:
    def __init__(self, action): self.action = action
class T:
    def __init__(self, steps): self.steps = steps
class Inst:
    def __init__(self, gold): self.gold_docs = gold; self.env = {'backend': 'disk'}


def show(name, gold, actions):
    r = retrieval_coverage(T([S(a) for a in actions]), Inst(gold))
    print(f'{name:26s} value={r["value"]}  detail={r["detail"]}')


# JSON 格式 action 构造（真实 harness 风格，避免 shell 转义歧义）
def read(**kw): return 'read:' + json.dumps(kw, ensure_ascii=False)
def bash(cmd): return 'bash:' + json.dumps({'command': cmd}, ensure_ascii=False)

# case1: deepseek 反斜杠路径 spec\auth.md（JSON 双反斜杠 -> 单反）
show('1 deepseek backslash', ['spec/auth.md'],
     [read(file_path='spec\\auth.md')])
# case2: bash cat 多文件
show('2 bash cat multi', ['users.txt', 'orders.txt'],
     [bash('cat users.txt orders.txt')])
# case3: bash tail -n 1
show('3 bash tail -n 1', ['a.log'], [bash('tail -n 1 a.log')])
# case4: read 工具正常
show('4 read tool normal', ['docs/a.txt'], [read(path='docs/a.txt')])
# case5: ls/find 不计
show('5 ls/find ignored', ['docs/a.txt'], ['find docs -name "*.txt"', 'ls docs'])
# case6: opencode filePath
show('6 opencode filePath', ['docs/intro.md'], [read(filePath='docs/intro.md')])
# case7: 混合 反斜杠+bash+read
show('7 mixed', ['spec/auth.md', 'spec/api.md'],
     [bash('cat spec\\auth.md'), read(path='spec/api.md')])
# case8: head -n 5
show('8 head -n 5', ['migration.sql'], [bash('head -n 5 migration.sql')])
# case9: cat 管道 grep（只收 users.txt）
show('9 cat pipe grep', ['users.txt'], [bash('cat users.txt | grep foo')])
# case10: 裸 bash:cat 格式（pi 可能）
show('10 bare bash:cat', ['foo.txt'], ['bash:cat foo.txt'])
# case11: cat 多文件 + 通配符（通配符收但不影响具体文件）
show('11 cat glob', ['a.txt'], [bash('cat a.txt *.log')])
# case12: 未读全（部分覆盖）
show('12 partial', ['a.txt', 'b.txt', 'c.txt'], [read(path='a.txt'), read(path='b.txt')])
