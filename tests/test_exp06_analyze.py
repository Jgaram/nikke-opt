"""실험 6 W5 analyze.py — 가짜 기록으로 잴 것 1~5 확인. 평가기를 부르지 않는다."""

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent.parent / "experiments" / "06_control_menu"
if str(EXP_DIR) not in sys.path:
    sys.path.insert(0, str(EXP_DIR))

import analyze  # noqa: E402
import common  # noqa: E402

M = "미하라 : 본딩 체인"
HOLD = "에이다:click:hold_own_fb"
TAP = "에이다:click:tap"
COVER = f"{M}:cover:on"
CAM = "squad:camera:에이다"


def rec(comp, cond, step, variants, dmg, *, start=None, cached=False, preempted=None):
    r = {k: None for k in common.RECORD_KEYS}
    r.update({"comp_id": comp, "condition": cond, "start": start or ("auto" if cond in ("auto", "search_from_auto")
                                                                       else "layer"),
              "step": step, "variants": sorted(variants), "request": {}, "total_damage": dmg,
              "control_detail": {"mode": "solo", "camera_mode": "single", "by_char": {}, "max_concurrent": 1,
                                 "overlap_t": 0.0, "overlaps": [], "preempted": preempted or {}},
              "cached": cached, "error": None, "evaluator": {}, "sim_count": 0})
    return r


COMPS = [
    {"id": "c1", "squad": ["에이다", M, "미란다", "P", "Q"], "skeleton": "1-1-3", "tags": [], "source": "t", "default_damage": 0},
    {"id": "c2", "squad": ["에이다", M, "미란다", "R", "S"], "skeleton": "1-1-3", "tags": [], "source": "t", "default_damage": 0},
    {"id": "c3", "squad": ["에이다", M, "X", "R", "S"], "skeleton": "1-2-2", "tags": [], "source": "t", "default_damage": 0},
    {"id": "c4", "squad": ["T", "U", "V", "W", "Y"], "skeleton": "2-1-2", "tags": [], "source": "t", "default_damage": 0},
]


def fake_records():
    R = []
    # c1: layer 100, 탐색 → HOLD+COVER 110. auto 90. fixed 95
    R += [rec("c1", "auto", 0, [], 90), rec("c1", "layer", 0, [], 100), rec("c1", "fixed_layer", 0, [], 95)]
    R += [rec("c1", "search_from_layer", 0, [], 100, cached=True),
          rec("c1", "search_from_layer", 1, [HOLD], 108),
          rec("c1", "search_from_layer", 2, [TAP], 101),
          rec("c1", "search_from_layer", 3, [HOLD, COVER], 110),
          rec("c1", "search_from_layer", 4, [HOLD, COVER, CAM], 109.5, cached=True, preempted={M: 2})]
    R += [rec("c1", "reference", 0, [HOLD, COVER], 110, start="random:1"),
          rec("c1", "reference", 1, [HOLD], 112, start="random:1")]
    R += [rec("c1", "search_from_auto", 0, [], 90), rec("c1", "search_from_auto", 1, [HOLD], 104)]
    # c2: layer 200, 최선 HOLD 202 (cover 시도했지만 안 고름)
    R += [rec("c2", "auto", 0, [], 210), rec("c2", "layer", 0, [], 200), rec("c2", "fixed_layer", 0, [], 190)]
    R += [rec("c2", "search_from_layer", 0, [], 200),
          rec("c2", "search_from_layer", 1, [HOLD], 202, preempted={"에이다": 1}),
          rec("c2", "search_from_layer", 2, [HOLD, COVER], 201)]
    # c3: 예외 — TAP이 최선, X가 있음. HOLD(최빈) 적용 기록 있음
    R += [rec("c3", "auto", 0, [], 50), rec("c3", "layer", 0, [], 60), rec("c3", "fixed_layer", 0, [], 70)]
    R += [rec("c3", "search_from_layer", 0, [], 60),
          rec("c3", "search_from_layer", 1, [HOLD], 59),
          rec("c3", "search_from_layer", 2, [TAP], 63),
          rec("c3", "search_from_layer", 3, [COVER, TAP], 66),
          rec("c3", "search_from_layer", 4, [CAM, COVER, TAP], 65)]
    # c4: 에이다 없음, 선택지 없음
    R += [rec("c4", "auto", 0, [], 300), rec("c4", "layer", 0, [], 150), rec("c4", "fixed_layer", 0, [], 140),
          rec("c4", "search_from_layer", 0, [], 150)]
    R.append(rec("c4", "search_from_layer", 1, ["T:reload:a"], None))  # 오류 줄
    return R


