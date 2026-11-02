"""10시즌 랭커 덱 · 우리 A 5덱을 기본 규칙과 「B1/B2도 앞에서부터 쿨 안 된 니케」 규칙으로 다시 평가한다(코어 없음)."""
import json, sys, copy
sys.path.insert(0, '/home/user/nikke-opt'); sys.path.insert(0, '/home/user/nikke-opt/experiments/31_recent_seasons')
from nikke_opt.evaluator import EvalRequest, make_evaluator
import run31
N = json.load(open('/home/user/nikke-calc-rs/upstream/data/parsed_nikke.json'))
LAYER_B1 = {'미란다', '츠바이', '토브'}
ALL = list(range(1, 40))
def rotate_patterns(sq):
    """같은 단계(1·2) 후보가 둘 이상이면 선두에 '모든 사이클' 패턴 → 후보 전체를 슬롯 순서로 본다(B3과 같은 규칙)."""
    pats = {}
    for st in ('1', '2'):
        c = [n for n in sq if N[n]['burst_stage'] == st]
        if len(c) < 2: continue
        if st == '1' and LAYER_B1 & set(c): continue          # 레이어가 전담 규칙을 이미 건다
        if '프리카' in c and '민트' in sq: continue
        if '마스트 : 로망틱 메이드' in c and any(N[n]['burst_cooldown'] <= 20 for n in c if n != '마스트 : 로망틱 메이드'): continue
        pats[c[0]] = ALL
    return pats
def opt(s, pats):
    o = copy.deepcopy(run31.options(s, 0))
    for n, p in pats.items():
        o.setdefault('chars', {}).setdefault(n, {}).setdefault('control', {})['burst'] = {'pattern': p}
    return o
out = {}
with make_evaluator('rust', jobs=4, cache=False) as ev:
    for s in run31.SEASONS:
        rk = run31.ranker_decks(s)
        A = json.load(open(run31.sdir(s) / 'maps.json'))['nocore|B']['reps'][0]['decks']
        groups = {'top_five': rk['top_five'], 'rank1': rk['rank1'], 'A': A, 'squads': rk['squads']}
        todo = sorted({tuple(q) for v in groups.values() for q in v if all(n[0] not in '?!' for n in q)})
        reqs = [EvalRequest(list(q), boss=None, options=opt(s, {})) for q in todo] + \
               [EvalRequest(list(q), boss=None, options=opt(s, rotate_patterns(q))) for q in todo]
        res = ev.evaluate(reqs)
        k = len(todo)
        vals = {','.join(q): {'base': res[i].total_damage / 1e8, 'rot': res[k + i].total_damage / 1e8, 'pats': list(rotate_patterns(q))} for i, q in enumerate(todo)}
        out[s] = {'groups': groups, 'vals': vals}
        def tot(g, key): return sum(vals[','.join(q)][key] for q in groups[g])
        print(f"S{s}: V_top 기본 {tot('top_five','base')/tot('A','base'):.1%} → 규칙 {tot('top_five','rot')/tot('A','rot'):.1%}  "
              f"(랭커5 {tot('top_five','base'):.0f}→{tot('top_five','rot'):.0f}억, A {tot('A','base'):.0f}→{tot('A','rot'):.0f}억, 덱 {k}개)", flush=True)
json.dump(out, open('/home/user/nikke-opt/experiments/32_primitive_control/diag/rotate10.json', 'w'), ensure_ascii=False, indent=1)
