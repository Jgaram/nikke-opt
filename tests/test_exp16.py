"""실험 16 실행기 · 분석(run16.py · analyze16.py) — 합성 기록으로 층 나누기 · 실행 순서 · 상한 · 판단 규칙을 확인한다."""

import os
import random
import sys
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP16 = ROOT / "experiments" / "16_control_miss"
if str(EXP16) not in sys.path:
    sys.path.insert(0, str(EXP16))

import analyze16 as A  # noqa: E402
import run16 as R  # noqa: E402

BY = {s: sorted(n for n, b in R.BURST.items() if b == s and not n.startswith("test_")) for s in "123"}
TEST = sorted(n for n in R.BURST if n.startswith("test_"))


def squad(rng, frame):
    out = []
    for s, c in zip("123", frame):
        out += rng.sample(BY[s], c)
    return tuple(out)


def fake_best(n=400, seed=0, with_test=3):
    rng = random.Random(seed)
    best = {}
    while len(best) < n:
        sq = squad(rng, rng.choice(((1, 2, 2), (1, 1, 3), (2, 1, 2))))
        best.setdefault(frozenset(sq), (rng.uniform(5, 40), sq))
    for i in range(with_test):
        sq = squad(rng, (1, 2, 2))
        sq = (TEST[0],) + sq[1:] if TEST else sq
        best[frozenset(sq)] = (100.0 + i, sq)  # 가장 높아도 순위에 넣지 않는다
    return best


class TestLayers(unittest.TestCase):
    def test_partition_and_sampling(self):
        best = fake_best()
        layers, sizes = R.sample_layers(best, 30.0, "x")
        self.assertEqual(sizes["test_excluded"], 3 if TEST else 0)
        self.assertEqual(sum(sizes[k] for k in ("S0", "S0p", "S1", "S2", "S3")) + sizes["test_excluded"], len(best))
        self.assertEqual(sizes["S0"], 15)
        self.assertEqual(sizes["S0p"], 15)
        for e in layers["S0"]:
            self.assertLessEqual(e["frame_rank"], 5)
        for e in layers["S0p"]:
            self.assertTrue(6 <= e["frame_rank"] <= 10)
        for e in layers["S1"]:
            self.assertGreaterEqual(e["B"], 0.85 * 30.0)
            self.assertGreater(e["frame_rank"], 10)
        for e in layers["S2"]:
            self.assertTrue(15.0 <= e["B"] < 25.5)
        for e in layers["S3"]:
            self.assertLess(e["B"], 15.0)
        self.assertTrue(all(not R.has_test(e["squad"]) for v in layers.values() for e in v))
        self.assertEqual(Counter_(e["half"] for e in layers["S1"]),
                         {"up": min(32, sizes["S1_up"]), "lo": min(32, sizes["S1_lo"])})
        self.assertEqual(sizes["S1_up"] - sizes["S1_lo"], sizes["S1"] % 2)
        again, _ = R.sample_layers(best, 30.0, "x")
        self.assertEqual(layers, again)
        other, _ = R.sample_layers(best, 30.0, "y")
        self.assertNotEqual(layers["S1"], other["S1"])
        self.assertEqual({e["part"] for e in layers["S2"]}, {0, 1})

    def test_s4(self):
        acct = fake_best(50, seed=1, with_test=0)
        pre = fake_best(300, seed=2, with_test=2)
        pre.update({c: (v + 30.0, sq) for c, (v, sq) in list(acct.items())[:5]})
        owned = set(R.BURST) - {BY["1"][0]}
        cands = R.s4_candidates(pre, 30.0, acct, owned)
        self.assertTrue(cands)
        for v, sq in cands:
            self.assertGreaterEqual(v, 25.5)
            self.assertNotIn(frozenset(sq), acct)
            self.assertNotIn(BY["1"][0], sq)
            self.assertFalse(R.has_test(sq))
        picked = R.sample_s4(cands, "v1")
        self.assertEqual(len(picked), min(16, len(cands)))
        self.assertTrue(all(e["B"] is None and e["B_pre"] >= 25.5 for e in picked))


def Counter_(xs):
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def fake_targets():
    t = {"scenarios": {}}
    for sid, seed in (("v1", 3), ("v2", 4)):
        best = fake_best(300, seed=seed, with_test=0)
        layers, sizes = R.sample_layers(best, 30.0, sid)
        layers["S4"] = []
        t["scenarios"][sid] = {"layers": layers, "sizes": sizes}
    return t


class TestJobs(unittest.TestCase):
    def test_priority_order(self):
        jobs = R.job_list(fake_targets())
        order = [(j["layer"]) for j in jobs]
        ranks = {"S0": 0, "S0p": 1, "S1": 2, "S4": 3, "S2": 4, "S3": 6}
        seq = []
        for j in jobs:
            r = ranks[j["layer"]]
            if j["layer"] == "S2":
                e = next(e for e in fake_targets()["scenarios"][j["scenario"]]["layers"]["S2"] if e["squad"] == j["squad"])
                r += e["part"]
            seq.append(r)
        self.assertEqual(seq, sorted(seq))
        self.assertEqual(len({j["id"] for j in jobs}), len(jobs))
        self.assertIn("S3", order)
        only = R.job_list(fake_targets(), only=["v2"], layers=["S0"])
        self.assertTrue(only and all(j["scenario"] == "v2" and j["layer"] == "S0" for j in only))

    def test_cap_gate(self):
        class Ev:
            sim_count = 0
        ev = Ev()
        g = R.CapGate(ev, cap=1000, per_job=200, base=100)
        got = [g.enter() for _ in range(5)]
        self.assertEqual(got, [True, True, True, True, False])
        g.leave()
        self.assertFalse(g.enter())  # 한 번 닫히면 남은 작업은 모두 뺀다


