"""현황판 사이트(web/build.py, 실험 31) — 결과 전에도 만들어지는지(「계산 전」), analysis.json의 분류를 값 그대로 옮기는지,
세부 분류 새 덱을 바뀐 덱 자리에 놓는지, 화면에 나오는 니케 · 보스 · 속성 그림이 빠짐없이 있는지."""

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
EXP = ROOT / "experiments" / "31_recent_seasons"


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


B = _load("web_build", WEB / "build.py")


def _fake_exp(tmp: Path) -> Path:
    """S40 하나만 끝난 실험 폴더: 시즌 풀 니케로 만든 가짜 기록 → run31 분류 · 랭커 지표 → analysis.json(시뮬 0)."""
    R = _load("run31", EXP / "run31.py")
    s = 40
    pool = sorted(R.season(s)["pool"])
    decks = [tuple(pool[i:i + 5]) for i in range(0, 150, 5)]          # 겹치지 않는 덱 30개
    book = {frozenset(d): (30.0 - 0.3 * i, d) for i, d in enumerate(decks)}
    for i in range(0, 25, 5):                                          # 덱 사이 맞교환 이웃(세부 분류 후보)
        a, b = decks[i], decks[i + 1]
        for x, y in ((a[:4] + (b[0],), b[1:] + (a[4],)),):
            book.setdefault(frozenset(x), (30.0 - 0.3 * i - 0.05, x))
            book.setdefault(frozenset(y), (30.0 - 0.3 * (i + 1) - 0.05, y))
    exp = tmp / "exp31"
    d = exp / "run_log" / f"S{s}"
    d.mkdir(parents=True)
    rk = R.season(s)["rankers"]
    rv = {",".join(q): {"nocore": 20.0, "core30": 25.0, "nocore_members": [[n, 4.0] for n in q], "core30_members": [[n, 5.0] for n in q]}
          for q in rk["top_five"]["squads"]}
    (d / "rankers.json").write_text(json.dumps({"season": s, "squads": rv}, ensure_ascii=False), encoding="utf-8")
    row = {"season": s, "arm": "B", "status": "done", "parts": {}, "sims_total": 123, "by_boss": {}}
    mem = {}
    for b in ("nocore", "core30"):
        m = R.R30.class_map(book, limit=5, low=0.0, max_reps=3)
        cl = R.classes_of(m, book)
        row["by_boss"][b] = {"best": m["best"], "comps": m["comps"], "map_exact": m["exact"], "map_seconds": 0.0,
                             "n97": R.R30.count_at(m, m["best"]), "classes": cl, "rankers": R.ranker_metrics(s, b, cl, rv)}
        mem[b] = {",".join(q): {"total": v, "members": [[n, v / 5] for n in q]} for c in cl for v, q in c["decks"]}
    (d / "members.json").write_text(json.dumps(mem, ensure_ascii=False), encoding="utf-8")
    (d / "part_B_s0.json").write_text(json.dumps({"evals": 10, "sims": 100, "seconds": 5.0}), encoding="utf-8")
    (d / "part_B_s1.json").write_text(json.dumps({"evals": 10, "sims": 23, "seconds": 5.0}), encoding="utf-8")
    (exp / "analysis.json").write_text(json.dumps({"arm": "B", "summary": {}, "rows": [row]}, ensure_ascii=False), encoding="utf-8")
    return exp


class TestWebBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.data = B.build(cls.tmp / "site")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_files(self):
        for f in (*B.STATIC, "data.json", ".nojekyll"):
            self.assertTrue((self.tmp / "site" / f).exists(), f)
        on_disk = json.loads((self.tmp / "site" / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["progress"], self.data["progress"])

    def test_every_season_and_boss(self):
        sd = json.loads((EXP / "seasons.json").read_text(encoding="utf-8"))["seasons"]
        self.assertEqual([s["season"] for s in self.data["seasons"]], [int(k) for k in sd])
        self.assertEqual(self.data["progress"]["total"], 10)
        has_analysis = (EXP / "analysis.json").exists()
        for s in self.data["seasons"]:
            v = sd[str(s["season"])]
            self.assertEqual(s["pool"], len(v["pool"]))
            self.assertEqual(s["favorite0"], v["favorite0"])
            self.assertEqual(set(s["by_boss"]), set(B.BOSSES))
            for b, r in s["by_boss"].items():
                self.assertEqual(len(r["ranker_sets"]["top_five"]["decks"]), 5)   # 결과 전이어도 랭커 덱은 있다
                self.assertEqual(len(r["ranker_sets"]["rank1"]["decks"]), 5)
                if not has_analysis:
                    self.assertEqual(r["status"], "pending")
        self.assertEqual(self.data["seasons"][6]["excluded_nikke"], ["라플라스 : 얼티밋 히어로"])     # S39 날짜 경계
        self.assertEqual(self.data["seasons"][6]["excluded_treasure"], ["로산나", "슈가", "팬텀", "플로라"])

    def test_done_season_shape(self):
        exp = _fake_exp(self.tmp)
        d = B.build_data(exp)
        self.assertEqual(d["progress"]["done"], 1)
        self.assertEqual(d["experiment"]["arm"], "B")
        a = json.loads((exp / "analysis.json").read_text(encoding="utf-8"))["rows"][0]
        S = next(x for x in d["seasons"] if x["season"] == 40)
        self.assertEqual(S["status"], "done")
        self.assertEqual(S["sims_total"], 123)
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

    def test_every_nikke_has_face(self):
        """화면에 나오는 니케와 10시즌 풀 전원은 얼굴 그림이 있다(니케 이름은 글자로 쓰지 않으므로). 없으면 web/sync_icons.py를 다시 돌린다."""
        names = B.site_names(self.data["seasons"]) | B.pool_names()
        self.assertGreaterEqual(len(names), 174)
        self.assertEqual(self.data["icons"]["missing"], [])
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
