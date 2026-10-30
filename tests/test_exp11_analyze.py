"""실험 11 분석(analyze11.py) — 합성 실행 요약으로 H · G 계산, 판단 규칙, 질문 1 · 2, 결과 쓰기를 확인한다."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

EXP11 = Path(__file__).resolve().parent.parent / "experiments" / "11_wide_precompute"
if str(EXP11) not in sys.path:
    sys.path.insert(0, str(EXP11))

import analyze11 as B  # noqa: E402

SCEN = list(B.VAL_SCENARIOS)
BASE = 100.0
POOL = B.POOL


def T_of(g, base_methods=("K", "P")):
    """g: 기법 → 예산 → [시나리오별 H(K 대비)]. K = 100, 나머지 = 100 · (1 + H). 없는 기법은 H = 0. P가 g에 없으면 K와 같다."""
    out = {}
    for i, s in enumerate(SCEN):
        for b in B.BUDGETS:
            out[(s, POOL, "K", b)] = BASE
            for m in (B.REF,) + B.CANDS:
                out[(s, POOL, m, b)] = BASE * (1 + g.get(m, {}).get(b, [0.0] * 8)[i])
    return out


def bad(keep, h=-0.05):
    """keep에 없는 후보는 모든 예산에서 「못하다」로 둔다(기본 H = 0은 「못지않다」라서)."""
    return {m: {b: [h] * 8 for b in B.BUDGETS} for m in B.CANDS if m not in keep}


def summary(s, m, b, total, history=None, squads=None, alt=None, alt20=None, start=None):
    history = history or [{"evals": 40, "pack": total * 0.8, "kick": False}, {"evals": b, "pack": total, "kick": False}]
    return {"scenario": s, "name": f"이름 {s}", "pool": POOL, "method": m, "budget": b, "evals": history[-1]["evals"],
            "errors": 0, "start": start or {"evals": history[0]["evals"], "pack": history[0]["pack"]},
            "history": history, "kicks": [],
            "final": {"total": total, "squads": squads if squads is not None else []},
            "alt": alt or {"total": total * 0.98, "squads": [], "shared_nikkes": 23},
            "alt20": alt20 or {"total": total * 0.95, "squads": [], "shared_nikkes": 19},
            "sims_during": 10, "seconds": 1.5}


PRE_EVALS = {"P": 4454, "PB15": 15000, "PB30": 30000, "PN": 9000, "PM": 14000}


class TestRules(unittest.TestCase):
    def test_h_and_g(self):
        g = {"PN": {2000: [0.02] * 8, 800: [-0.01] * 8}, "P": {2000: [-0.04] * 8, 800: [0.0] * 8}}
        T = T_of(g)
        self.assertAlmostEqual(B.rel(T, "PN", "K", 2000)[0], 0.02)
        self.assertAlmostEqual(B.rel(T, "PN", "P", 2000)[0], 1.02 / 0.96 - 1)  # G = PN / P − 1
        self.assertAlmostEqual(B.rel(T, "PN", "P", 800)[0], 0.99 / 1.0 - 1)
        self.assertEqual(B.rel(T, "PN", "K", 2000, ["v1", "v2"]).__len__(), 2)

    def test_boundaries(self):
        self.assertTrue(B.A.noninferior([0.0] * 7 + [-0.031]))
        self.assertFalse(B.A.noninferior([0.0] * 6 + [-0.031, -0.04]))
        self.assertTrue(B.A.noninferior([99.5 / 100 - 1] * 6 + [0.97 - 1] * 2))
        self.assertTrue(B.A.better([0.01] * 6 + [-0.01, -0.02]))
        self.assertFalse(B.A.better([0.01] * 5 + [-0.01] * 3))

    def test_stat_requires_all_scenarios(self):
        s = B.stat([0.02] * 7)
        self.assertFalse(s["complete"])
        self.assertFalse(s["better"] or s["noninf"] or s["worse"])
        self.assertEqual(B.label(s), "판단 불가(7/8)")
        s = B.stat([0.02] * 8)
        self.assertEqual(B.label(s), "낫다 · 못지않다")
        self.assertEqual(B.label(B.stat([-0.01] * 8)), "못하다")
        self.assertEqual(B.label(B.stat([-0.004] * 4 + [0.004] * 4)), "못지않다")
        self.assertEqual(B.label(B.stat([-0.1] * 8)), "못하다")
        self.assertEqual(B.label(B.stat([0.0] * 6 + [-0.04, -0.05])), "해당 없음")


class TestJudge1(unittest.TestCase):
    def test_row1_and_tiebreak_by_evals(self):
        g = bad(["PB15", "PN"])  # PB15 · PN 모두 둘 다 통과 → 평가 수가 작은 PN
        g["PB15"] = {b: [0.03] * 8 for b in B.BUDGETS}
        g["PN"] = {b: [0.0] * 8 for b in B.BUDGETS}
        j = B.judge1(T_of(g), PRE_EVALS)
        self.assertEqual((j["line"], j["pick"], sorted(j["names"])), (1, "PN", ["PB15", "PN"]))

    def test_row1_tie_evals_then_2000_then_800(self):
        g = bad(["PB15", "PN"])
        g["PB15"] = {800: [0.0] * 8, 2000: [0.01] * 8}
        g["PN"] = {800: [0.03] * 8, 2000: [0.01] * 8}
        same = dict(PRE_EVALS, PB15=9000)  # 평가 수 같음
        self.assertEqual(B.judge1(T_of(g), same)["pick"], "PN")  # 2,000 같으면 800이 큰 쪽
        g["PB15"][2000] = [0.02] * 8
        self.assertEqual(B.judge1(T_of(g), same)["pick"], "PB15")  # 2,000 중앙이 큰 쪽

    def test_row2(self):
        g = bad(["PB30", "PM"])
        g["PB30"] = {800: [-0.02] * 8, 2000: [0.0] * 8}  # 800 「못하다」 아님이지만 중앙 −2% → 못지않다 아님
        g["PM"] = {800: [-0.01] * 8, 2000: [0.0] * 8}
        j = B.judge1(T_of(g), PRE_EVALS)
        self.assertEqual((j["line"], sorted(j["names"])), (2, ["PB30", "PM"]))
        self.assertEqual(j["pick"], "PM")  # 평가 수 14,000 < 30,000

    def test_row3_and_p_not_candidate(self):
        g = bad([])
        g["P"] = {b: [0.05] * 8 for b in B.BUDGETS}  # P는 후보가 아니다
        j = B.judge1(T_of(g), PRE_EVALS)
        self.assertEqual((j["line"], j["pick"], j["names"]), (3, None, []))
        self.assertEqual(j["noninf"]["P"], [800, 2000])

    def test_incomplete_scenarios_cannot_pass(self):
        T = T_of({})
        for s in SCEN[:2]:
            for m in B.CANDS:
                T.pop((s, POOL, m, 2000))
        j = B.judge1(T, PRE_EVALS)
        self.assertEqual(j["line"], 3)  # 2,000이 6개뿐 → 판단 불가, 통과 못 함
        self.assertEqual(B.label(j["stats"]["PN"][2000]), "판단 불가(6/8)")


class TestJudge2(unittest.TestCase):
    def test_default_follows_q1_when_row1_or_2(self):
        g = bad(["PM"])
        g["PM"] = {b: [0.01] * 8 for b in B.BUDGETS}
        T = T_of(g)
        q1 = B.judge1(T, PRE_EVALS)
        q2 = B.judge2(T, q1, PRE_EVALS)
        self.assertEqual((q1["line"], q2["default"]), (1, "PM"))
        self.assertIn("질문 1", q2["how"])

    def test_fallback_eligible_largest_h(self):
        # 모든 후보가 K에 못 미침(3줄). P가 더 나쁘고, PB15 · PN은 P보다 확실히 낫다.
        g = {"P": {b: [-0.08] * 8 for b in B.BUDGETS},
             "PB15": {b: [-0.05] * 8 for b in B.BUDGETS}, "PN": {b: [-0.04] * 8 for b in B.BUDGETS},
             "PB30": {b: [-0.08] * 8 for b in B.BUDGETS}, "PM": {b: [-0.08] * 8 for b in B.BUDGETS}}
        T = T_of(g)
        q1 = B.judge1(T, PRE_EVALS)
        self.assertEqual(q1["line"], 3)
        q2 = B.judge2(T, q1, PRE_EVALS)
        self.assertEqual(sorted(q2["eligible"]), ["PB15", "PN"])
        self.assertEqual(q2["default"], "PN")  # H 중앙이 큰 쪽
        self.assertFalse(q2["per"]["PB30"]["eligible"])  # G = 0

    def test_fallback_keeps_p(self):
        g = {m: {b: [-0.08] * 8 for b in B.BUDGETS} for m in (B.REF,) + B.CANDS}
        T = T_of(g)
        q2 = B.judge2(T, B.judge1(T, PRE_EVALS), PRE_EVALS)
        self.assertEqual((q2["eligible"], q2["default"]), ([], "P"))

    def test_eligibility_blocked_by_800_worse(self):
        g = {"P": {b: [-0.08] * 8 for b in B.BUDGETS}, "PN": {2000: [-0.04] * 8, 800: [-0.10] * 8}}
        for m in ("PB15", "PB30", "PM"):
            g[m] = {b: [-0.08] * 8 for b in B.BUDGETS}
        T = T_of(g)
        q2 = B.judge2(T, B.judge1(T, PRE_EVALS), PRE_EVALS)
        self.assertTrue(q2["per"]["PN"]["g2000"]["better"])
        self.assertTrue(q2["per"]["PN"]["g800"]["worse"])
        self.assertFalse(q2["per"]["PN"]["eligible"])
        self.assertEqual(q2["default"], "P")


class TestMetrics(unittest.TestCase):
    def test_pack_at_and_curves(self):
        h = [{"evals": 4000, "pack": 10.0}, {"evals": 5200, "pack": 11.0}, {"evals": 12000, "pack": 12.0}]
        self.assertEqual(B.pack_at(h, 5000), 11.0)
        self.assertEqual(B.pack_at(h, 12000), 12.0)
        self.assertIsNone(B.pack_at(h, 15000))
        pre = {"PB30": {"history": h, "final": {"total": 12.5}}, "PB15": {"history": h, "final": {"total": 12.0}},
               "P": {"history": h, "final": {"total": 9.0}}}
        rows = {r["name"]: r for r in B.curve_rows(pre)}
        self.assertEqual(rows["PB30"]["at"][10000], 12.0)
        self.assertIsNone(rows["PB30"]["at"][15000])
        self.assertIsNone(rows["PB15"]["at"][15000])  # PB15는 5,000 · 10,000만
        self.assertEqual(rows["PB15"]["at"][5000], 11.0)
        self.assertEqual(rows["P"]["final"], 9.0)
        self.assertEqual(rows["P"]["at"], {t: None for t in B.CURVE_COLS})

    def test_recall(self):
        sq = [[10.0, [f"n{i}" for i in range(5 * j, 5 * j + 5)]] for j in range(5)]  # n0..n24
        runs = {("v1", POOL, "K", 2000): summary("v1", "K", 2000, 100.0, squads=sq)}
        narrowed = [f"n{i}" for i in range(0, 20)] + ["x"]
        p60 = [f"n{i}" for i in range(10, 25)]
        rc = B.recall_rows(runs, narrowed, p60)
        self.assertEqual(rc["per"]["v1"], {"total": 25, "narrowed": 20, "p60": 15})
        self.assertEqual((rc["median_narrowed"], rc["median_p60"]), (20, 15))
        rc = B.recall_rows(runs, None, None)
        self.assertIsNone(rc["per"]["v1"]["narrowed"])
        self.assertIsNone(rc["median_p60"])
        self.assertEqual(B.recall_rows({}, narrowed, p60)["per"], {})

    def test_reach_and_tier(self):
        H = [{"evals": 40, "pack": 90.0, "kick": False}, {"evals": 500, "pack": 100.0, "kick": False},
             {"evals": 2000, "pack": 101.0, "kick": False}]
        runs = {}
        for s in SCEN[:2]:
            runs[(s, POOL, "K", 2000)] = summary(s, "K", 2000, 100.0)
            runs[(s, POOL, "PN", 2000)] = summary(s, "PN", 2000, 101.0, history=H)
        runs[("v3", POOL, "PN", 2000)] = summary("v3", "PN", 2000, 90.0)  # K 없음 → 도달 계산에서 뺀다
        T = {k: r["final"]["total"] for k, r in runs.items()}
        x = {r["method"]: r for r in B.reach_rows(runs, T)}["PN"]
        self.assertEqual((x["reached"], x["reach"], x["n"]), (2, 500, 3))
        self.assertAlmostEqual(x["start_ratio"], 90.0 / 101.0)
        g = {"PN": {2000: [0.0, 0.0, 0.0, 0.0, 0.03, 0.03, 0.0, 0.03]}}
        t = {r["method"]: r for r in B.tier_rows(T_of(g))}["PN"]
        self.assertAlmostEqual(t["random"], 0.03)  # v5 · v6 · v8
        self.assertAlmostEqual(t["other"], 0.0)
        self.assertEqual((t["random_n"], t["other_n"]), (3, 5))

    def test_alt_rows(self):
        runs = {("v1", POOL, "PN", 2000): summary("v1", "PN", 2000, 100.0, alt={"total": 97.0, "shared_nikkes": 21},
                                                  alt20={"total": 90.0, "shared_nikkes": 18}),
                ("v2", POOL, "PN", 2000): summary("v2", "PN", 2000, 100.0, alt={"total": 99.0, "shared_nikkes": 23},
                                                  alt20={"total": 0, "shared_nikkes": 0})}
        r = {x["method"]: x for x in B.alt_rows(runs)}["PN"]
        self.assertAlmostEqual(r["alt"]["ratio"], 0.98)
        self.assertEqual((r["shared"], r["alt20"]["found"]), (22, 1))

    def test_pre_rows(self):
        pre = {"PN": {"budget": 5000, "evals": 5500, "sims": 4000, "seconds": 100.0, "sets": [[]] * 8,
                      "set_totals": [150.0, 160.0], "final": {"total": 162.0},
                      "stages": [{"what": "G+E 60명", "budget": 5000, "evals": 5000, "best": 161.0}]}}
        rows = {r["name"]: r for r in B.pre_rows(pre)}
        self.assertFalse(rows["PB15"]["present"])
        pn = rows["PN"]
        self.assertEqual((pn["per_account"][1], pn["per_account"][10], pn["per_account"][100]), (5500, 550, 55))
        self.assertEqual((pn["set_min"], pn["set_max"], pn["final"]), (150.0, 160.0, 162.0))
        self.assertEqual(pn["stages"][0]["best"], 161.0)


class TestLoad(unittest.TestCase):
    def test_merge_prefers_later_and_warns(self):
        a = summary("v1", "K", 2000, 100.0)
        b = summary("v1", "K", 2000, 100.5)
        k = ("v1", POOL, "K", 2000)
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            out = B.merge_runs([("낮음", {k: a}), ("높음", {k: b})])
        self.assertEqual(out[k]["final"]["total"], 100.5)
        self.assertIn("최종 합이 다르다", buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            B.merge_runs([("낮음", {k: a}), ("높음", {k: summary("v1", "K", 2000, 100.0 + 1e-9)})])
        self.assertEqual(buf.getvalue(), "")

    def test_load_jsonl_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.jsonl"
            rows = [dict(run="v1_P177_K_2000", **summary("v1", "K", 2000, 100.0)),
                    dict(run="v1_P177_K+E_2000", **summary("v1", "K+E", 2000, 101.0)),
                    dict(run="v1_P60_K_2000", **dict(summary("v1", "K", 2000, 99.0), pool=60))]
            f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n{깨짐\n", encoding="utf-8")
            self.assertEqual(sorted(B.load_jsonl(f)), [("v1", POOL, "K", 2000), ("v1", POOL, "K+E", 2000)])
            self.assertEqual(sorted(B.load_jsonl(f, ("K",))), [("v1", POOL, "K", 2000)])
            self.assertEqual(B.load_jsonl(Path(tmp) / "없음.jsonl"), {})
            self.assertEqual(B.load_jsonl(None), {})


class TestMain(unittest.TestCase):
    def _write(self, d, r):
        (d / f"{r['scenario']}_P{r['pool']}_{r['method']}_{r['budget']}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8")

    def _pre(self, d, name, evals, final, **extra):
        (d / f"precompute_{name}.json").write_text(json.dumps(
            {"name": name, "pool": 177, "budget": evals, "evals": evals, "sims": evals - 100, "seconds": 100.0,
             "sets": [[]] * 8, "set_totals": [final - 3, final], "coef": {}, "final": {"total": final, "squads": []},
             "history": [{"evals": 5000, "pack": final - 2, "kick": False}, {"evals": evals, "pack": final, "kick": False}],
             "kicks": [], **extra}, ensure_ascii=False), encoding="utf-8")

    def test_main_writes_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            runs, log, pre = tmp / "runs", tmp / "log", tmp / "pre"
            for d in (runs, log, pre):
                d.mkdir()
            names = [f"n{i}" for i in range(25)]
            sq = [[10.0, names[5 * j:5 * j + 5]] for j in range(5)]
            deltas = {"K": 0.0, "P": -0.04, "PB15": -0.01, "PB30": -0.01, "PN": 0.0, "PM": 0.0}
            exp10 = []
            for i, s in enumerate(SCEN):
                for m, d in deltas.items():
                    for b in B.BUDGETS:
                        r = summary(s, m, b, (180.0 + i) * (1 + d), squads=sq if m == "K" else None)
                        if m in ("K", "P") and b == 2000:
                            exp10.append(dict(run=f"{s}_P177_{m}_{b}", **r))  # 2,000의 K · P는 실험 10 기록에서
                            continue
                        if (s, m, b) == ("v8", "PM", 800):
                            continue  # 빠진 실행 하나
                        self._write(runs, r)
            (log / "val177_summary.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in exp10) + "\n",
                                                      encoding="utf-8")
            self._pre(log, "P", 4454, 150.0)
            (log / "precompute_P177.json").write_text((log / "precompute_P.json").read_text(encoding="utf-8"), encoding="utf-8")
            (log / "precompute_P.json").unlink()
            self._pre(pre, "PB15", 15000, 155.0)
            self._pre(pre, "PB30", 30000, 156.0)
            self._pre(pre, "PN", 5500, 154.0, narrowed=names[:20] + [f"m{i}" for i in range(40)],
                      stages=[{"what": "G+E 60명", "budget": 5000, "evals": 5000, "best": 154.0, "history": [], "kicks": []}])
            # PM은 일부러 없음 → 「—」
            poolj = tmp / "pool.json"
            poolj.write_text(json.dumps({"pool": {n: 1 for n in names[10:] + ["z"]}}), encoding="utf-8")
            out, js = tmp / "results.md", tmp / "summary.json"
            meta = tmp / "meta.json"
            meta.write_text(json.dumps({"evaluator": "테스트 평가기", "workers": 4}), encoding="utf-8")
            rc = B.main(["--runs", str(runs), "--exp10-log", str(log), "--precompute", str(pre), "--pool-json", str(poolj),
                         "--out", str(out), "--json", str(js), "--meta", str(meta)])
            self.assertEqual(rc, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("analyze11.py", text)
            self.assertIn("평가기: 테스트 평가기", text)
            self.assertIn("- workers: 4", text)
            self.assertIn("v8_P177_PM_800", text)  # 빠진 실행
            self.assertIn("판단 불가(7/8)", text)  # PM 800
            self.assertIn("1줄 「랭커 없이 넓은 풀에서도 된다」: PN", text)  # PN: 평가 수 5,500이 가장 작음
            self.assertIn("G+E 60명", text)
            for h in ("## 판단", "## 1.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7.", "## 8.", "## 9."):
                self.assertIn(h, text)
            self.assertLess(text.index("## 판단"), text.index("## 1."))
            a = json.loads(js.read_text(encoding="utf-8"))
            self.assertEqual((a["q1"]["line"], a["q1"]["pick"], a["q2"]["default"]), (1, "PN", "PN"))
            self.assertEqual(a["recall"]["per"]["v1"], {"total": 25, "narrowed": 20, "p60": 15})
            self.assertEqual(a["missing"], ["v8_P177_PM_800"])
            pm = [r for r in a["precompute"] if r["name"] == "PM"][0]
            self.assertFalse(pm["present"])

    def test_main_empty_and_bad_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "broken.json").write_text("{", encoding="utf-8")
            out = tmp / "results.md"
            rc = B.main(["--runs", str(tmp), "--exp10-log", str(tmp / "없음"), "--pool-json", str(tmp / "없음.json"),
                         "--summary", str(tmp / "없음.jsonl"), "--out", str(out)])
            self.assertEqual(rc, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("3줄", text)
            self.assertIn("빠진 실행", text)
            self.assertIn("—", text)

    def test_main_no_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.md"
            self.assertEqual(B.main(["--exp10-log", str(Path(tmp) / "x"), "--pool-json", str(Path(tmp) / "x.json"),
                                     "--out", str(out)]), 0)
            self.assertIn("## 판단", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
