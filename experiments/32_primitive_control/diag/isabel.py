import json, sys, copy
sys.path.insert(0, '/home/user/nikke-opt'); sys.path.insert(0, '/home/user/nikke-opt/experiments/31_recent_seasons')
from nikke_opt.evaluator import EvalRequest, make_evaluator
import run31
S = int(sys.argv[1]) if len(sys.argv) > 1 else 42
base = run31.options(S, 0)
def opt(patterns=None):
    o = copy.deepcopy(base)
    if patterns:
        ch = o.setdefault('chars', {})
        for n, p in patterns.items():
            ch.setdefault(n, {}).setdefault('control', {})['burst'] = {'pattern': p}
    return o
cases = json.loads(sys.argv[2])
reqs = [EvalRequest(tuple(sq), boss=None, options=opt(p)) for _, sq, p in cases]
with make_evaluator('rust', jobs=4, cache=False) as ev:
    res = ev.evaluate(reqs)
for (label, sq, p), r in zip(cases, res):
    mem = r.raw.get('members') if hasattr(r, 'raw') and isinstance(r.raw, dict) else None
    print(("%7.2f억" % (r.total_damage/1e8)) if r.total_damage else "  error", label, "" if r.error is None else json.dumps(r.error, ensure_ascii=False)[:300])
