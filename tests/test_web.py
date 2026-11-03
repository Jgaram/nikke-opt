"""현황판 사이트(web/build.py, 실험 36) — 결과 전에도 만들어지는지(「계산 전」 · 후처리 「계산 중」), analysis.json의 분류를 값 그대로
옮기는지, 세부 분류 새 덱을 바뀐 덱 자리에 놓는지, 후처리 5덱(post.json)을 값 그대로 옮기고 배분 · 큐브 · 선택지를 펼치는지,
화면에 나오는 니케 · 보스 · 속성 그림이 빠짐없이 있는지.

실험 36 결과는 아직 git에 없을 수 있어서, 결과가 있는 경우는 임시 폴더에 지은 실험 36 모양 기록(시뮬 0)으로 시험한다."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
EXP31 = ROOT / "experiments" / "31_recent_seasons"     # 시즌 자료(seasons.json) · 가짜 기록을 만드는 run31 분류 함수


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


B = _load("web_build", WEB / "build.py")
ALLOCS = ("우코4+공4+장탄4", "우코4+공4+크확2+크뎀2", "우코3+공2+차속3+차뎀4")


def _jdump(p: Path, x) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False), encoding="utf-8")


def _post_deck(s: int, i: int, q: list[str], pre: float) -> dict:
    """run36.post_deck 모양 덱 하나(값은 가짜). 선택지: 장전컨 · 카메라 · 버충 담당 · 큐브(3번째 니케)."""
    labels = [f"{q[0]}:reload:C0.1_dry", f"squad:camera:{q[1]}", f"squad:tactic:버충={q[3]}", f"{q[2]}:cube:렐릭 어설트 큐브"]
    return {"id": f"S{s}-{i}", "season": s, "squad": list(q), "win": None, "pre": pre, "ctrl": pre * 1.01, "ctrl_variants": labels[:1],
            "E0": pre * 1.03, "O": pre * 1.04, "alloc": {n: ALLOCS[k % len(ALLOCS)] for k, n in enumerate(q)}, "C2": pre * 1.05,
            "ctrl2_variants": labels, "final": pre * 1.05, "final_variants": labels, "screen": {}, "top": {}, "sims": 1200, "seconds": 60.0}


def _fake_exp(tmp: Path) -> Path:
    """실험 36 모양 결과 폴더(시뮬 0, seasons.json 없음 — 시즌 자료는 늘 실험 31 것).
    S40 = 끝남(분류 + post.json, 후처리 5덱 = 코어 없음 큰 분류 A), S41 = 후처리 덱 1개만(계산 중), 나머지 = 기록 없음."""
    R = _load("run31", EXP31 / "run31.py")
    s = 40
    pool = sorted(R.season(s)["pool"])
    decks = [tuple(pool[i:i + 5]) for i in range(0, 150, 5)]          # 겹치지 않는 덱 30개
    book = {frozenset(d): (30.0 - 0.3 * i, d) for i, d in enumerate(decks)}
    for i in range(0, 25, 5):                                          # 덱 사이 맞교환 이웃(세부 분류 후보)
        a, b = decks[i], decks[i + 1]
        for x, y in ((a[:4] + (b[0],), b[1:] + (a[4],)),):
            book.setdefault(frozenset(x), (30.0 - 0.3 * i - 0.05, x))
            book.setdefault(frozenset(y), (30.0 - 0.3 * (i + 1) - 0.05, y))
    exp = tmp / "exp36"
    d = exp / "run_log" / f"S{s}"
    rk = R.season(s)["rankers"]
    rv = {",".join(q): {"nocore": 20.0, "core30": 25.0, "nocore_members": [[n, 4.0] for n in q], "core30_members": [[n, 5.0] for n in q]}
          for q in rk["top_five"]["squads"]}
    _jdump(d / "rankers.json", {"season": s, "squads": rv})
    parts = {"B_s0": {"evals": 10, "sims": 100, "sims_new": 0, "seconds": 5.0, "copied_from": "experiments/32_primitive_control/r3/S40/A_s0"},
             "B_s1": {"evals": 10, "sims": 23, "seconds": 5.0}, "end": {"skipped": "A", "sims": 0},
             "post": {"total": {}, "sims": 6000, "seconds": 300.0}}
    row = {"season": s, "arm": "A", "status": "done", "parts": parts, "sims_total": 6123, "by_boss": {}}
    mem = {}
    for b in ("nocore", "core30"):
        m = R.R30.class_map(book, limit=5, low=0.0, max_reps=3)
        cl = R.classes_of(m, book)
        row["by_boss"][b] = {"best": m["best"], "comps": m["comps"], "map_exact": m["exact"], "map_seconds": 0.0,
                             "n97": R.R30.count_at(m, m["best"]), "classes": cl, "rankers": R.ranker_metrics(s, b, cl, rv)}
        mem[b] = {",".join(q): {"total": v, "members": [[n, v / 5] for n in q]} for c in cl for v, q in c["decks"]}
    _jdump(d / "members.json", mem)
    for p, x in parts.items():
        _jdump(d / f"part_{p}.json", {**x, "season": s, "part": p, "arm": "A", "evaluator": "nikke-calc-rs 8bc51a2"})
    A = row["by_boss"]["nocore"]["classes"][0]
    pdecks = [_post_deck(s, i, list(q), v) for i, (v, q) in enumerate(A["decks"])]
    _jdump(d / "post.json", {"season": s, "arm": "A", "opt": "final5", "c2": True, "cube": True, "decks": pdecks,
                             "total": {k: sum(x[k] for x in pdecks) for k in ("pre", "ctrl", "E0", "O", "final")}})
    q41 = sorted(R.season(41)["pool"])[:5]
    _jdump(exp / "run_log" / "S41" / "post" / "S41-0.json", _post_deck(41, 0, q41, 10.0))
    _jdump(exp / "analysis.json", {"arm": "A", "summary": {}, "rows": [row],
                                   "procedure": {"arm": "A", "opt": "final5", "c2": True, "cube": True, "post_budget": 400}})
    return exp


class TestWebBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.data = B.build(cls.tmp / "site")            # 기본 결과 폴더(실험 36) — 결과가 없으면 전부 「계산 전」
        cls.exp = _fake_exp(cls.tmp)
        cls.fake = B.build_data(cls.exp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def season(self, s, data=None):
        return next(x for x in (data or self.fake)["seasons"] if x["season"] == s)

    def test_paths(self):
        """결과는 실험 36 폴더, 시즌 자료는 실험 31의 seasons.json(결과 폴더에 seasons.json이 없어도 만들어진다)."""
        self.assertEqual(B.EXP, ROOT / "experiments" / "36_season_refresh")
        self.assertEqual(B.SEASONS, EXP31 / "seasons.json")
        self.assertEqual(B.PARTS, ("B_s0", "B_s1", "end", "core30", "members", "rankers", "post"))
        self.assertFalse((self.exp / "seasons.json").exists())
        self.assertEqual(len(self.fake["seasons"]), 10)
        self.assertEqual(self.data["experiment"]["id"], 36)

    def test_files(self):
        for f in (*B.STATIC, "data.json", ".nojekyll"):
            self.assertTrue((self.tmp / "site" / f).exists(), f)
        on_disk = json.loads((self.tmp / "site" / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["progress"], self.data["progress"])

    def test_every_season_and_boss(self):
        sd = json.loads(B.SEASONS.read_text(encoding="utf-8"))["seasons"]
        self.assertEqual([s["season"] for s in self.data["seasons"]], [int(k) for k in sd])
        self.assertEqual(self.data["progress"]["total"], 10)
        has_analysis = (B.EXP / "analysis.json").exists()
        for s in self.data["seasons"]:
            v = sd[str(s["season"])]
            self.assertEqual(s["pool"], len(v["pool"]))
            self.assertEqual(s["favorite0"], v["favorite0"])
            self.assertEqual(set(s["by_boss"]), set(B.BOSSES))
            self.assertIn(s["post"]["status"], ("done", "running"))
            if not has_analysis and not (B.EXP / "run_log" / f"S{s['season']}" / "post.json").exists():
                self.assertEqual(s["post"]["status"], "running")
            for b, r in s["by_boss"].items():
                self.assertEqual(len(r["ranker_sets"]["top_five"]["decks"]), 5)   # 결과 전이어도 랭커 덱은 있다
                self.assertEqual(len(r["ranker_sets"]["rank1"]["decks"]), 5)
                if not has_analysis:
                    self.assertEqual(r["status"], "pending")
        self.assertEqual(self.data["seasons"][6]["excluded_nikke"], ["라플라스 : 얼티밋 히어로"])     # S39 날짜 경계
        self.assertEqual(self.data["seasons"][6]["excluded_treasure"], ["로산나", "슈가", "팬텀", "플로라"])

    def test_done_season_shape(self):
        d = self.fake
        self.assertEqual(d["progress"]["done"], 1)
        self.assertEqual(d["experiment"]["arm"], "A")
        self.assertEqual(d["experiment"]["procedure"]["opt"], "final5")
        a = json.loads((self.exp / "analysis.json").read_text(encoding="utf-8"))["rows"][0]
        S = self.season(40)
        self.assertEqual(S["status"], "done")
        for b, r in S["by_boss"].items():
            src = a["by_boss"][b]
            self.assertEqual(r["best"], src["best"])
            self.assertEqual([c["name"] for c in r["classes"]], [c["name"] for c in src["classes"]])
            self.assertEqual(r["metrics"], src["rankers"])
            self.assertEqual(r["ranker_sets"]["top_five"]["total"], 100.0 if b == "nocore" else 125.0)
            for c, cs in zip(r["classes"], src["classes"]):
                self.assertEqual(c["total"], cs["total"])
                self.assertEqual([x["order"] for x in c["decks"]], [q for _, q in cs["decks"]])
                for x in c["decks"]:
                    self.assertIsNotNone(x["members"])                    # members.json의 니케별 딜
                self.assertEqual(len(c["subs"]), len(cs["subs"]))
                self.assertEqual(c["more_left"], cs["subs_count"] - len(cs["subs"]))
                rep = [x["order"] for x in c["decks"]]
                for s in c["subs"]:
                    self.assertEqual(sorted(sl["no"] for sl in s["slots"]), sorted(s["changed"]))
                    plan = [list(q) for q in rep]
                    for sl in s["slots"]:
                        plan[sl["no"] - 1] = sl["order"]
                    names = [n for q in plan for n in q]
                    self.assertEqual(len(set(names)), 25)                 # 바꿔 넣은 5덱도 겹치지 않는다
                    for n, x, y in s["moved"]:
                        self.assertIn(n, rep[x - 1])
                        self.assertIn(n, plan[y - 1])
                if c["subs"]:
                    break

    def test_cost_parts(self):
        """비용 표: 실험 36 부분(옮겨 쓴 부분은 새 시뮬 0, 판 A의 끝 탐침은 건너뜀)."""
        S = self.season(40)
        self.assertEqual(set(S["parts"]), {"B_s0", "B_s1", "end", "post"})
        self.assertIn("copied_from", S["parts"]["B_s0"])
        self.assertEqual(S["parts"]["end"]["skipped"], "A")
        self.assertEqual(S["sims_total"], 100 + 23 + 0 + 6000)
        self.assertEqual(S["sims_new"], 0 + 23 + 0 + 6000)
        self.assertEqual(S["evaluators"], ["nikke-calc-rs 8bc51a2"])
        self.assertEqual(self.fake["progress"]["sims_new"], S["sims_new"])

    def test_post_present(self):
        """post.json이 있으면 값(사전 · 단계별 · 최종 · 5덱 합)을 그대로 옮기고, 니케별 배분 · 큐브와 큐브 밖 선택지를 펼친다."""
        src = json.loads((self.exp / "run_log" / "S40" / "post.json").read_text(encoding="utf-8"))
        P = self.season(40)["post"]
        self.assertEqual(P["status"], "done")
        self.assertEqual(P["total"], src["total"])
        self.assertEqual(P["procedure"], {"arm": "A", "opt": "final5", "c2": True, "cube": True})
        self.assertTrue(P["same_as_A"])                                    # 후처리 5덱 = 코어 없음 큰 분류 A
        self.assertEqual(self.fake["progress"]["post"], 1)
        self.assertEqual(len(P["decks"]), 5)
        for x, sx in zip(P["decks"], src["decks"]):
            self.assertEqual(x["order"], sx["squad"])
            for k in ("pre", "ctrl", "E0", "O", "C2", "final"):
                self.assertEqual(x[k], sx[k], k)
            self.assertEqual(x["value"], sx["final"])
            q = sx["squad"]
            self.assertEqual(set(x["gear"]), set(q))
            for n in q:
                self.assertEqual(x["gear"][n]["alloc"], sx["alloc"][n])
            self.assertEqual(x["gear"][q[1]]["alloc_short"], ["우4", "공4", "크확2", "크뎀2"])
            self.assertEqual(x["gear"][q[2]]["cube"], "렐릭 어설트 큐브")
            self.assertEqual(x["gear"][q[2]]["cube_short"], "어설트")
            self.assertEqual(x["gear"][q[0]]["cube"], B.DEFAULT_CUBE)        # 최종 선택에 큐브가 없으면 기본 큐브
            self.assertIsNone(x["gear"][q[0]]["cube_short"])
            self.assertEqual([(c["who"], c["axis"], c["value"], c["target"]) for c in x["choices"]],
                             [(q[0], "reload", "C0.1_dry", None), (None, "camera", "", q[1]), (None, "tactic", "버충", q[3])])
        names = B.site_names(self.fake["seasons"])
        self.assertTrue(all(n in names for x in P["decks"] for n in x["order"]))

    def test_post_missing(self):
        """post.json이 없으면 「계산 중」 — 끝난 덱 수만 세고 덱 값은 옮기지 않는다."""
        p41, p33 = self.season(41)["post"], self.season(33)["post"]
        self.assertEqual(p41, {"status": "running", "decks_done": 1})
        self.assertEqual(p33, {"status": "running", "decks_done": 0})
        self.assertEqual(self.fake["progress"]["post"], 1)

    def test_post_from_analysis_row(self):
        """run_log의 post.json이 없어도 analysis.json 줄의 `post`(run36 analyze가 넣는다)가 있으면 그것을 쓴다."""
        exp = self.tmp / "exp36_row"
        shutil.copytree(self.exp, exp)
        f = exp / "run_log" / "S40" / "post.json"
        post = json.loads(f.read_text(encoding="utf-8"))
        f.unlink()
        an = json.loads((exp / "analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(B.build_data(exp)["seasons"][7]["post"]["status"], "running")
        an["rows"][0]["post"] = post
        _jdump(exp / "analysis.json", an)
        P = B.build_data(exp)["seasons"][7]["post"]
        self.assertEqual(P["status"], "done")
        self.assertEqual(P["total"], post["total"])

    def test_choice_labels(self):
        """선택지 라벨: 니케 이름에 「 : 」가 있어도 스쿼드 이름과 맞춰 자른다."""
        q = ["네온 : 비전 아이", "아니스 : 스타", "민트", "목단", "프리카"]
        self.assertEqual(B.choice("네온 : 비전 아이:reload:A0.3", q),
                         {"who": "네온 : 비전 아이", "axis": "reload", "value": "A0.3", "target": None, "label": "네온 : 비전 아이:reload:A0.3"})
        c = B.choice("squad:camera:아니스 : 스타", q)
        self.assertEqual((c["who"], c["axis"], c["value"], c["target"]), (None, "camera", "", "아니스 : 스타"))
        c = B.choice("squad:tactic:버충=민트", q)
        self.assertEqual((c["who"], c["axis"], c["value"], c["target"]), (None, "tactic", "버충", "민트"))
        c = B.choice("목단:burst:pattern=x", q)
        self.assertEqual((c["who"], c["axis"], c["value"], c["target"]), ("목단", "burst", "pattern=x", None))
        self.assertEqual(B.short_alloc("우코3+공2+크확3+크뎀4"), ["우3", "공2", "크확3", "크뎀4"])
        self.assertEqual(B.short_alloc(None), [])
        self.assertEqual(B.short_cube("택티컬 베어 큐브"), "택티컬 베어")

    def test_every_nikke_has_face(self):
        """화면에 나오는 니케와 10시즌 풀 전원은 얼굴 그림이 있다(니케 이름은 글자로 쓰지 않으므로). 없으면 web/sync_icons.py를 다시 돌린다."""
        names = B.site_names(self.data["seasons"]) | B.pool_names()
        self.assertGreaterEqual(len(names), 174)
        self.assertEqual(self.data["icons"]["missing"], [])
        self.assertEqual(self.fake["icons"]["missing"], [])
        nikke = B.nikke_table(names, B.icon_index())
        for n in names:
            img = nikke.get(n, {}).get("img")
            self.assertTrue(img, n)
            self.assertTrue((self.tmp / "site" / img).exists(), (n, img))
            for e in nikke[n]["el"]:
                self.assertTrue((self.tmp / "site" / "icons" / "elements" / f"{e.lower()}.png").exists(), (n, e))
            self.assertIn(nikke[n].get("b"), ("1", "2", "3", "A"), n)

    def test_boss_and_element_images(self):
        for s in self.data["seasons"]:
            self.assertTrue(s["boss_img"], s["season"])
            self.assertTrue((self.tmp / "site" / s["boss_img"]).exists(), s["boss_img"])
            for e in (s["element"], s["weak"]):
                self.assertTrue((self.tmp / "site" / "icons" / "elements" / f"{e.lower()}.png").exists(), e)
        for f in ("i", "ii", "iii", "i-ii-iii"):
            self.assertTrue((self.tmp / "site" / "icons" / "bursts" / f"{f}.png").exists(), f)

    def test_icon_index_matches_files(self):
        """icons.json이 가리키는 그림은 모두 있고, 가리키지 않는 얼굴 · 보스 그림은 남아 있지 않다."""
        idx = B.icon_index()
        units = {f"{u['id']}.webp" for u in idx["units"].values()}
        bosses = {f"{b}.webp" for b in idx["bosses"].values()}
        self.assertEqual({p.name for p in (B.ICONS / "units").iterdir()}, units)
        self.assertEqual({p.name for p in (B.ICONS / "bosses").iterdir()}, bosses)
        self.assertTrue(idx["source"].get("commit"))

    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_app_js_syntax(self):
        subprocess.run(["node", "--check", str(WEB / "app.js")], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
