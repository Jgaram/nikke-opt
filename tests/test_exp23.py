"""실험 23 — 유사도 분석(시뮬 없음)."""

import importlib.util
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "23_deck_similarity"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A = sys.modules.get("analyze23") or _load("analyze23", EXP / "analyze23.py")


class TestAnalyze23(unittest.TestCase):
    def test_reference_values(self):
        ref = {r["case"]: r for r in A.reference()}
        self.assertAlmostEqual(ref["두 덱 사이 1명 맞교환"]["pair_jaccard"], 42 / 58)
        self.assertEqual(ref["같은 25명, 덱마다 원래 덱 출신 1명씩(완전 재배치)"]["moves"], 20)
        self.assertEqual(ref["니케 25명 모두 다름"]["shared_nikkes"], 0)

    def test_bins(self):
        self.assertEqual(A.bins([1.0, 0.72, 0.7, 0.5, 0.49, 0.1, 0.0]), [1, 2, 1, 1, 1, 1])

    def test_wmedian(self):
        self.assertEqual(A.wmedian([(0.2, 1), (0.9, 3)]), 0.9)
        self.assertIsNone(A.wmedian([]))

    def test_rebuilt(self):
        best = [["a", "b", "c", "d", "e"], ["f", "g", "h", "i", "j"]]
        self.assertEqual(A.rebuilt(best, [["a", "b", "c", "d", "x"], ["a", "b", "c", "f", "g"]]), 1)

    def test_ranker_baseline_counts_duplicates(self):
        g = [["a", "b"], ["c", "d"]]
        h = [["a", "c"], ["b", "d"]]
        base = A.ranker_baseline([g, g, h])
        self.assertEqual((base["rankers"], base["distinct"]), (3, 2))
        self.assertEqual(base["pair_median"], 0.0)                 # 쌍 3개: (g, g) = 1, (g, h) = 0 두 번
        self.assertEqual(base["near_j_median"], 1.0)               # g 두 명은 서로 같다, h는 0
        self.assertEqual(sorted(base["mean_j"]), [0.0, 0.5, 0.5])

    def test_ranker_fives_match_exp22(self):
        fives = A.read_json(A.FIVES)
        s22 = A.read_json(A.SEASONS22)
        if fives is None or s22 is None:
            self.skipTest("ranker_fives.json 없음")
        for s, players in fives["seasons"].items():
            rk = s22["seasons"][s]["rankers"]
            self.assertEqual(len(players), rk["players"])
            self.assertEqual(sum(len(p["decks"]) for p in players), rk["decks"])
            top = Counter(frozenset(frozenset(d) for d in p["decks"]) for p in players).most_common(1)[0][1]
            self.assertEqual(top, rk["top_five"]["count"])

    def test_results_up_to_date(self):
        if not (EXP / "analysis.json").exists():
            self.skipTest("analysis.json 없음")
        saved = json.loads((EXP / "analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["reference"], json.loads(json.dumps(A.reference(), ensure_ascii=False)))


if __name__ == "__main__":
    unittest.main()
