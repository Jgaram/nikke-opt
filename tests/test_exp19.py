"""실험 19(accounts.py · run19.py) — 검증 계정 고정 · 계정 options · 배포 사전값 규칙을 확인한다(시뮬 없음)."""

import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP19 = ROOT / "experiments" / "19_first_goal"
if str(EXP19) not in sys.path:
    sys.path.insert(0, str(EXP19))

import accounts as AC  # noqa: E402
import run19 as R  # noqa: E402


class TestAccounts(unittest.TestCase):
    def test_fixed(self):
        a, b = AC.test_scenarios(), AC.test_scenarios()
        self.assertEqual(a, b)
        self.assertEqual([s["id"] for s in a], [f"t{i}" for i in range(1, 9)])
        self.assertEqual(a[0]["missing"], sorted(["그레이브", "맥스웰 : 오디너리 미케닉", "벨벳", "이브"]))
        self.assertEqual(a[4]["start_cube"], "택티컬 베어 큐브")
        self.assertNotIn(AC.CB.DEFAULT_CUBE, a[4]["cubes"])
        self.assertEqual(a[5]["cubes"], {AC.CB.DEFAULT_CUBE: 12, "택티컬 베어 큐브": 9, "렐릭 퀀텀 큐브": 7})
        for s in a:
            self.assertFalse(any(n.startswith("test_") for n in s["missing"]))
            self.assertIn(s["start_cube"], s["cubes"])

    def test_options(self):
        sc = {s["id"]: s for s in AC.test_scenarios()}
        t2 = AC.AccountT(sc["t2"])
        self.assertNotIn("크라운", t2.owned)
        self.assertEqual(t2.options, {})                        # 전원 상 · 장탄 기본 · 렐릭 베어 15 → 평가기 기본
        t5 = AC.AccountT(sc["t5"])
        ch = t5.options["profile"]["chars"]
        self.assertEqual(len(ch), len(t5.owned))
        self.assertTrue(all(e["cube"] == {"name": "택티컬 베어 큐브", "level": 15} for e in ch.values()))
        t7 = AC.AccountT(sc["t7"])
        e = t7.options["profile"]["chars"]
        self.assertTrue(all(v["overload"]["max_ammo_pct"] == 0 for v in e.values()))
        low = [n for n, t in t7.tier.items() if t == "하"]
        self.assertEqual(len(low), 6)
        self.assertEqual(e[low[0]]["overload"]["우월 코드 대미지"], 0)   # 등급 옵션과 장탄 줄을 합친다
        t8 = AC.AccountT(sc["t8"])
        self.assertTrue(all(v["cube"]["level"] == sc["t8"]["cubes"][AC.CB.DEFAULT_CUBE]
                            for v in t8.options["profile"]["chars"].values()))

    def test_strong_pool_frozen(self):
        names = json.loads(AC.STRONG_FILE.read_text(encoding="utf-8"))["names"]
        self.assertEqual(AC.strong_nikkes(), names)
        self.assertEqual(len(names), 45)


class TestRun(unittest.TestCase):
    def test_priors(self):
        by = {"v1": {("크라운", "택티컬 베어 큐브"): [0.01], ("크라운", "렐릭 퀀텀 큐브"): [0.02],
                     ("아니스 : 스타", "택티컬 베어 큐브"): [0.05]}}
        p = R.build_priors(by)
        self.assertNotIn("아니스 : 스타", p["main"])            # 신캐 = 기록 없음 = 큐브 전부
        self.assertIn("렐릭 퀀텀 큐브", p["main"]["크라운"])
        self.assertIn("택티컬 베어 큐브", p["newcube"]["크라운"])   # 관찰 없는 새 큐브는 넣는다

    def test_plans(self):
        keys = [p[0] for p in R.PLANS]
        self.assertEqual(keys, ["B0", "B1", "B2", "P", "B0w", "REF", "PI1", "PNC"])
        self.assertEqual(R.plan_method("T", "newcube"), "T@newcube")
        self.assertEqual(R.plan_method("C", None), "C")
        self.assertIsNone(R.plan_method(None, None))
        self.assertEqual(set(R.PRE), {"U4", "I1"})
        self.assertTrue(all(p.exists() for p in R.PRE.values()))


if __name__ == "__main__":
    unittest.main()
