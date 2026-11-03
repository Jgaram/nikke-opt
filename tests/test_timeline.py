"""nikke_opt/timeline.py — 평가기 `sim.trace`(nikke-calc-rs)를 화면용 모양으로 줄이는 것(시뮬 0)."""

from __future__ import annotations

import unittest

from nikke_opt.evaluator import EvalRequest
from nikke_opt.timeline import compact, traced

SQUAD = ("아니스 : 스타", "크라운", "마스트 : 로망틱 메이드", "퀸(마코토)", "유키코")
RAW = {  # nikke-calc-rs `trace_json` 모양(S40-0 앞부분)
    "bursts": [{"t": 3.3666666666666596, "stage": 1, "caster": "아니스 : 스타", "reenter": False},
               {"t": 3.4666666666666592, "stage": 2, "caster": "마스트 : 로망틱 메이드", "reenter": False},
               {"t": 3.566666666666659, "stage": 3, "caster": "퀸(마코토)", "reenter": True},
               {"t": 9.0, "stage": 1, "caster": None, "reenter": False}],
    "full_bursts": [{"t0": 3.949999999999991, "t1": 13.950000000000273}],
    "controls": [{"t0": 13.30000000000024, "t1": 13.466666666666915, "caster": "퀸(마코토)", "input": "cover", "mode": "cover",
                  "producer": "엄폐 시작(장전컨)"},
                 {"t0": 14.0, "t1": 16.5, "caster": "크라운", "input": "click", "mode": "tap", "producer": "burst_charge"},
                 {"t0": 20.0, "t1": 21.0, "caster": "유키코", "input": "cover_all", "mode": "cover", "producer": "seq"}],
    "camera": [{"t": 0.0, "names": ["아니스 : 스타"]}, {"t": 13.30000000000024, "names": ["퀸(마코토)"]}, {"t": 30.0, "names": []}],
}


class TestTimeline(unittest.TestCase):
    def test_traced_only_adds_trace(self):
        r = EvalRequest(SQUAD, options={"sim": {"expected": True}, "operation": {"camera": "크라운"}})
        t = traced(r)
        self.assertEqual(t.options["sim"], {"expected": True, "trace": True})
        self.assertEqual(t.options["operation"], {"camera": "크라운"})
        self.assertEqual(r.options["sim"], {"expected": True})      # 원래 요청은 그대로
        line = t.to_line()
        self.assertTrue(line["sim"]["trace"])
        self.assertEqual(line["sim"]["burst_gauge_mode"], "accumulate")

    def test_compact(self):
        tl = compact(RAW, SQUAD, 180.0)
        self.assertEqual(tl["v"], 1)
        self.assertEqual(tl["squad"], list(SQUAD))
        self.assertEqual(tl["dur"], 180.0)
        self.assertEqual(tl["fb"], [[3.95, 13.95]])
        self.assertEqual(tl["b"], [[3.367, 1, 0, 0], [3.467, 2, 2, 0], [3.567, 3, 3, 1], [9.0, 1, -1, 0]])
        self.assertEqual(tl["c"], [[13.3, 13.467, 3, "cover", "엄폐 시작(장전컨)"], [14.0, 16.5, 1, "tap", "burst_charge"],
                                   [20.0, 21.0, 4, "all", "seq"]])
        self.assertEqual(tl["cam"], [[0.0, 0], [13.3, 3], [30.0, -1]])


if __name__ == "__main__":
    unittest.main()
