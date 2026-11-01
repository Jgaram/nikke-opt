"""실험 22 — 시즌 자료 · 요청 options · 사전 계산 계정(평가기 없이)."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "22_ranker_check"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R22 = sys.modules.get("run22") or _load("run22", EXP / "run22.py")
S22 = sys.modules.get("seasons22") or _load("seasons22", EXP / "seasons22.py")


class TestSeasons(unittest.TestCase):
    def test_fixed_seasons(self):
        self.assertEqual(sorted(int(k) for k in R22.SEASON_DATA), list(S22.SEASONS))
        self.assertEqual(S22.SEASONS, (4, 9, 14, 18, 23, 28, 34, 40))

    def test_pool_grows_and_excludes_test_chars(self):
        sizes = [len(R22.season(s)["pool"]) for s in S22.SEASONS]
        self.assertEqual(sizes, sorted(sizes))
        for s in S22.SEASONS:
            v = R22.season(s)
            self.assertFalse(any(n.startswith("test_") for n in v["pool"]))
            self.assertEqual(set(v["pool"]) | set(v["missing"]), set(S22.POOL177))
            self.assertFalse(set(v["pool"]) & set(v["missing"]))
            self.assertTrue(set(v["favorite0"]) <= set(v["pool"]))

    def test_release_order(self):
        self.assertNotIn("레드 후드", R22.season(4)["pool"])      # 2023-11 출시
        self.assertIn("레드 후드", R22.season(9)["pool"])
        self.assertIn("헬름", R22.season(4)["favorite0"])         # 애장품 2025-01
        self.assertNotIn("헬름", R22.season(28)["favorite0"])
        self.assertEqual(R22.season(40)["favorite0"], [])

    def test_element_code(self):
        v = R22.season(40)
        self.assertEqual((v["code"], v["weak"]), ("풍압", "Fire"))


class TestOptions(unittest.TestCase):
    def test_boss_options(self):
        o0, o30 = R22.options(4, "nocore"), R22.options(4, "core30")
        self.assertEqual(o0["enemy"], {"code": "수냉"})
        self.assertEqual(o30["enemy"], {"code": "수냉", "core_px": 30})
        self.assertEqual(o0["profile"], o30["profile"])
        favs = o0["profile"]["chars"]
        self.assertTrue(favs and all(v == {"favorite_stage": 0} for v in favs.values()))
        self.assertNotIn("profile", R22.options(40, "nocore"))
        with self.assertRaises(KeyError):
            R22.options(4, "core52")

    def test_account(self):
        a, b = R22.account(14, "nocore"), R22.account(14, "core30")
        self.assertEqual(a.id, b.id)                    # 같은 난수 — 보스만 다르다
        self.assertEqual(set(a.names), set(R22.season(14)["pool"]))
        self.assertEqual(a.options, R22.options(14, "nocore"))
        self.assertTrue(all(t == "상" for t in a.tier.values()))
        self.assertEqual(R22.run_name(4, "core30"), "S04_core30")

    def test_ranker_decks(self):
        d = R22.ranker_decks(40)
        self.assertEqual(len(d["top_five"]), 5)
        self.assertEqual(len(d["rank1"]), 5)
        self.assertTrue(all(len(q) == 5 for v in d.values() for q in v))


if __name__ == "__main__":
    unittest.main()


A22 = sys.modules.get("analyze22") or _load("analyze22", EXP / "analyze22.py")


class TestJudge(unittest.TestCase):
    @staticmethod
    def row(n25, vt, better="core30"):
        m = {"N25": n25, "D4": 2, "V_top": vt, "V_pack": vt}
        other = {"N25": n25 - 1, "D4": 2, "V_top": vt, "V_pack": vt}
        bb = {"core30": m, "nocore": other} if better == "core30" else {"nocore": m, "core30": other}
        return {"better": better, "tie": False, "by_boss": bb, "N25_prev": 18, "N25_same": 16}

    def test_verdicts(self):
        self.assertEqual(A22.judge([self.row(15, 0.90)] * 3)["verdict"], "얼추 비슷")      # 경계는 통과
        self.assertEqual(A22.judge([self.row(14, 0.95)] * 3)["verdict"], "일부 다름")
        self.assertEqual(A22.judge([self.row(20, 0.89)] * 3)["verdict"], "일부 다름")
        self.assertEqual(A22.judge([self.row(10, 0.80)] * 3)["verdict"], "다름")

    def test_uses_better_boss(self):
        j = A22.judge([self.row(16, 0.95, "nocore"), self.row(18, 0.92, "core30")])
        self.assertEqual(j["N25_med"], 17)
        self.assertEqual(dict(j["better_count"]), {"nocore": 1, "core30": 1})

    def test_main_dealer_and_five_value(self):
        self.assertEqual(A22.main_dealer([["a", 1.0], ["b", 3.0], ["c", 2.0]]), "b")
        vals = {"a,b": {"nocore": 1.0}, "c,d": {"nocore": 2.0}}
        self.assertEqual(A22.five_value([["a", "b"], ["c", "d"]], vals, "nocore"), 3.0)
        self.assertIsNone(A22.five_value([["a", "b"], ["x"]], vals, "nocore"))