class TestBasics(unittest.TestCase):
    def test_parse_label(self):
        self.assertEqual(analyze.parse_label(COVER), (M, "cover", "on"))
        self.assertEqual(analyze.parse_label(CAM), (None, "camera", "에이다"))
        self.assertEqual(analyze.parse_label("A:reload:lead=0.3:margin=1"), ("A", "reload", "lead=0.3:margin=1"))
        with self.assertRaises(ValueError):
            analyze.parse_label("에이다:jump:x")

    def test_spearman(self):
        self.assertAlmostEqual(analyze.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(analyze.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        # 동순위: 평균 순위 [1, 2.5, 2.5, 4] vs [1,2,3,4] → Pearson
        self.assertEqual(analyze.average_ranks([5, 7, 7, 9]), [1, 2.5, 2.5, 4])
        rx, ry = [1, 2.5, 2.5, 4], [1, 2, 3, 4]
        mx = my = 2.5
        exp = sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(
            sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
        self.assertAlmostEqual(analyze.spearman([5, 7, 7, 9], [1, 2, 3, 4]), exp)
        self.assertIsNone(analyze.spearman([1], [1]))
        self.assertIsNone(analyze.spearman([1, 1, 1], [1, 2, 3]))
        # 교과서 예: 1 - 6Σd²/(n(n²-1)), 동순위 없음
        x, y = [1, 2, 3, 4, 5], [2, 1, 4, 3, 5]
        self.assertAlmostEqual(analyze.spearman(x, y), 1 - 6 * 4 / (5 * 24))

    def test_describe(self):
        d = analyze.describe([4, 1, 3, 2, None])
        self.assertEqual((d["n"], d["min"], d["max"]), (4, 1, 4))
        self.assertAlmostEqual(d["median"], 2.5)
        self.assertAlmostEqual(d["q1"], 1.75)
        self.assertAlmostEqual(d["q3"], 3.25)
        self.assertEqual(analyze.describe([])["median"], None)


class TestSummary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = analyze.summarize(fake_records(), COMPS)
        cls.comps = {c["comp_id"]: c for c in cls.s["comps"]}

    def test_data(self):
        d = self.s["data"]
        self.assertEqual(d["errors"], 1)
        self.assertEqual(d["comps"], 4)
        self.assertEqual(d["sims"], d["records"] - 2)
        self.assertEqual(d["missing_compositions"], [])

    def test_gains(self):
        c1 = self.comps["c1"]
        self.assertAlmostEqual(c1["gain_vs_layer"], 0.10)
        self.assertAlmostEqual(c1["gain_vs_auto"], 110 / 90 - 1)
        self.assertEqual(c1["best_variants"], sorted([HOLD, COVER]))
        self.assertAlmostEqual(c1["ref_gap"], 112 / 110 - 1)
        self.assertEqual(self.comps["c4"]["gain_vs_layer"], 0.0)
        g = self.s["gains"]["vs_layer"]
        self.assertEqual(g["n"], 4)
        self.assertAlmostEqual(g["median"], (0.01 + 0.10) / 2)  # 0, 0.01, 0.1, 0.1

    def test_layer_fallback(self):
        recs = [r for r in fake_records() if not (r["comp_id"] == "c2" and r["condition"] == "layer")]
        s = analyze.summarize(recs, COMPS)
        c2 = next(c for c in s["comps"] if c["comp_id"] == "c2")
        self.assertEqual(c2["damage"]["layer"], 200)  # search_from_layer step 0

    def test_rank(self):
        pairs = {(p["a"], p["b"]): p for p in self.s["rank"]["pairs"]}
        self.assertEqual(len(pairs), 6)
        p = pairs[("layer", "search_from_layer")]
        self.assertEqual(p["n"], 4)
        self.assertAlmostEqual(p["spearman"], 1.0)
        self.assertTrue(p["top_same"] is None)  # 4 < top_k 5
        q = pairs[("auto", "layer")]
        # auto: c4 300 > c2 210 > c1 90 > c3 50 ; layer: c2 200 > c4 150 > c1 100 > c3 60
        self.assertEqual(q["reversal_count"], 1)
        self.assertEqual(q["reversals"][0]["hi_in_a"], "c4")
        s2 = analyze.summarize(fake_records(), COMPS, top_k=2)
        q2 = next(p for p in s2["rank"]["pairs"] if (p["a"], p["b"]) == ("auto", "layer"))
        self.assertTrue(q2["top_same"])
        self.assertEqual(q2["top_overlap"], 2)

    def test_uniqueness(self):
        items = {(it["nikke"], it["axis"]): it for it in self.s["uniqueness"]["items"]}
        click = items[("에이다", "click")]
        self.assertEqual(click["n"], 3)
        self.assertEqual(click["mode"], HOLD)
        self.assertAlmostEqual(click["mode_share"], 2 / 3)
        (exc,) = click["exceptions"]
        self.assertEqual((exc["comp_id"], exc["choice"]), ("c3", TAP))
        # c3 최선 {COVER, TAP} 66 → 최빈 적용 {COVER, HOLD} 기록 없음 → 미측정
        self.assertFalse(exc["measured"])
        self.assertEqual(exc["peer_candidates"], ["X"])
        cover = items[(M, "cover")]
        self.assertEqual(cover["n"], 3)
        self.assertEqual(cover["counts"], {"(바꾸지 않음)": 1, COVER: 2})
        self.assertEqual(cover["mode"], COVER)
        (e2,) = cover["exceptions"]
        # c2 최선 [HOLD] 202 → 최빈 적용 [COVER, HOLD] 201 기록 있음
        self.assertTrue(e2["measured"])
        self.assertAlmostEqual(e2["gain"], 202 / 201 - 1)
        self.assertEqual(e2["peer_candidates"], [])  # R·S는 c3(최빈)에도 있다
        self.assertEqual(self.s["uniqueness"]["squad_choices"]["c1"], [])
        pooled = self.s["uniqueness"]["pooled"]
        self.assertEqual(pooled["exceptions"], 2)
        self.assertEqual(pooled["exceptions_measured"], 1)
        self.assertEqual(pooled["exceptions_with_peer_candidate"], 1)

    def test_uniqueness_offered_axis_only(self):
        items = {(it["nikke"], it["axis"]) for it in self.s["uniqueness"]["items"]}
        # c4의 T:reload는 오류 줄에서만 시도됐다 — 시도된 축이므로 「바꾸지 않음」 한 번으로 센다
        self.assertIn(("T", "reload"), items)
        self.assertNotIn(("U", "reload"), items)

    def test_convergence(self):
        runs = {(r["comp_id"], r["condition"], r["start"]): r for r in self.s["convergence"]["runs"]}
        r = runs[("c1", "search_from_layer", "layer")]
        self.assertEqual(r["final"], 110)
        self.assertEqual(r["evals"], 5)
        self.assertEqual(r["sims"], 3)
        # 99% of 110 = 108.9 → step 3 (108 < 108.9), 시뮬: step0 cached → 1,2,3 = 3
        self.assertEqual(r["to_own"]["0.99"], {"step": 3, "sims": 3})
        # 조합 탐색 최선 = reference 112 → 99% 110.88 → 미도달
        self.assertIsNone(r["to_comp"]["0.99"])
        self.assertEqual(r["comp_best"], 112)
        r2 = runs[("c2", "search_from_layer", "layer")]
        self.assertEqual(r2["to_own"]["0.99"], {"step": 0, "sims": 1})
        self.assertEqual(r2["to_own"]["0.999"], {"step": 1, "sims": 2})
        self.assertIn(("c1", "reference", "random:1"), runs)
        bs = self.s["convergence"]["by_start"]
        self.assertEqual(set(bs), {"search_from_layer", "search_from_auto", "reference"})
        self.assertEqual(bs["search_from_layer"]["to_comp:0.99:missed"], 1)

    def test_camera(self):
        cam = {r["comp_id"]: r for r in self.s["camera"]["rows"]}
        self.assertEqual(cam["c1"]["best_preempted"], {})
        self.assertEqual(cam["c1"]["all_preempted"], {M: {"preempted": 2, "records": 1}})
        self.assertEqual(cam["c2"]["best_preempted"], {"에이다": 1})
        self.assertEqual(self.s["camera"]["comps_with_preemption_in_best"], 1)
        self.assertEqual(self.s["camera"]["comps_with_preemption_any"], 2)
        self.assertEqual(self.s["camera"]["unknown_keys"], {})
        recs = fake_records()
        recs[0]["control_detail"]["new_key"] = 1
        recs[1]["control_detail"] = None
        s = analyze.summarize(recs, COMPS)
        self.assertEqual(s["camera"]["unknown_keys"], {"new_key": 1})
        self.assertEqual(s["camera"]["missing_control_detail"], 1)

    def test_criteria(self):
        cr = {c["line"]: c for c in self.s["criteria"]}
        self.assertIsNone(cr[1]["values"]["top_same"])  # 조합 4개 < 상위 5
        self.assertFalse(cr[1]["met"])  # 그래도 중앙 5.5% ≥ 1%라 거짓
        self.assertFalse(analyze.summarize(fake_records(), COMPS, top_k=2)["criteria"][0]["met"])  # 중앙 5.5% ≥ 1%
        s = analyze.summarize(fake_records(), COMPS, top_k=2, gain_median_max=0.2)
        self.assertTrue(s["criteria"][0]["met"])
        self.assertTrue(cr[4]["met"])  # c1 참조 +1.8%
        self.assertFalse(analyze.summarize(fake_records(), COMPS, ref_gap_min=0.05)["criteria"][3]["met"])
        # 기본(유의 0.3%): 예외 둘 다 유의(c2 cover +0.5%, c3 click 미측정) → 실질 최빈 1 − 2/7
        v2 = cr[2]["values"]
        self.assertAlmostEqual(v2["effective_mode_share"], 5 / 7)
        self.assertEqual((v2["significant"], v2["significant_explained"], v2["significant_weak"]), (2, 1, 1))
        self.assertAlmostEqual(v2["explained_share"], 0.5)
        self.assertAlmostEqual(v2["explained_share_strong"], 0.0)
        self.assertFalse(cr[2]["met"])
        self.assertTrue(cr[3]["met"])  # 0.71 < 0.8 그리고 0.5 < 0.6
        self.assertEqual(self.s["candidate"]["line"], 4)  # 4줄이 먼저

    def test_significance_and_candidate(self):
        # 유의 1%: c2 cover(+0.5%)는 유의하지 않음 → 유의 예외는 c3 click 하나, 후보 X(약한 근거)
        kw = dict(exception_gain_min=0.01, ref_gap_min=0.05)
        s = analyze.summarize(fake_records(), COMPS, **kw)
        u = s["uniqueness"]["pooled"]
        self.assertEqual((u["significant"], u["significant_explained"], u["significant_weak"]), (1, 1, 1))
        self.assertAlmostEqual(u["effective_mode_share"], 6 / 7)
        self.assertAlmostEqual(u["explained_share"], 1.0)
        self.assertAlmostEqual(u["explained_share_strong"], 0.0)
        cr = {c["line"]: c["met"] for c in s["criteria"]}
        self.assertEqual((cr[1], cr[2], cr[3], cr[4]), (False, True, False, False))
        self.assertEqual(s["candidate"]["line"], 2)
        cover = next(it for it in s["uniqueness"]["items"] if it["axis"] == "cover")
        self.assertFalse(cover["exceptions"][0]["significant"])
        # 역전 기준 0건 → 3줄도 해당 → 2·3 함께 → 후보 없음
        s = analyze.summarize(fake_records(), COMPS, reversals_max=0, **kw)
        self.assertIsNone(s["candidate"]["line"])
        self.assertTrue(any("함께" in n for n in s["candidate"]["notes"]))
        # 1줄과 2줄이 함께 → 1줄, 메모
        s = analyze.summarize(fake_records(), COMPS, top_k=2, gain_median_max=0.2, **kw)
        self.assertEqual(s["candidate"]["line"], 1)
        self.assertTrue(any("2줄도" in n for n in s["candidate"]["notes"]))
        # 기본 기준에서 참조만 빼면 3줄
        s = analyze.summarize(fake_records(), COMPS, ref_gap_min=0.05)
        self.assertEqual(s["candidate"]["line"], 3)

    def test_partial_conditions(self):
        # search_from_auto · reference가 없는 조합은 그 지표에서 빠진다
        s = self.s
        self.assertEqual(s["reference"]["summary"]["n"], 1)
        self.assertEqual([r["comp_id"] for r in s["reference"]["rows"]], ["c1"])
        self.assertEqual(s["convergence"]["by_start"]["search_from_auto"]["runs"], 1)
        self.assertEqual(s["gains"]["vs_auto"]["n"], 4)
        recs = [r for r in fake_records() if r["condition"] != "reference"]
        s2 = analyze.summarize(recs, COMPS)
        self.assertIsNone(s2["criteria"][3]["met"])
        self.assertNotIn("reference", s2["convergence"]["by_start"])
        self.assertTrue(any("4줄 판정 불가" in n for n in s2["candidate"]["notes"]))

    def test_render(self):
        text = analyze.render(self.s)
        for h in ("## 지표 정의", "## 판단 기준 표시", "## 1. 탐색 이득", "## 2. 조건 사이 순위 상관", "## 3. 니케 고유성",
                  "## 4. 수렴", "## 5. solo 카메라 경합", "## 참조 탐색 대비", "미측정", "+10.00%"):
            self.assertIn(h, text)
        self.assertNotIn("본 실행 전", text)
        json.dumps(self.s, ensure_ascii=False)

    def test_empty(self):
        s = analyze.summarize([], [])
        text = analyze.render(s)
        self.assertIn("본 실행 전 — 형식만", text)
        self.assertTrue(all(c["met"] is None for c in s["criteria"]))

    def test_main(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            log = d / "run.jsonl"
            for r in fake_records():
                common.append_record(log, r)
            cp = d / "comps.json"
            cp.write_text(json.dumps(COMPS, ensure_ascii=False), encoding="utf-8")
            out, js = d / "results.md", d / "s.json"
            self.assertEqual(analyze.main([str(log), "--compositions", str(cp), "--out", str(out), "--json", str(js)]), 0)
            self.assertIn("## 3. 니케 고유성", out.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(js.read_text(encoding="utf-8"))["data"]["comps"], 4)


if __name__ == "__main__":
    unittest.main()