def fake_jobs(t, gain):
    out = {}
    for sid, d in t["scenarios"].items():
        for lay, es in d["layers"].items():
            for e in es:
                cid = R.comp_id(sid, e["squad"])
                b = e["B"] if e["B"] is not None else 20.0
                out[cid] = {"comp_id": cid, "base_damage": round(b * R.E8), "best_damage": round(b * (1 + gain(lay, e)) * R.E8),
                            "best_variants": [f"{e['squad'][0]}:burst:x"]}
    return out


class TestAnalyze(unittest.TestCase):
    def test_scenario_totals(self):
        best = fake_best(300, seed=3, with_test=0)
        layers, sizes = R.sample_layers(best, 30.0, "v1")
        layers["S4"] = []
        tgt = {"name": "t", "m": 30.0, "P0_record": 0, "layers": layers, "sizes": sizes}
        jobs = fake_jobs({"scenarios": {"v1": tgt}}, lambda lay, e: 0.5 if lay == "S3" else 0.01)
        r = A.scenario("v1", tgt, best, jobs)
        t = r["totals"]
        self.assertLessEqual(t["P0"], t["P5"] + 1e-9)
        self.assertLessEqual(t["P5"], t["P10"] + 1e-9)
        self.assertLessEqual(t["P10"], t["Pstar"] + 1e-9)
        self.assertAlmostEqual(r["L"], t["Pstar"] / t["P5"] - 1)
        self.assertEqual(r["base_mismatch"], 0)
        self.assertEqual(r["missing"], {})
        for d in r["missed"]:
            self.assertIn(d["layer"], A.OUTSIDE)
            self.assertTrue(d["controlled"])
        self.assertEqual(r["enter"]["S0"]["n"], 15)

    def test_judge(self):
        def row(L, Lo, missed=()):
            return {"L": L, "Lout": Lo, "missing": {}, "missed": [{"layer": x} for x in missed]}
        self.assertEqual(A.judge([row(0.001, 0.0)] * 8)["case"], 1)
        self.assertEqual(A.judge([row(0.001, 0.0)] * 7 + [row(0.02, 0.0)])["case"], 1)
        self.assertEqual(A.judge([row(0.001, 0.0)] * 6 + [row(0.02, 0.0)] * 2)["case"], 2)
        self.assertEqual(A.judge([row(0.01, 0.0)] * 8)["case"], 2)
        self.assertEqual(A.judge([row(0.01, 0.005, ("S1",))] * 8)["case"], 3)
        self.assertEqual(A.judge([row(0.01, 0.001)] * 6 + [row(0.03, 0.02, ("S1", "S2"))] * 2)["case"], 3)
        self.assertEqual(A.judge([row(0.01, 0.005, ("S1", "S2", "S4"))] * 8)["case"], 4)
        self.assertIsNone(A.judge([row(0.01, 0.005)] * 8)["case"])
        self.assertIsNone(A.judge([row(0.0, 0.0)] * 7)["case"])
        bad = [row(0.0, 0.0)] * 8
        bad[0] = {**bad[0], "missing": {"S1": 1}}
        self.assertIsNone(A.judge(bad)["case"])

    def test_stats(self):
        self.assertAlmostEqual(A.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(A.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        lo, hi = A.wilson(0, 32)
        self.assertEqual(lo, 0.0)
        self.assertTrue(0 < hi < 0.1)
        lo, hi = A.wilson(16, 32)
        self.assertTrue(lo < 0.5 < hi)
        self.assertEqual(A.axes_of(["아니스 : 스타:burst:x", "squad:tactic:a=b", "모름"]), ["burst", "tactic"])


class TestDeckLoop(unittest.TestCase):
    def test_converges_and_measures_decks(self):
        best = fake_best(200, seed=5, with_test=0)
        calls = []

        def run(todo):
            calls.append(len(todo))
            out = {}
            for j in todo:
                b = best[frozenset(j["squad"])][0]
                g = 0.3 if sum(map(ord, "".join(j["squad"]))) % 3 == 0 else 0.0
                out[j["id"]] = {"squad": j["squad"], "base_damage": round(b * R.E8), "best_damage": round(b * (1 + g) * R.E8)}
            return out

        r = R.deck_loop("v1", best, {}, run)
        self.assertTrue(r["complete"])
        self.assertEqual(calls[0], 5)
        self.assertGreaterEqual(r["total"], R.R9.pack_vals(best)[0] - 1e-9)
        last = r["rounds"][-1]
        self.assertEqual(last["new"], 0)
        self.assertTrue(all(R.comp_id("v1", sq) in set(r["extra"]) for _, sq in last["squads"]))

    def test_measured_values_new_comp(self):
        best = fake_best(20, seed=6, with_test=0)
        sq = squad(random.Random(9), (1, 2, 2))
        vals = R.measured_values(best, [{"squad": list(sq), "base_damage": 10 * R.E8, "best_damage": 12 * R.E8}])
        self.assertAlmostEqual(vals[frozenset(sq)][0], 12.0)
        c, (v, s0) = next(iter(best.items()))
        vals = R.measured_values(best, [{"squad": list(s0), "base_damage": v * R.E8, "best_damage": v * 0.5 * R.E8}])
        self.assertAlmostEqual(vals[c][0], v)


if __name__ == "__main__":
    unittest.main()
