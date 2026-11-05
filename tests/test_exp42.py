"""실험 42: 규칙 없는 조합 수 · 실험 41 표 재사용 대응 · 기본 값 세계 평가기 · 판 부품(시뮬 0)."""

import importlib.util
import random
import sys
import unittest
from itertools import combinations
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "experiments" / "42_bundle_search"


def load():
    if "run42" in sys.modules:
        return sys.modules["run42"]
    spec = importlib.util.spec_from_file_location("run42", EXP / "run42.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run42"] = mod
    spec.loader.exec_module(mod)
    return mod


def small(seed: int = 0, n: int = 9):
    """작은 규칙 없는 표: S36 풀 앞 n명의 5인 조합 전부, 무작위 값."""
    r = load()
    names = sorted(r.pool(36))[:n]
    rng = random.Random(seed)
    cs = list(combinations(names, 5))
    vals = [round(rng.uniform(5, 60), 3) for _ in cs]
    return r, r.R41.Table(36, cs, vals, None, names), names


class Free42(unittest.TestCase):
    def test_counts(self):
        r = load()
        want = {36: 435_897, 39: 658_008, 42: 658_008}
        for s, n in want.items():
            self.assertEqual(r.free_count(s), n)
            self.assertEqual(comb(len(r.pool(s)), 5), n)

    def test_rule_space_is_subset_in_same_shape(self):
        """실험 41 구성(이름순 튜플)은 규칙 없는 구성 목록에 같은 모양으로 들어 있다 — 재사용 대응."""
        r = load()
        free = set(r.free_comps(36))
        rule = r.R41.comps(36)
        self.assertTrue(all(c in free for c in rule[:2000]))
        self.assertTrue(all(tuple(sorted(c)) == c for c in rule[:2000]))
        self.assertEqual(len(free), r.free_count(36))

    def test_base_world_evaluator(self):
        from nikke_opt.evaluator import EvalRequest
        r, T, names = small()
        ev = r.BaseWorldEvaluator(T)
        c = T.cs[3]
        o1 = tuple(c)
        o2 = tuple(reversed(c))
        g = ev.evaluate([EvalRequest(o1, options={}), EvalRequest(o2, options={})])
        self.assertEqual(g[0].total_damage, g[1].total_damage)            # 순서는 값에 안 들어간다
        self.assertEqual(g[0].total_damage, round(T.base[3] * 1e8))
        self.assertEqual(ev.sim_count, 2)
        with self.assertRaises(KeyError):
            ev.evaluate([EvalRequest(tuple(sorted(r.pool(36)))[-5:], options={})])


