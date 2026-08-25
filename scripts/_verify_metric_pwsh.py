import sys, json
sys.path.insert(0, 'agent_eval')
from agent_eval.metrics.process import retrieval_coverage


class S:
    def __init__(s, a): s.action = a
class T:
    def __init__(s, steps): s.steps = steps
class Inst:
    def __init__(s, g): s.gold_docs = g; s.env = {'backend': 'disk'}


def pwsh(cmd):
    return 'pwsh:' + json.dumps({'command': cmd}, ensure_ascii=False)


def show(name, gold, acts):
    r = retrieval_coverage(T([S(a) for a in acts]), Inst(gold))
    print('%-42s value=%.4f  %s' % (name, r['value'], r['detail']))


print('=== 回归：原验证脚本全用例 ===')
import subprocess
subprocess.run([sys.executable, 'scripts/_verify_metric.py'])

print()
print('=== PowerShell Get-Content 用例（deepseek 风格）===')
show('pwsh Get-Content tail (deepseek base007)', ['a.log', 'b.log', 'c.log'],
     [pwsh('Get-Content a.log -Tail 1'), pwsh('Get-Content b.log -Tail 1'),
      pwsh('Get-Content c.log -Tail 1')])
show('pwsh Get-Content -Path quoted', ['a.log'],
     [pwsh('Get-Content -Path "a.log" -Tail 1')])
show('pwsh gc alias + -Last', ['x.txt'],
     [pwsh('gc x.txt -Last 5')])
