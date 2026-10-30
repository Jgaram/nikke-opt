"""실험 10 실행기(run10.py) — 가짜 평가기로 확인한다."""

import json
import os
import random
import sys
import unittest
from collections import Counter
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP9 = ROOT / "experiments" / "09_account_pack"
EXP10 = ROOT / "experiments" / "10_rankerless_start"
for p in (EXP9, EXP10):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import run9  # noqa: E402
import run10 as T  # noqa: E402


class _Res:
    def __init__(self, dmg):
        self.total_damage, self.error, self.cached = dmg, None, False


class FakeEv:
    """니케 가중치 + 짝 보너스 + 순서 약간(177명). 결정론."""

    def __init__(self):
        rng = random.Random(11)
        self.w = {n: rng.uniform(1, 10) for n in T.P177}
        self.sim_count = 0

    def damage(self, sq, options):
        v = sum(self.w[n] for n in sq)
        v += sum(3.0 for a in sq for b in sq if a < b and (len(a) + len(b)) % 7 == 0)
        v += 0.01 * sum(i * self.w[n] for i, n in enumerate(sq))
        low = (options.get("profile") or {}).get("chars", {})
        v -= sum(2.0 for n in sq if n in low)
        return int(v * 1e8)

    def evaluate(self, reqs):
        self.sim_count += len(reqs)
        return [_Res(self.damage(r.squad, r.options)) for r in reqs]


class FlatEv(FakeEv):
    """모든 스쿼드가 같은 딜 — 계보가 오르지 않아 매 라운드 킥한다."""

    def damage(self, sq, options):
        return 10 ** 9


class Poison:
    """랭커 자료 대신 끼워 넣는다 — 건드리면 실패한다."""

    def _boom(self, *a, **k):
        raise AssertionError("랭커 자료를 읽었다")

    __getitem__ = __iter__ = __len__ = __contains__ = get = items = keys = values = _boom


def val(i):
    return run9.val_scenarios()[i]


class TestRoster(unittest.TestCase):
    def test_roster_and_frames(self):
        self.assertEqual(len(T.P177), 177)
        self.assertEqual(Counter(T.BURST_ALL.values()), Counter({"3": 77, "2": 59, "1": 40, "A": 1}))
        self.assertTrue(set(T.P60) <= set(T.P177))
        self.assertEqual(set(T.STRUCT_FRAMES), {(1, 1, 3, 0), (1, 2, 2, 0), (2, 1, 2, 0),
                                                (1, 1, 2, 1), (1, 2, 1, 1), (2, 1, 1, 1)})
        self.assertTrue(set(run9.FRAMES) <= set(T.STRUCT_FRAMES))

    def test_accounts(self):
        s = val(4)  # v5 육성 무작위 C
        a60 = T.Account10(s, 60, rankerless=True)
        k60 = run9.Account(s)
        self.assertEqual(a60.names, k60.names)
        self.assertEqual(a60.options, k60.options)
        self.assertTrue(all(set(v) == {"burst"} for v in a60.owned.values()))
        a177 = T.Account10(s, 177, rankerless=True)
        self.assertEqual(len(a177.names), 177)
        ext = {n: t for n, t in a177.tier.items() if n not in run9.POOL}
        self.assertEqual(len(ext), 117)
        self.assertTrue(0 < sum(t != "상" for t in ext.values()) < 117)
        self.assertEqual({n: t for n, t in a177.tier.items() if n in run9.POOL}, k60.tier)
        a1 = T.Account10(val(0), 177, rankerless=True)  # 미보유 시나리오: 더한 니케는 모두 상
        self.assertTrue(all(a1.tier[n] == "상" for n in a1.names if n not in run9.POOL))
        self.assertEqual(len(a1.names), 177 - 3)
        k177 = T.Account10(val(0), 177, rankerless=False)
        self.assertEqual(k177.owned["크라운"]["s40_use"], run9.POOL["크라운"]["s40_use"])


