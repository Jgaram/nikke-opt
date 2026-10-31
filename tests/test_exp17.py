"""실험 17(cubes.py · run17.py · analyze17.py) — 큐브 선택지 · 합친 공간 · 사전값 · 판단 규칙을 합성 자료로 확인한다."""

import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP17 = ROOT / "experiments" / "17_cube_control"
if str(EXP17) not in sys.path:
    sys.path.insert(0, str(EXP17))

import analyze17 as A  # noqa: E402
import cubes as CB  # noqa: E402
import run17 as R  # noqa: E402

SQUAD = ["아니스 : 스타", "크라운", "네온 : 비전 아이", "아스카 : WILLE", "프리바티"]


class TestCubes(unittest.TestCase):
    def test_catalog(self):
        names = CB.supported()
        self.assertEqual(len(names), 15)
        self.assertIn(CB.DEFAULT_CUBE, names)
        self.assertNotIn("렐릭 힐링 큐브", names)      # 미지원
        self.assertNotIn("렐릭 어시스터 큐브", names)
        self.assertIn("렐릭 디스트로이 큐브", names)   # 허수아비에서 효과가 없어도 규칙으로 지우지 않는다
        src = json.loads(CB.CUBES_PATH.read_text(encoding="utf-8"))["_source"]
        self.assertEqual(len(src["sha256"]), 64)

    def test_variants(self):
        inv = CB.full_inventory()
        vs = CB.cube_variants("크라운", inv)
        self.assertEqual(len(vs), 14)
        self.assertNotIn(f"크라운:cube:{CB.DEFAULT_CUBE}", [v["label"] for v in vs])
        v = vs[0]
        self.assertEqual(v["patch"], {"chars": {"크라운": {"cube": {"name": v["label"].split(":cube:")[1], "level": 15}}}})
        some = CB.cube_variants("크라운", inv, allowed=["택티컬 베어 큐브", "렐릭 피어싱 큐브", CB.DEFAULT_CUBE])
        self.assertEqual([x["label"] for x in some], ["크라운:cube:택티컬 베어 큐브", "크라운:cube:렐릭 피어싱 큐브"])
        # 계정에 없는 큐브는 선택지가 아니다
        self.assertEqual(len(CB.cube_variants("크라운", {"택티컬 베어 큐브": 7})), 1)
        self.assertEqual(CB.cube_variants("크라운", {"택티컬 베어 큐브": 7})[0]["patch"]["chars"]["크라운"]["cube"]["level"], 7)

    def test_joint_order_and_apply(self):
        import menu as menu6
        fn = CB.joint_variants_fn()
        sp = fn(SQUAD)
        keys = list(sp)
        ctrl = list(menu6.variants(SQUAD))
        self.assertEqual(set(keys) - set(ctrl), {(w, "cube") for w in SQUAD})
        # 니케마다 컨트롤 축 뒤에 cube, 스쿼드 축은 맨 뒤
        first_squad = next(i for i, k in enumerate(keys) if k[0] is None)
        self.assertTrue(all(k[0] is None for k in keys[first_squad:]))
        for w in SQUAD:
            mine = [i for i, k in enumerate(keys) if k[0] == w]
            self.assertEqual(keys[mine[-1]], (w, "cube"))
            self.assertEqual(mine, list(range(mine[0], mine[-1] + 1)))
        cube = sp[(SQUAD[0], "cube")][0]
        rel = next(v for v in sp[(SQUAD[0], "reload")])
        opts = menu6.apply({"profile": {"base": "default"}}, [cube, rel])
        self.assertIn("cube", opts["chars"][SQUAD[0]])
        self.assertIn("reload", opts["chars"][SQUAD[0]]["control"])
        self.assertEqual(opts["profile"], {"base": "default"})
        only = CB.joint_variants_fn(control=False)(SQUAD)
        self.assertEqual(list(only), [(w, "cube") for w in SQUAD])

    def test_allowed_callable(self):
        fn = CB.joint_variants_fn(allowed=lambda w: ["택티컬 베어 큐브"] if w == "크라운" else None)
        sp = fn(SQUAD)
        self.assertEqual(len(sp[("크라운", "cube")]), 1)
        self.assertEqual(len(sp[("프리바티", "cube")]), 14)
        self.assertEqual(CB.cube_of(["크라운:cube:택티컬 베어 큐브", "크라운:reload:A0.3"], "크라운"), "택티컬 베어 큐브")
        self.assertEqual(CB.cube_of(["크라운:reload:A0.3"], "크라운"), CB.DEFAULT_CUBE)


