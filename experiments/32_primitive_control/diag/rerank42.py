import json, gzip, sys, copy
sys.path.insert(0, '/home/user/nikke-opt'); sys.path.insert(0, '/home/user/nikke-opt/experiments/31_recent_seasons')
from nikke_opt.evaluator import EvalRequest, make_evaluator
import run31
src = open('/home/user/nikke-opt/experiments/32_primitive_control/diag/rotate10.py').read()
exec(src.split('out = {}')[0].split('import run31')[1])
S = 42
seen = {}
for f in ('B_s0', 'B_s1'):
    for l in gzip.open(f'/home/user/nikke-opt/experiments/31_recent_seasons/run_log/S{S}/{f}.jsonl.gz', 'rt'):
        if l.strip():
            r = json.loads(l)
            if r['total_damage']: seen[tuple(r['squad'])] = r['total_damage'] / 1e8
aff = [q for q in seen if rotate_patterns(list(q))]
with make_evaluator('rust', jobs=4, cache=False) as ev:
    res = ev.evaluate([EvalRequest(list(q), boss=None, options=opt(S, rotate_patterns(list(q)))) for q in aff])
new = dict(seen)
for q, r in zip(aff, res): new[q] = r.total_damage / 1e8
json.dump({'old': [[list(q), v] for q, v in seen.items()], 'new': [[list(q), v] for q, v in new.items()]},
          open('/home/user/nikke-opt/experiments/32_primitive_control/diag/rerank42.json', 'w'), ensure_ascii=False)
print('done', len(seen), len(aff), ev.sim_count)
