"""실험 6 W2 — menu.py(선택지 생성) 확인. 평가기 없이 돈다. `NIKKE_SIM_BIN`·`NIKKE_CALC_DIR`이 있으면 요청 3개를 실제로 평가한다."""

import json
import os
import sys
import unittest
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent.parent / "experiments" / "06_control_menu"
if str(EXP_DIR) not in sys.path:
    sys.path.insert(0, str(EXP_DIR))

import common  # noqa: E402
import menu  # noqa: E402

SQUAD = ["리타", "에이다", "미란다", "미하라 : 본딩 체인", "홍련 : 흑영"]


def pick(menu_map, label):
    for vs in menu_map.values():
        for v in vs:
            if v["label"] == label:
                return v
    raise KeyError(label)


class TestInfo(unittest.TestCase):
    def test_pool_covered(self):
        names = menu.pool_names()
        self.assertEqual(len(names), 60)
        for n in names:
            menu.nikke(n)  # KeyError면 실패
        src = menu.info()["_source"]
        self.assertEqual(src["commit"], menu.CALC_COMMIT)

    def test_unknown_nikke(self):
        with self.assertRaises(KeyError):
            menu.variants(["없는 니케"])


class TestVariants(unittest.TestCase):
    def test_shape_and_order(self):
        m = menu.variants(SQUAD)
        self.assertEqual(m, menu.variants(SQUAD))
        self.assertEqual(list(m), list(menu.variants(SQUAD)))
        labels = [v["label"] for vs in m.values() for v in vs]
        self.assertEqual(len(labels), len(set(labels)))
        for (who, ax), vs in m.items():
            self.assertTrue(vs)
            self.assertIn(ax, common.AXES)
            if ax in common.SQUAD_AXES:
                self.assertIsNone(who)
            else:
                self.assertIn(who, SQUAD)
            for v in vs:
                self.assertEqual((v["nikke"], v["axis"]), (who, ax))
                self.assertEqual(set(v), {"nikke", "axis", "label", "patch"})
                self.assertTrue(v["label"].startswith(f"{who if who else 'squad'}:{ax}:"))
                if who is None:
                    self.assertEqual(set(v["patch"]), {"operation"})
                else:
                    self.assertEqual(list(v["patch"]["chars"]), [who])
                    self.assertEqual(list(v["patch"]["chars"][who]), ["control"])
                json.dumps(v)
        # 배치 순서대로 니케 축, 그 뒤 스쿼드 축
        whos = [w for w, _ in m]
        self.assertEqual([w for w in whos if w], sorted([w for w in whos if w], key=SQUAD.index))
        self.assertEqual(whos[-2:], [None, None])

    def test_labels_same_across_squads(self):
        a = menu.variants(["에이다", "리타", "크라운"])
        b = menu.variants(["크라운", "헬름", "에이다", "목단"])
        self.assertEqual(a[("에이다", "reload")], b[("에이다", "reload")])
        self.assertEqual(a[("에이다", "click")], b[("에이다", "click")])

    def test_weapon_rules(self):
        m = menu.variants(["아니스 : 스타", "레이븐", "에이다", "리타", "헬름"])
        self.assertNotIn(("아니스 : 스타", "click"), m)          # DOWN_Charge: click 무력
        self.assertNotIn(("리타", "click"), m)                   # 비차지
        raven = [v["label"] for v in m[("레이븐", "click")]]      # 풀차지 전용: 톡톡이 없음, 홀드만
        self.assertEqual(raven, ["레이븐:click:hold_own_fb"])
        ada = [v["label"] for v in m[("에이다", "click")]]
        self.assertEqual(ada[0], "에이다:click:auto")            # 레이어 홀드가 있어 auto가 뜻이 있다
        cams = [v["patch"]["operation"]["camera"] for v in m[(None, "camera")]]
        self.assertEqual(cams, ["아니스 : 스타", "레이븐", "에이다", "헬름"])
        carriers = [v["patch"]["operation"]["tactics"][0]["target"] for v in m[(None, "tactic")]]
        self.assertEqual(carriers, ["에이다"])                   # 아니스·레이븐 톡톡이 불가, 헬름은 풀차지 버충

    def test_layer_toggles(self):
        m = menu.variants(SQUAD)
        self.assertEqual([v["label"] for v in m[("홍련 : 흑영", "cancel")]], ["홍련 : 흑영:cancel:off"])
        self.assertIn("미하라 : 본딩 체인:cover:off", [v["label"] for v in m[("미하라 : 본딩 체인", "cover")]])
        self.assertIn("미란다:burst:pattern_off", [v["label"] for v in m[("미란다", "burst")]])
        self.assertIn("미란다:burst:pattern=전담", [v["label"] for v in m[("미란다", "burst")]])
        on = pick(m, "에이다:cover:on")["patch"]["chars"]["에이다"]["control"]
        self.assertIs(on["hold"], False)  # 레이어 홀드(미란다 동석)와 같은 창 → 함께 끈다
        self.assertNotIn("hold", pick(m, "리타:cover:on")["patch"]["chars"]["리타"]["control"])

    def test_exclude(self):
        old = menu.info().get("exclude")
        try:
            menu.info()["exclude"] = {"리타:reload:A0.3": "test", "squad:camera:에이다": "test"}
            m = menu.variants(SQUAD)
            labels = [v["label"] for vs in m.values() for v in vs]
            self.assertNotIn("리타:reload:A0.3", labels)
            self.assertNotIn("squad:camera:에이다", labels)
        finally:
            menu.info()["exclude"] = old if old is not None else {}


