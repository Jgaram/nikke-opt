"""실험 8 실행기(run8.py)의 장전컨 기본값 · 분석(analyze8.py)의 지표 · 판단 — 가짜 자료로 확인한다."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

EXP8 = Path(__file__).resolve().parent.parent / "experiments" / "08_control_postproc"
if str(EXP8) not in sys.path:
    sys.path.insert(0, str(EXP8))

import analyze8 as A  # noqa: E402
import run8  # noqa: E402


class TestReloadDefaults(unittest.TestCase):
    def setUp(self):
        self.cands = {
            "k1": {"squad": ["a", "b"], "fold": "A"},
            "k2": {"squad": ["a", "c"], "fold": "B"},
            "k3": {"squad": ["a", "b"], "fold": "B"},
            "k4": {"squad": ["b", "c"], "fold": "B"},
        }
        self.summ = [
            {"comp_id": "k1", "best_damage": 1, "best_variants": ["a:reload:A0.3"]},
            {"comp_id": "k2", "best_damage": 1, "best_variants": ["a:reload:B0.1", "c:reload:C0.1_dry"]},
            {"comp_id": "k3", "best_damage": 1, "best_variants": ["a:reload:B0.1", "b:click:tap"]},
            {"comp_id": "k4", "best_damage": 1, "best_variants": ["b:reload:A0.3"]},
        ]

    def test_choice(self):
        self.assertEqual(run8.reload_choice(["a:click:tap", "a:reload:B0.1"], "a"), "B0.1")
        self.assertEqual(run8.reload_choice(["a:click:tap"], "a"), run8.NONE)

    def test_cross_fit_excludes_own_fold(self):
        t = run8.reload_defaults(self.summ, self.cands, exclude_fold="A")  # B 계열(k2 · k3 · k4)에서 배운다
        self.assertEqual(t["a"]["choice"], "B0.1")
        self.assertEqual(t["a"]["n"], 2)
        # b: k3 없음 · k4 A0.3 → 동률은 none 먼저
        self.assertEqual(t["b"]["choice"], run8.NONE)
        self.assertEqual(t["c"]["choice"], run8.NONE)  # k2 C0.1_dry · k4 없음 → 동률
        self.assertEqual(t["c"]["n"], 2)
        t2 = run8.reload_defaults(self.summ, self.cands, exclude_fold="B")  # A 계열(k1)만
        self.assertEqual(t2["a"]["choice"], "A0.3")
        self.assertNotIn("c", t2)

    def test_default_labels(self):
        t = run8.reload_defaults(self.summ, self.cands, exclude_fold="A")
        self.assertEqual(run8.default_labels(["a", "b", "z"], t), ["a:reload:B0.1"])

    def test_fold_alternates(self):
        self.assertEqual([run8.fold_of(i) for i in range(4)], ["A", "B", "A", "B"])


class TestMetrics(unittest.TestCase):
    def test_spearman(self):
        self.assertAlmostEqual(A.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(A.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertEqual(A.avg_ranks([5, 5, 1]), [2.5, 2.5, 1.0])

    def test_postproc(self):
        ids = [f"k{i:02d}" for i in range(30)]
        S = {i: 100 - n for n, i in enumerate(ids)}            # k00이 S 1위
        J = dict(S)
        J["k25"] = 1000                                        # S 26위가 J 1위
        sims = {i: 200 for i in ids}
        r = A.postproc(S, J, sims, 10, overlap=1)
        self.assertEqual(r["hits"], 9)
        self.assertFalse(r["top1_in"])
        self.assertEqual(r["missed"], ["k25"])
        self.assertEqual(r["cost"], 30 + 10 * 199)
        self.assertAlmostEqual(r["top1_ratio"], 100 / 1000)
        r2 = A.postproc(S, J, sims, 26, overlap=0)
        self.assertEqual(r2["recall"], 1.0)
        self.assertEqual(r2["value_min"], 1.0)
        self.assertEqual(r2["cost"], 30 + 26 * 200)

    def test_ties_by_id(self):
        self.assertEqual(A.ranked({"b": 1, "a": 1, "c": 2}), ["c", "a", "b"])

    def test_skeleton_recall(self):
        S = {"a": 3, "b": 2, "c": 1, "d": 0}
        J = {"a": 3, "b": 2, "c": 1, "d": 5}
        skel = {"a": "x", "b": "x", "c": "y", "d": "y"}
        self.assertEqual(A.skeleton_recall(S, J, skel, 2, top=3), {"x": (2, 2), "y": (0, 2)})


class TestJudge(unittest.TestCase):
    @staticmethod
    def rows(rec):
        return [{"k": k, "recall": r} for k, r in zip(A.KS, rec)]

    def test_line1(self):
        j = A.judge(self.rows([0.7, 0.9, 1.0, 1.0]), self.rows([0.9, 1.0, 1.0, 1.0]))
        self.assertEqual((j["line"], j["k"]), (2, 10))  # S2가 K 더 작음
        j = A.judge(self.rows([0.7, 0.9, 1.0, 1.0]), self.rows([0.7, 0.9, 1.0, 1.0]))
        self.assertEqual((j["line"], j["k"]), (1, 20))  # 같으면 1줄

    def test_line2_and_3(self):
        j = A.judge(self.rows([0.5, 0.6, 0.8, 0.9]), self.rows([0.6, 0.8, 0.9, 1.0]))
        self.assertEqual((j["line"], j["k"]), (2, 40))
        j = A.judge(self.rows([0.3, 0.4, 0.5, 0.6]), self.rows([0.3, 0.4, 0.6, 0.65]))
        self.assertEqual(j["line"], 3)
        self.assertTrue(j["large_change"])
        j = A.judge(self.rows([0.3, 0.4, 0.8, 0.9]), self.rows([0.3, 0.4, 0.6, 0.65]))
        self.assertEqual(j["line"], 3)  # K = 80만 충족은 기준 밖
        self.assertFalse(j["large_change"])


class TestEndToEnd(unittest.TestCase):
    def test_files(self):
        with tempfile.TemporaryDirectory() as d:
            runs, rel = Path(d, "runs"), Path(d, "rel")
            runs.mkdir()
            rel.mkdir()
            cands, rows = [], []
            for n in range(25):
                cid = f"k{n:03d}"
                cands.append({"id": cid, "squad": [f"m{n}"], "skeleton": "1-1-3" if n % 2 else "1-2-2",
                              "kind": "swap", "fold": "A"})
                base, best = 1000 - n, 1000 - n + (50 if n == 20 else 0)
                (runs / f"{cid}.done").write_text(json.dumps({"comp_id": cid, "best_damage": best,
                                                              "best_variants": []}))
                with open(runs / f"{cid}.jsonl", "w") as f:
                    for s in range(5):
                        f.write(json.dumps({"step": s, "total_damage": base if s == 0 else best,
                                            "cached": False}) + "\n")
                rows.append({"comp_id": cid, "total_damage": base, "reused": True})
            with open(rel / "reload_eval.jsonl", "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            J, L, sims, _ = A.load_runs(runs)
            S2, n_sim, n_reuse = A.load_reload(rel)
            self.assertEqual((len(J), sims["k000"], n_sim, n_reuse), (25, 5, 0, 25))
            a = A.analyze(cands, J, L, sims, S2, {})
            self.assertEqual(a["top"][0]["id"], "k020")
            self.assertEqual(a["rows"]["S1"][0]["hits"], 9)  # k020은 S1 21위
            self.assertEqual(a["rows"]["S1"][2]["hits"], 10)
            self.assertEqual(a["judge"]["line"], 1)
            md = A.render(a, {"s2_sims": 0, "s2_reused": 25})
            self.assertIn("1줄", md)


if __name__ == "__main__":
    unittest.main()
