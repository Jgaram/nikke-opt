"""실험 13 실행기(run13.py) — 합성 기록으로 합치기 · 쌍 고르기를 확인한다."""

import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP13 = ROOT / "experiments" / "13_seed_merge"
if str(EXP13) not in sys.path:
    sys.path.insert(0, str(EXP13))

import run13 as U  # noqa: E402

NAMES = U.R12.pre_account(0).names


def value(sq):
    return sum(1.0 + (sum(map(ord, n)) % 97) / 10.0 for n in sq)  # 결정론적 가짜 딜(억)


def fake_sources(n_per=60, seeds=U.SEEDS):
    out = {}
    for k in seeds:
        rng = random.Random(k)
        recs = []
        for _ in range(n_per):
            sq = rng.sample(NAMES, 5)
            recs.append({"squad": sq, "total_damage": value(sq) * U.R10.E8})
        recs.append({"squad": rng.sample(NAMES, 5), "total_damage": None})
        best = U.R9.pack_vals(U.R9.book_of(recs))[0]
        out[k] = ({"sims": 100 * (k + 1), "evals": len(recs), "seconds": 10.0, "final": {"total": best}}, recs)
    return out


class TestMerge(unittest.TestCase):
    def test_union_and_prefix(self):
        srcs = fake_sources()
        book, where, used = U.merged_book(srcs, (0, 1))
        self.assertEqual(used, {0: 61, 1: 61})
        self.assertEqual(len(book.best), len(where))
        self.assertTrue(all(set(v) <= {0, 1} for v in where.values()))
        _, _, half = U.merged_book(srcs, (0, 1), part=2)
        self.assertEqual(half, {0: 30, 1: 30})

    def test_merge_not_below_singles(self):
        srcs = fake_sources()
        m = U.merge(srcs, (0, 2, 3))
        self.assertEqual((m["name"], m["kind"]), ("U3-s0s2s3", "U3"))
        for k in (0, 2, 3):
            self.assertGreaterEqual(m["final"]["total"], srcs[k][0]["final"]["total"] - 1e-9)
        self.assertEqual(len(m["squad_seeds"]), 5)
        self.assertEqual(m["sims"], 100 + 300 + 400)
        e = U.merge(srcs, (0, 1, 2), part=3)
        self.assertEqual((e["name"], e["kind"], e["evals"]), ("E3-s0s1s2", "E3", 60))
        self.assertNotIn("coef", e)

    def test_pick_and_worst_pair(self):
        srcs = fake_sources()
        top = max(U.SEEDS, key=lambda k: srcs[k][0]["final"]["total"])
        self.assertEqual(U.pick_best(srcs, U.SEEDS), U.seed_method(top))
        obs = U.observe(srcs)
        self.assertEqual([sum(o["kind"] == k for o in obs) for k in ("U2", "U3", "E2", "E3")], [6, 4, 6, 4])
        wp = U.worst_pair(obs)
        pairs = {tuple(o["seeds"]): o["final"]["total"] for o in obs if o["kind"] == "U2"}
        self.assertEqual(pairs[tuple(wp)], min(pairs.values()))
        tie = [{"kind": "U2", "name": "U2-s1s2", "seeds": [1, 2], "final": {"total": 5.0}},
               {"kind": "U2", "name": "U2-s0s3", "seeds": [0, 3], "final": {"total": 5.0}}]
        self.assertEqual(U.worst_pair(tie), [0, 3])

    def test_full_merge_for_search(self):
        srcs = fake_sources()
        m = U.merge(srcs, (1, 2), full=True, name="U2w")
        self.assertEqual(m["name"], "U2w")
        self.assertEqual(len(m["coef"]), 177)
        self.assertTrue(1 <= len(m["sets"]) <= U.R10.PRE_SETS)
        self.assertAlmostEqual(m["set_totals"][0], m["final"]["total"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "precompute_U2w.json"
            import json
            p.write_text(json.dumps(m, ensure_ascii=False))
            self.assertEqual(U.load_pre("U2w", Path(d))["seeds"], [1, 2])
        with self.assertRaises(ValueError):
            U.load_pre("PB15", Path("."))

    def test_real_sources_exist(self):
        for k in U.SEEDS:
            pj, pr = U.src_paths(k)
            self.assertTrue(pj.is_file() and pr.is_file(), pj)
        self.assertEqual([U.seed_method(k) for k in U.SEEDS], ["PB15", "PB15s1", "PB15s2", "PB15s3"])


if __name__ == "__main__":
    unittest.main()