class TestApply(unittest.TestCase):
    def setUp(self):
        self.m = menu.variants(SQUAD)

    def test_merge_reload_and_cancel(self):
        base = {"sim": {"burst_gauge_mode": "fixed"}, "operation": {"auto": True}}
        chosen = [pick(self.m, "리타:reload:C0.1_dry"), pick(self.m, "리타:cancel:on"),
                  pick(self.m, "리타:burst:delay1"), pick(self.m, "squad:camera:에이다")]
        out = menu.apply(base, chosen)
        self.assertEqual(out["chars"]["리타"]["control"]["reload"],
                         {"policy": "finish_by_fb_end", "margin": 0.1, "if_dry": True, "cancel_on_full": True})
        self.assertEqual(out["chars"]["리타"]["control"]["burst"], {"delay": 1.0})
        self.assertEqual(out["operation"], {"auto": True, "camera": "에이다"})
        self.assertEqual(out["sim"], {"burst_gauge_mode": "fixed"})
        self.assertEqual(base, {"sim": {"burst_gauge_mode": "fixed"}, "operation": {"auto": True}})
        self.assertEqual(out, menu.apply(base, list(reversed(chosen))))  # 순서 무관

    def test_no_mutation(self):
        v = pick(self.m, "에이다:click:hold_own_fb+tap")
        before = json.dumps(v, ensure_ascii=False)
        out = menu.apply({}, [v])
        out["chars"]["에이다"]["control"]["click"][0]["lead"] = 9
        self.assertEqual(json.dumps(v, ensure_ascii=False), before)

    def test_duplicate_axis(self):
        with self.assertRaises(ValueError):
            menu.apply({}, [pick(self.m, "리타:reload:A0.3"), pick(self.m, "리타:reload:B0.1")])
        with self.assertRaises(ValueError):
            menu.apply({}, [pick(self.m, "squad:camera:에이다"), pick(self.m, "squad:camera:홍련 : 흑영")])

    def test_conflict_hold_cover(self):
        for hold in ("에이다:click:hold_own_fb", "에이다:click:hold_own_fb+tap"):
            chosen = [pick(self.m, hold), pick(self.m, "에이다:cover:on")]
            self.assertTrue(menu.conflicts(chosen))
            with self.assertRaises(menu.MenuConflict):
                menu.apply({}, chosen)
        ok = [pick(self.m, "에이다:click:tap"), pick(self.m, "에이다:cover:on")]
        self.assertEqual(menu.conflicts(ok), [])
        menu.apply({}, ok)
        # 다른 니케끼리는 충돌하지 않는다
        menu.apply({}, [pick(self.m, "에이다:click:hold_own_fb"), pick(self.m, "리타:cover:on")])


class TestCheck(unittest.TestCase):
    def test_cases(self):
        from nikke_opt.evaluator import EvalRequest
        cases = menu.check_cases(["에이다", "리타"])
        labels = [c["label"] for c in cases]
        self.assertEqual(labels[0], "에이다:base")
        self.assertIn("에이다:combo", labels)
        self.assertIn("squad:camera:에이다", labels)
        self.assertIn("squad:tactic:버충=에이다", labels)
        self.assertNotIn("squad:camera:헬름", labels)  # 동료가 대상인 스쿼드 축은 그 동료 차례에 본다
        for c in cases:
            self.assertEqual(len(c["squad"]), 5)
            self.assertEqual(c["squad"][0], c["nikke"])
            EvalRequest(squad=tuple(c["squad"]), options=c["options"]).to_line()
        combo = next(c for c in cases if c["label"] == "에이다:combo")
        self.assertEqual(menu.conflicts([pick(menu.variants(combo["squad"]), lb) for lb in combo["combo"]]), [])

    def test_table(self):
        t = menu.table(["에이다", "리타"])
        self.assertIn("| 에이다 | RL |", t)
        self.assertIn("2명", t)


@unittest.skipUnless(os.environ.get("NIKKE_SIM_BIN") or os.environ.get("NIKKE_CALC_DIR"),
                     "NIKKE_SIM_BIN · NIKKE_CALC_DIR 없음 — 실제 평가기 확인 생략")
class TestRealEvaluator(unittest.TestCase):
    def test_three_requests(self):
        cases = [c for c in menu.check_cases(["에이다"])
                 if c["label"] in ("에이다:base", "에이다:cover:on", "squad:tactic:버충=에이다")]
        rows, meta = menu.run_check(cases)
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertIsNone(r["error"], r["label"])
            self.assertGreater(r["total_damage"], 0)


if __name__ == "__main__":
    unittest.main()
