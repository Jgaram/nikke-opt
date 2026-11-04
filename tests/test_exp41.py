"""실험 41: 풀 규칙 재현 · 구조 통과 구성 수 · 기본 배치 순서(시뮬 0)."""

import importlib.util
import json
import sys
import unittest
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "experiments" / "41_ground_truth"


def load(name: str, file: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, EXP / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class Pool41(unittest.TestCase):
    def test_pool_rule_reproduces_committed_pool(self):
        p = load("pool41", "pool41.py")
        saved = json.loads(p.OUT.read_text(encoding="utf-8"))["seasons"]
        for s in p.SEASONS:
            b = p.build(s)
            self.assertEqual(b["pool"], saved[str(s)]["pool"])
            self.assertEqual(b["comps"], saved[str(s)]["comps"])

    def test_preregistered_table(self):
        """README §풀 규칙 표(2026-11-04 계산)와 같다."""
        p = load("pool41", "pool41.py")
        want = {36: (37, 37, (8, 12, 17, 0), 182_784), 39: (43, 40, (7, 12, 20, 1), 261_660),
                42: (44, 40, (11, 13, 16, 0), 268_840)}
        for s, (cand, n, st, nc) in want.items():
            b = p.build(s)
            self.assertEqual(b["candidates"], cand)
            self.assertEqual(len(b["pool"]), n)
            self.assertEqual(tuple(b["stages"][k] for k in "123A"), st)
            self.assertEqual(b["comps"], nc)
            a_names = {x for q in b["our_a"] for x in q}
            self.assertLessEqual(a_names, set(b["pool"]))     # 우리 A 25명은 언제나 풀에 든다

    def test_iter_comps_matches_count(self):
        p = load("pool41", "pool41.py")
        small = ["아니스 : 스타", "리틀 머메이드", "목단",           # 1단계
                 "크라운", "나유타", "티아",                          # 2단계
                 "신데렐라", "이사벨", "에이다", "라피 : 레드 후드"]   # 3단계 · A
        small = [n for n in small if n in p.BURST]
        got = list(p.iter_comps(small))
        self.assertEqual(len(got), p.count_comps(small))
        self.assertEqual(len(got), len(set(got)))
        self.assertTrue(all(p.passes(c) for c in got))
        # 구조 규칙 밖 구성은 하나도 없다: 풀의 5인 조합 전부 중 통과하는 것 = got
        from itertools import combinations
        allc = {tuple(sorted(c)) for c in combinations(small, 5) if p.passes(c)}
        self.assertEqual(allc, set(got))
        self.assertLessEqual(len(got), comb(len(small), 5))

    def test_base_order(self):
        r = load("run41", "run41.py")
        b = r.BURST
        comp = ("신데렐라", "아니스 : 스타", "크라운", "이사벨", "리틀 머메이드")
        o = r.base_order(comp)
        self.assertEqual(sorted(o), sorted(comp))
        st = [b[n] for n in o]
        self.assertEqual(st, sorted(st, key="12A3".index))
        for k in "123":
            inside = [n for n in o if b[n] == k]
            self.assertEqual(inside, sorted(inside))

    def test_options_camera(self):
        r = load("run41", "run41.py")
        o = r.options(36)
        self.assertTrue(o["sim"]["camera_reload_cancel"])
        self.assertEqual(o["enemy"], r.run31.options(36, 0)["enemy"])
        self.assertNotIn("core_px", o["enemy"])


def small_table(seed: int, n: int = 140):
    """구조 통과 구성 n개를 무작위로 고른 작은 표(니케 27명 — 겹치지 않는 5덱이 드물게만 생긴다)."""
    import random
    r = load("run41", "run41.py")
    rng = random.Random(seed)
    by = {k: sorted(x for x in r.pool(36) if r.BURST[x] == k) for k in "123"}
    names = by["1"][:7] + by["2"][:8] + by["3"][:12]
    allc = list(r.P41.iter_comps(names))
    cs = sorted(rng.sample(allc, n))
    vals = [round(rng.uniform(10, 60), 3) for _ in cs]
    return r, r.Table(36, cs, vals, None, names)


def all_packs(T, vals, k=5):
    """겹치지 않는 k덱 전부(가지치기 없음) — (합, 구성 번호들)."""
    out = []
    n = len(T.cs)

    def dfs(start, used, path, tot):
        if len(path) == k:
            out.append((tot, tuple(path)))
            return
        for i in range(start, n):
            if not T.masks[i] & used:
                dfs(i + 1, used | T.masks[i], path + [i], tot + vals[i])
    dfs(0, 0, [], 0.0)
    return out


class Pack41(unittest.TestCase):
    def test_pruned_exact_equals_full(self):
        for seed in range(6):
            r, T = small_table(seed)
            packs = all_packs(T, T.base)
            if not packs:
                continue
            best = max(t for t, _ in packs)
            full, _ = r.R9.pack_vals(T.book("base", range(len(T.cs))))
            got = r.exact_opt(T, "base", seed_limit=20)          # 하한을 일부러 약하게
            self.assertAlmostEqual(got["total"], best, places=9)
            self.assertAlmostEqual(full, best, places=9)
            self.assertTrue(got["exact"])

    def test_landscape_counts_and_members(self):
        for seed in range(6):
            r, T = small_table(seed)
            packs = all_packs(T, T.base)
            if not packs:
                continue
            best = max(t for t, _ in packs)
            for x in (1.0, 0.97, 0.9, 0.8):
                thr = x * best
                want = [p for t, p in packs if t >= thr - 1e-9]
                L = r.landscape(T, "base", best, x)
                self.assertTrue(L["complete"])
                self.assertEqual(L["count"], len(want))
                self.assertEqual(set(L["comps_in"]), {i for p in want for i in p})
                b = r.in_some_pack(T, "base", thr - 1e-9)
                self.assertEqual(set(b["comps"]), {i for p in want for i in p})

    def test_r_need_bruteforce(self):
        for seed in range(6):
            r, T = small_table(seed)
            packs = all_packs(T, T.base)
            if not packs:
                continue
            best = max(t for t, _ in packs)
            rk = T.ranks("base")
            for x in (1.0, 0.95, 0.85):
                want = min(max(rk[i] for i in p) for t, p in packs if t >= x * best - 1e-9)
                self.assertEqual(r.r_need(T, "base", x * best)["K"], want)

    def test_in_some_pack_fallback(self):
        """5덱 셈이 바로 끊겨도(시간 0) 구성별 판정이 같은 답을 낸다."""
        r, T = small_table(3)
        packs = all_packs(T, T.base)
        best = max(t for t, _ in packs)
        orig = r.enum_packs
        try:
            r.enum_packs = lambda *a, **k: {"count": 0, "complete": False, "stop": "time", "members": []}
            b = r.in_some_pack(T, "base", 0.9 * best - 1e-9)
        finally:
            r.enum_packs = orig
        self.assertEqual(set(b["comps"]), {i for t, p in packs if t >= 0.9 * best - 1e-9 for i in p})

    def test_table_evaluator(self):
        from nikke_opt.evaluator import EvalRequest
        r, T = small_table(1, n=30)
        c = T.cs[0]
        o = r.base_order(c)
        others = [x for x in r.R2.distinct_orders(o, r.BURST) if r.stage_key(x) != r.stage_key(o)]
        T.refined[0] = {r.stage_key(others[0]): (99.0, others[0])} if others else {}
        ev = r.TableEvaluator(T)
        got = ev.evaluate([EvalRequest(o, options={})])
        self.assertEqual(got[0].total_damage, round(T.base[0] * 1e8))
        if others:
            got = ev.evaluate([EvalRequest(others[0], options={})])
            self.assertEqual(got[0].total_damage, round(99.0 * 1e8))
            if len(others) > 1:
                got = ev.evaluate([EvalRequest(others[1], options={})])
                self.assertEqual(got[0].total_damage, round(T.base[0] * 1e8))
                self.assertEqual(ev.fallback, 1)
        outside = [x for x in r.P41.iter_comps(sorted(T.bit)) if frozenset(x) not in T.idx][0]
        with self.assertRaises(KeyError):
            ev.evaluate([EvalRequest(outside, options={})])

    def test_table_refined_best(self):
        r, T = small_table(2, n=20)
        o = r.base_order(T.cs[0])
        others = [x for x in r.R2.distinct_orders(o, r.BURST) if r.stage_key(x) != r.stage_key(o)]
        if not others:
            self.skipTest("순서 하나뿐")
        T2 = r.Table(36, T.cs, T.base, {0: {r.stage_key(others[0]): (T.base[0] + 5, others[0])}}, sorted(T.bit))
        self.assertAlmostEqual(T2.ref[0], T.base[0] + 5)
        self.assertEqual(T2.best_order[0], tuple(others[0]))
        self.assertEqual(T2.base[0], T.base[0])


if __name__ == "__main__":
    unittest.main()
