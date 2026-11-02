"""랭커 덱(5명 집합)마다 실전 딜 중앙값과 계산 값(기본 · B1/B2 새 규칙)을 나란히 본다."""
import json, sys, statistics as st
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, '/home/user/nikke-opt/experiments/31_recent_seasons')
import seasons31
an = Path('/home/user/jgaram/nikke-analysis')
D = seasons31.Data31(an)
R = json.load(open('/home/user/nikke-opt/experiments/32_primitive_control/diag/rotate10.json'))
out = {}
for s in seasons31.SEASONS:
    end = D.seasons[s]['end_at']
    real = defaultdict(list)
    for p in D.ranks(s):
        for t in p['teams']:
            names = [D.to_eval(en, end) for en in t['characters']]
            if any(n[0] in '?!' for n in names): continue
            real[frozenset(names)].append(t['damage'] / 1e8)
    calc = {frozenset(k.split(',')): (k, v) for k, v in R[str(s)]['vals'].items()}
    rows = []
    for fs, ds in real.items():
        if fs in calc and len(ds) >= 10:
            k, v = calc[fs]
            rows.append({'deck': k, 'n': len(ds), 'real': st.median(ds), 'base': v['base'], 'rot': v['rot']})
    out[s] = rows
json.dump(out, open('/home/user/nikke-opt/experiments/32_primitive_control/diag/real_vs_calc.json', 'w'), ensure_ascii=False, indent=1)