class TestRun(unittest.TestCase):
    def test_targets(self):
        t = R.build_targets(json.loads(R.SOURCE_TARGETS.read_text(encoding="utf-8")))
        comps = [c for d in t["scenarios"].values() for c in d["comps"]]
        self.assertEqual(len(comps), 116)
        self.assertEqual(sum(c["ref"] for c in comps), 24)
        for d in t["scenarios"].values():
            bs = [c["B"] for c in d["comps"]]
            self.assertEqual(bs, sorted(bs, reverse=True))
            self.assertTrue(all(c["ref"] for c in d["comps"][:3]))
        self.assertEqual(comps[0]["id"], R.R9.post_id("v1", comps[0]["squad"]))
        committed = json.loads((R.LOG / "targets.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, json.loads(json.dumps(t, ensure_ascii=False)))

    def test_split_label(self):
        self.assertEqual(R.split_label("아니스 : 스타:cube:택티컬 베어 큐브"), ("아니스 : 스타", "cube", "택티컬 베어 큐브"))
        self.assertEqual(R.split_label("squad:camera:스노우 화이트 : 헤비암즈"), ("squad", "camera", "스노우 화이트 : 헤비암즈"))
        self.assertEqual(R.split_label("나유타:reload:C0.1_dry"), ("나유타", "reload", "C0.1_dry"))

    def test_best_at(self):
        rows = [{"step": i, "total_damage": d, "variants": [str(i)]} for i, d in enumerate([5, None, 7, 6, 9])]
        self.assertEqual(R.best_at(rows, 3), (7, ["2"]))
        self.assertEqual(R.best_at(rows, 5), (9, ["4"]))
        self.assertEqual(R.best_at(rows, 1), (5, ["0"]))

    def test_cube_deltas_and_prior(self):
        import math
        a, b = "크라운:cube:택티컬 베어 큐브", "크라운:cube:렐릭 피어싱 큐브"
        r = "크라운:reload:A0.3"
        rows = [{"variants": [], "total_damage": 100}, {"variants": [a], "total_damage": 110},
                {"variants": [b], "total_damage": 90}, {"variants": [r], "total_damage": 100},
                {"variants": [a, r], "total_damage": 121}, {"variants": ["x:cube:렐릭 퀀텀 큐브"], "total_damage": None}]
        d = R.cube_deltas(rows)
        self.assertAlmostEqual(d[("크라운", "택티컬 베어 큐브")][0], math.log(1.1))
        self.assertEqual(len(d[("크라운", "택티컬 베어 큐브")]), 2)          # [] → [a], [r] → [a, r]
        self.assertAlmostEqual(d[("크라운", "렐릭 피어싱 큐브")][0], math.log(0.9))
        self.assertNotIn(("x", "렐릭 퀀텀 큐브"), d)
        by = {"v1": d, "v2": {("크라운", "렐릭 퀀텀 큐브"): [0.5]}, "v3": {("헬름", "렐릭 퀀텀 큐브"): [0.1]}}
        p = R.build_prior(by, "v2", top_k=1)
        cubes = [c for c in CB.supported() if c != CB.DEFAULT_CUBE]
        # v2를 빼면 크라운 관찰 = 택티컬 베어 · 피어싱 → 상위 1 + 관찰 안 한 12종
        self.assertIn("택티컬 베어 큐브", p["크라운"])
        self.assertNotIn("렐릭 피어싱 큐브", p["크라운"])
        self.assertEqual(len(p["크라운"]), len(cubes) - 1)
        self.assertEqual(p["크라운"], sorted(p["크라운"], key=cubes.index))
        self.assertNotIn("나유타", p)                                          # 기록 없는 니케 = 전부
        p1 = R.build_prior(by, "v1", top_k=1)
        self.assertEqual(len(p1["크라운"]), len(cubes))                         # 퀀텀 관찰 1 + 관찰 안 한 13종

    def test_job_budget(self):
        self.assertEqual(R.job_max_sims(1, True), 400 * 2 + 200 + 1200)
        self.assertEqual(R.job_max_sims(2, False), 400)


class TestJudge(unittest.TestCase):
    def q(self, m, p10=None):
        return {"median": m, "p10": m - 0.01 if p10 is None else p10}

    def test_small(self):
        v = A.judge(0.002, 0.001, {"J": self.q(0.99)}, {})
        self.assertEqual(v["case"], 1)

    def test_pick_and_budget(self):
        q400 = {"J": self.q(0.995), "SQ": self.q(0.9945), "JT": self.q(0.990)}
        q200 = {"J": self.q(0.993), "JT": self.q(0.992)}
        v = A.judge(0.01, 0.005, q400, q200)
        self.assertEqual(v["case"], 2)
        self.assertEqual(v["method"], "J")            # SQ와 0.1%p 안, 10백분위 같으면 J 먼저
        self.assertEqual(v["budget"], 200)            # 400 대비 −0.2%p
        self.assertFalse(v["prior_helps"])

    def test_tie_by_p10_and_prior(self):
        q400 = {"J": self.q(0.995, 0.97), "SQ": self.q(0.9948, 0.99), "JT": self.q(0.99)}
        q200 = {"J": self.q(0.980), "JT": self.q(0.986)}
        v = A.judge(0.01, 0.0, q400, q200)
        self.assertEqual(v["method"], "SQ")
        self.assertEqual(v["budget"], 400)            # SQ는 200판이 없다
        self.assertTrue(v["prior_helps"])             # JT200 − J200 = +0.6%p

    def test_jt_wins(self):
        q400 = {"J": self.q(0.98), "SQ": self.q(0.97), "JT": self.q(0.99)}
        q200 = {"J": self.q(0.95), "JT": self.q(0.985)}
        v = A.judge(0.02, 0.01, q400, q200)
        self.assertEqual((v["method"], v["budget"]), ("JT", 400))


if __name__ == "__main__":
    unittest.main()