class TestGenerators(unittest.TestCase):
    def test_design_balanced(self):
        acct = T.Account10(val(2), 60)  # 미보유 6명
        d = T.design(acct.names, T.BURST_ALL, random.Random(1))
        self.assertEqual(len(d), len(acct.names) * 3 // 5)
        self.assertEqual(len({frozenset(x) for x in d}), len(d))
        cnt = Counter(n for x in d for n in x)
        for x in d:
            self.assertEqual(len(set(x)), 5)
            self.assertIn(T.frame_of(x, T.BURST_ALL), T.STRUCT_FRAMES)
            stages = [T.BURST_ALL[n] for n in x]
            self.assertEqual(stages, sorted(stages, key="12A3".index))
        for s in "123":
            c = [cnt[n] for n in acct.names if T.BURST_ALL[n] == s]
            self.assertLessEqual(max(c) - min(c), 1, s)
        self.assertEqual(d, T.design(acct.names, T.BURST_ALL, random.Random(1)))

    def test_no_red_hood_frames(self):
        acct = T.Account10(run9.dev_scenarios()[4], 60)  # 미보유 레드 후드
        d = T.design(acct.names, T.BURST_ALL, random.Random(2))
        self.assertTrue(all(T.frame_of(x, T.BURST_ALL)[3] == 0 for x in d) or "레드 후드" in acct.names)

    def test_dual_fit_matches_ridge(self):
        acct = T.Account10(val(0), 60)
        ev, book = FakeEv(), run9.S4.Book()
        for sq in T.design(acct.names, T.BURST_ALL, random.Random(3), n=80):
            book.add(sq, ev.damage(sq, {}) / 1e8)
        a, b = run9.S4.fit(book, acct.names), T.DualFit(book, acct.names)
        rng = random.Random(4)
        for _ in range(30):
            c = frozenset(rng.sample(acct.names, rng.randint(0, 5)))
            self.assertAlmostEqual(a(c), b(c), places=6)
        cur, opts = acct.names[:3], acct.names[3:20]
        for x, v in zip(opts, b.add_scores(cur, opts)):
            self.assertAlmostEqual(v, a(frozenset(cur + [x])), places=6)

    def test_alt20(self):
        acct = T.Account10(val(0), 60)
        ev, book = FakeEv(), run9.S4.Book()
        for sq in T.design(acct.names, T.BURST_ALL, random.Random(5), n=150):
            book.add(sq, ev.damage(sq, {}) / 1e8)
        best = [sq for _, sq in run9.pack_vals(book.best)[1]]
        tot, ch = T.pack_alt20(book.best, best)
        self.assertEqual(len(ch), 5)
        self.assertLessEqual(T.shared_nikkes([sq for _, sq in ch], best), 20)
        self.assertLessEqual(sum(frozenset(sq) in {frozenset(b) for b in best} for _, sq in ch), 2)


class TestMethods(unittest.TestCase):
    def test_k_matches_exp9_l0k(self):
        """기법 K(탈출 없음) = 실험 9 L0k(같은 평가 기록)."""
        for b in (300, 800):
            acct = run9.Account(val(1))
            s9, r9 = run9.run_method(acct, "L0k", b, FakeEv())
            s10, r10, _ = T.run_method(acct, "K", b, FakeEv(), pool=60)
            self.assertEqual([r["squad"] for r in r9], [r["squad"] for r in r10])
            self.assertEqual(s9["final"]["total"], s10["final"]["total"])
            self.assertEqual([h["pack"] for h in s9["history"]], [h["pack"] for h in s10["history"]])

    def test_rankerless_do_not_read_ranker_data(self):
        scs = [val(7)]
        saved = {k: getattr(run9, k) for k in ("RANKERS", "RK_SQ", "PATTERN", "POOL")}
        try:
            for k in saved:
                setattr(run9, k, Poison())
            pre, _ = self._precompute()
            for s in scs:
                for m in T.RANKERLESS:
                    acct = T.Account10(s, 60, rankerless=True)
                    summ, recs, _ = T.run_method(acct, m, 400, FakeEv(), pre=pre)
                    self.assertGreater(summ["final"]["total"], 0)
                    self.assertLessEqual(summ["evals"], 400)
                    self.assertEqual(len(summ["final"]["squads"]), 5)
        finally:
            for k, v in saved.items():
                setattr(run9, k, v)

    def _precompute(self):
        old = T.PRE_BUDGET
        T.PRE_BUDGET = 450
        try:
            return T.precompute(60, FakeEv())
        finally:
            T.PRE_BUDGET = old

    def test_precompute_sets(self):
        pre, _ = self._precompute()
        self.assertEqual(len(pre["sets"]), T.PRE_SETS)
        prev = []
        for s in pre["sets"]:
            comps = {frozenset(d) for d in s}
            self.assertEqual(len({n for d in s for n in d}), 25)
            for p in prev:
                self.assertLessEqual(len(comps & p), 2)
            prev.append(comps)
        self.assertEqual(set(pre["coef"]), set(T.P60))

    def test_transplant_coef(self):
        acct = T.Account10(val(0), 60)
        miss = val(0)["missing"]
        other = [n for n in T.P60 if n not in miss]
        deck = tuple([miss[0]] + other[:4])
        coef = {n: i for i, n in enumerate(T.P60)}
        out = T.transplant_coef([deck], acct.owned, coef, T.BURST_ALL)[0]
        self.assertNotIn(miss[0], out)
        self.assertEqual(T.BURST_ALL[out[0]], T.BURST_ALL[miss[0]])

    def test_escape_runs_and_deterministic(self):
        acct = T.Account10(val(3), 60)
        a, ra, _ = T.run_method(acct, "R+E", 500, FlatEv())
        b, rb, _ = T.run_method(acct, "R+E", 500, FlatEv())
        self.assertEqual(a["final"], b["final"])
        self.assertEqual([r["squad"] for r in ra], [r["squad"] for r in rb])
        self.assertGreater(len(a["kicks"]), 0)
        self.assertTrue(all("improved" in k for k in a["kicks"]))
        self.assertTrue(any(h["kick"] for h in a["history"]))
        self.assertEqual(a["history"][-1]["pack"], a["final"]["total"])
        self.assertGreaterEqual(a["final"]["total"], max(h["pack"] for h in a["history"]) - 1e-9)
        body = [r for r in ra if r["phase"] != "순서"]  # 킥 · 탐색은 평가한 구성을 피한다
        self.assertEqual(len({frozenset(r["squad"]) for r in body}), len(body))
        r, _, _ = T.run_method(acct, "R", 500, FlatEv())
        n0 = a["kicks"][0]["evals"]
        self.assertEqual([h for h in a["history"] if h["evals"] <= n0], [h for h in r["history"] if h["evals"] <= n0])

    def test_kick_keeps_three(self):
        acct = T.Account10(val(0), 60)
        sess = run9.Session(acct, FakeEv(), 400)
        sess.run(T.design(acct.names, T.BURST_ALL, random.Random(6)), "설계")
        best = {frozenset(sq) for _, sq in sess.pack()[1]}
        lin = T.do_kick(sess, random.Random(7), T.BURST_ALL, cap=10)
        self.assertEqual(len(lin), 5)
        self.assertEqual(len(lin & best), 3)
        self.assertEqual(len(set().union(*lin)), 25)
        for c in lin - best:
            self.assertIn(T.frame_of(c, T.BURST_ALL), T.STRUCT_FRAMES)

    def test_p177_methods(self):
        pre = {"sets": [[list(x) for x in T.design(T.P60, T.BURST_ALL, random.Random(8), n=5)]],
               "coef": {n: 0.0 for n in T.P60}}
        for m in ("G+E", "K", "P"):
            acct = T.Account10(val(4), 177, rankerless=m != "K")
            summ, _, _ = T.run_method(acct, m, 500, FakeEv(), pre=pre)
            self.assertEqual(summ["pool"], 177)
            self.assertLessEqual(summ["evals"], 500)
            self.assertEqual(len(summ["final"]["squads"]), 5)

    def test_summary_schema(self):
        acct = T.Account10(val(0), 60)
        summ, _, _ = T.run_method(acct, "G", 400, FakeEv())
        for k in ("scenario", "name", "pool", "method", "budget", "evals", "errors", "start", "history",
                  "pre_order", "kicks", "final", "alt", "alt20", "sims_during", "seconds"):
            self.assertIn(k, summ)
        self.assertEqual(summ["history"][0]["evals"], summ["start"]["evals"])
        self.assertGreater(summ["start"]["evals"], len(acct.names) * 3 // 5)  # 설계 + 구성
        json.dumps(summ, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