class Arms42(unittest.TestCase):
    def test_free_generators_ignore_frames(self):
        r = load()
        A = r.arms_mod()
        names = sorted(r.pool(36))
        d = A.design_free(names, r.BURST, random.Random(1))
        self.assertEqual(len(d), len(names) * r.R10.DESIGN_MULT // 5)
        self.assertEqual(len({frozenset(x) for x in d}), len(d))
        self.assertTrue(any(not r.P41.passes(x) for x in d))              # 규칙 밖 구성도 나온다
        self.assertTrue(all(x == r.base_order(x) for x in d))              # 기본 순서
        sq = d[0]
        nb = A.neighbors_free(sq, {n: {} for n in names})
        self.assertEqual(len(nb), 5 * (len(names) - 5))
        self.assertTrue(any(r.P41.frame(x) != r.P41.frame(sq) for x in nb))

    def test_beam_exact_when_wide(self):
        """빔이 넓으면 대리 모델 − 가격 최대 구성을 전수와 같게 찾는다."""
        r = load()
        A = r.arms_mod()
        names = sorted(r.pool(36))[:9]
        rng = random.Random(3)
        w = {n: rng.uniform(0, 10) for n in names}
        pair = {p: rng.gauss(0, 2) for p in combinations(names, 2)}
        score = lambda c: sum(w[x] for x in c) + sum(pair[p] for p in combinations(sorted(c), 2))  # noqa: E731
        price = {n: rng.uniform(0, 3) for n in names}
        brute = max(combinations(names, 5), key=lambda c: score(c) - sum(price[x] for x in c))
        got = A.beam_comps(score, names, price, width=200)
        self.assertEqual(got[0][1], frozenset(brute))
        self.assertAlmostEqual(got[0][0], score(brute) - sum(price[x] for x in brute), places=9)
        self.assertTrue(all(len(c) == 5 for _, c in got))
        self.assertEqual([x for x, _ in got], sorted((x for x, _ in got), reverse=True))

    def test_prices_bound_the_pack(self):
        """니케 가격 λ ≥ 0이고, 어떤 겹치지 않는 5덱 합도 Σ(값 − Σλ) 상위 5 + λ 상위 25의 합을 넘지 않는다(쌍대 상한)."""
        r = load()
        A = r.arms_mod()
        names = sorted(r.pool(36))[:27]
        rng = random.Random(5)
        cs = rng.sample(list(combinations(names, 5)), 400)
        book = {frozenset(c): (rng.uniform(10, 60), tuple(c)) for c in cs}
        best, _ = r.R9.pack_vals(book)
        lam = A.nikke_prices(book, names, best)
        self.assertTrue(all(v >= 0 for v in lam.values()))
        red = sorted((v - sum(lam[x] for x in c) for c, (v, _) in book.items()), reverse=True)
        bound = sum(red[:5]) + sum(sorted(lam.values(), reverse=True)[:25])
        self.assertGreaterEqual(bound + 1e-6, best)

    def test_patched_restores(self):
        r = load()
        A = r.arms_mod()
        before = (r.R10.design, r.R10.local_round, A.S4.neighbors)
        with A.patched("P"):
            self.assertIs(r.R10.local_round, A.price_round)
            self.assertIs(r.R10.design, A.design_free)
        self.assertEqual((r.R10.design, r.R10.local_round, A.S4.neighbors), before)
        with A.patched("base"):
            self.assertIs(r.R10.design, before[0])


class Order42(unittest.TestCase):
    def test_order_season_with_fake_evaluator(self):
        """3단계: 잰 stage_key는 다시 안 재고, 다듬은 값은 기록 값보다 작아지지 않으며, 시뮬 수 = 순서 + 카메라."""
        import hashlib
        from types import SimpleNamespace
        r = load()
        names = sorted(r.BURST)[:30]
        rng = random.Random(11)
        comps = [tuple(rng.sample(names, 5)) for _ in range(40)]

        def val(order, cam=None):
            h = int(hashlib.md5(("|".join(order) + f"#{cam}").encode()).hexdigest()[:6], 16)
            return 10e8 + sum(len(x) for x in order) * 1e7 + h % 5_000_000

        class FakeEv:
            sim_count = 0

            def evaluate(self, reqs):
                self.sim_count += len(reqs)
                return [SimpleNamespace(error=None, total_damage=val(tuple(q.squad), (q.options.get("operation") or {}).get("camera")))
                        for q in reqs]

        recs = {k: [{"squad": list(c), "total_damage": val(c), "error": None} for c in comps[k::2]] for k in (0, 1)}
        full = comps[0]
        recs[0] += [{"squad": list(o), "total_damage": val(o), "error": None} for o in r.R41.R2.distinct_orders(full, r.BURST)]
        old = r.verify_recs
        r.verify_recs = lambda arm, s, k: recs[k]
        try:
            ev = FakeEv()
            out = r.order_season("base", 23, ev)
        finally:
            r.verify_recs = old
        self.assertEqual(out["sims"], out["order_sims"] + out["camera_sims"])
        self.assertEqual(out["sims"], ev.sim_count)
        self.assertEqual(out["camera_sims"], 5 * out["targets"])
        self.assertGreaterEqual(out["after_order"] + 1e-9, out["pre"])
        self.assertGreaterEqual(out["after_camera"] + 1e-9, out["after_order"])
        for d in out["decks"]:
            self.assertGreaterEqual(d["after"] + 1e-9, d["order"])
            self.assertGreaterEqual(d["order"] + 1e-9, d["pre"])
        dk = {frozenset(d["comp"]): d for d in out["decks"]}
        if frozenset(full) in dk:                                           # 다 잰 구성은 새 순서를 안 잰다
            n_rep = len(r.R41.R2.distinct_orders(full, r.BURST))
            self.assertEqual(dk[frozenset(full)]["orders"], n_rep + (tuple(full) not in r.R41.R2.distinct_orders(full, r.BURST)))


if __name__ == "__main__":
    unittest.main()
