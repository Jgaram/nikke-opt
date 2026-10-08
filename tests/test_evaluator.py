"""평가기 어댑터 테스트.

가짜 nikke-calc(같은 `--batch` 계약을 흉내 내는 작은 스크립트)로 돌려서 진짜 계산기 없이 돈다.
`NIKKE_CALC_DIR`이 있으면 진짜 nikke-calc로 한 번 더 확인한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from nikke_opt.evaluator import BudgetExceeded, Cache, EvalRequest, NikkeCalcEvaluator

# 총딜 = 이름 길이에 자리마다 다른 가중치(100^자리)를 곱한 합 — 순서가 결과를 바꾸게 한다
FAKE_SIM = textwrap.dedent('''
    import json, sys
    COMMIT = open(".commit").read().strip()
    for n, raw in enumerate(sys.stdin, 1):
        if not raw.strip():
            continue
        req = json.loads(raw)
        squad = req["squad"]
        if "없는 니케" in squad:
            out = {"schema_version": 1, "line": n, "error": {"type": "invalid_input", "message": "없음"}}
        else:
            total = sum(len(name) * 100 ** i for i, name in enumerate(squad))
            out = {"schema_version": 1, "line": n, "total_damage": total, "expected": req.get("expected"),
                   "boss": req.get("boss"), "evaluator": {"commit": COMMIT}}
        print(json.dumps(out, ensure_ascii=False), flush=True)
''')


def make_fake_calc(root: Path) -> Path:
    calc = root / "calc"
    (calc / "runner").mkdir(parents=True)
    (calc / "runner" / "__init__.py").write_text("")
    (calc / "runner" / "sim.py").write_text(FAKE_SIM, encoding="utf-8")
    git = ["git", "-C", str(calc), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "fake"], check=True)
    commit = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (calc / ".commit").write_text(commit)  # 추적 안 하는 파일 — dirty로 치지 않는다
    return calc


SQUAD = ("리틀 머메이드", "크라운", "라피 : 레드 후드", "미하라", "헬름")


class FakeCalcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calc = make_fake_calc(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def evaluator(self, **kw):
        kw.setdefault("cache", Cache(self.root / "cache.sqlite"))
        return NikkeCalcEvaluator(self.calc, **kw)

    def test_order_preserved_across_jobs(self):
        reqs = [EvalRequest(SQUAD[i:] + SQUAD[:i]) for i in range(5)]
        one = [r.total_damage for r in self.evaluator(jobs=1, cache=None).evaluate(reqs)]
        many = [r.total_damage for r in self.evaluator(jobs=3, cache=None).evaluate(reqs)]
        self.assertEqual(one, many)
        self.assertEqual(len(set(one)), 5)  # 배치 순서가 다르면 값도 다르다

    def test_cache_hits_do_not_count(self):
        ev = self.evaluator(jobs=2)
        first = ev.evaluate([EvalRequest(SQUAD)])
        again = ev.evaluate([EvalRequest(SQUAD)])
        self.assertEqual(ev.sim_count, 1)
        self.assertFalse(first[0].cached)
        self.assertTrue(again[0].cached)
        self.assertEqual(first[0].total_damage, again[0].total_damage)

    def test_duplicates_run_once(self):
        ev = self.evaluator(cache=None)
        res = ev.evaluate([EvalRequest(SQUAD)] * 3)
        self.assertEqual(ev.sim_count, 1)
        self.assertEqual(len({r.total_damage for r in res}), 1)

    def test_boss_is_part_of_the_key(self):
        ev = self.evaluator()
        ev.evaluate([EvalRequest(SQUAD, boss="솔로 레이드 S40")])
        ev.evaluate([EvalRequest(SQUAD, boss={"def": 50000, "code": "철갑"})])
        self.assertEqual(ev.sim_count, 2)

    def test_budget(self):
        ev = self.evaluator(budget=2)
        ev.evaluate([EvalRequest(SQUAD), EvalRequest(SQUAD[::-1])])
        ev.evaluate([EvalRequest(SQUAD)])  # 캐시 적중은 예산을 안 쓴다
        with self.assertRaises(BudgetExceeded):
            ev.evaluate([EvalRequest(SQUAD[1:] + SQUAD[:1])])
        self.assertEqual(ev.sim_count, 2)

    def test_error_is_returned_not_cached(self):
        ev = self.evaluator()
        bad = EvalRequest(("없는 니케",) + SQUAD[1:])
        res = ev.evaluate([bad, EvalRequest(SQUAD)])
        self.assertEqual(res[0].error["type"], "invalid_input")
        self.assertIsNone(res[0].total_damage)
        self.assertIsNotNone(res[1].total_damage)
        ev.evaluate([bad])
        self.assertEqual(ev.sim_count, 3)

    def test_always_full_180s_and_expected_by_default(self):
        with self.assertRaises(ValueError):
            EvalRequest(SQUAD, options={"duration": 30}).to_line()
        self.assertTrue(self.evaluator(cache=None).evaluate([EvalRequest(SQUAD)])[0].raw["expected"])

    def test_inline_profile_is_part_of_the_key(self):
        ev = self.evaluator()
        mid = {"base": "default", "chars": {"크라운": {"skill_levels": "7/7/7"}}}
        low = {"base": "default", "chars": {"크라운": {"skill_levels": "4/4/4"}}}
        ev.evaluate([EvalRequest(SQUAD, options={"profile": mid})])
        ev.evaluate([EvalRequest(SQUAD, options={"profile": low})])
        again = ev.evaluate([EvalRequest(SQUAD, options={"profile": dict(mid)})])
        self.assertEqual(ev.sim_count, 2)
        self.assertTrue(again[0].cached)

    def test_named_profile_is_keyed_by_content(self):
        # 이름으로 준 프로필은 파일 내용이 바뀌면 다시 돈다 (profiles/는 추적 밖이라 dirty가 아니다)
        prof = self.calc / "profiles" / "p.json"
        prof.parent.mkdir()
        prof.write_text('{"chars": {}}', encoding="utf-8")
        ev = self.evaluator()
        req = EvalRequest(SQUAD, options={"profile": "p"})
        ev.evaluate([req])
        self.assertTrue(ev.evaluate([req])[0].cached)
        prof.write_text('{"chars": {"크라운": {}}}', encoding="utf-8")
        self.assertFalse(ev.evaluate([req])[0].cached)
        self.assertEqual(ev.sim_count, 2)

    def test_dirty_checkout_disables_cache(self):
        (self.calc / "runner" / "sim.py").write_text(FAKE_SIM + "\n# 수정\n", encoding="utf-8")
        ev = NikkeCalcEvaluator(self.calc)
        self.assertTrue(ev.version["dirty"])
        self.assertIsNone(ev.cache)


@unittest.skipUnless(os.environ.get("NIKKE_CALC_DIR"), "NIKKE_CALC_DIR 없음 — 진짜 nikke-calc 확인 생략")
class RealCalcTest(unittest.TestCase):
    def test_order_changes_damage(self):
        ev = NikkeCalcEvaluator(cache=None, jobs=2)
        fwd, rev = ev.evaluate([EvalRequest(SQUAD, boss="솔로 레이드 S40"),
                                EvalRequest(SQUAD[::-1], boss="솔로 레이드 S40")])
        self.assertIsInstance(fwd.total_damage, int)
        self.assertNotEqual(fwd.total_damage, rev.total_damage)
        self.assertEqual(fwd.raw["evaluator"]["commit"], ev.version["commit"])

    def test_inline_profile(self):
        # 빈 인라인 프로필(base=default)은 기본 스펙과 같고, 낮은 육성은 딜을 낮춘다
        ev = NikkeCalcEvaluator(cache=None, jobs=3)
        duo = SQUAD[1:3]
        plain, empty, low = ev.evaluate([
            EvalRequest(duo),
            EvalRequest(duo, options={"profile": {"base": "default", "chars": {}}}),
            EvalRequest(duo, options={"profile": {"base": "default", "chars": {
                "크라운": {"skill_levels": "4/4/4", "overload": {"우월코드": 0, "공격력": 0}}}}}),
        ])
        self.assertEqual(empty.total_damage, plain.total_damage)
        self.assertLess(low.total_damage, plain.total_damage)
        self.assertEqual(empty.raw["spec"]["profile"]["source"], "inline")


if __name__ == "__main__":
    unittest.main()
