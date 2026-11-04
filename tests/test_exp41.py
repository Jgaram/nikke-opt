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


if __name__ == "__main__":
    unittest.main()
