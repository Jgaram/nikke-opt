"""평가기 어댑터 테스트.

가짜 nikke-calc · 가짜 nikke-sim(같은 `--batch` 계약을 흉내 내는 작은 스크립트)으로 돌려서 진짜 계산기 없이 돈다.
`NIKKE_CALC_DIR` · `NIKKE_SIM_BIN`이 있으면 진짜 평가기로 한 번 더 확인한다.
"""

from __future__ import annotations

import gc
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from nikke_opt.evaluator import (BudgetExceeded, Cache, EvalRequest, NikkeCalcEvaluator, NikkeSimEvaluator,
                                 make_evaluator)

# 요청 v2 계약을 흉내 낸다 — 모르는 최상위 키(v1의 "expected" 등)는 그 줄만 오류.
# 총딜 = 이름 길이에 자리마다 다른 가중치(100^자리)를 곱한 합 — 순서가 결과를 바꾸게 한다
FAKE_SIM = textwrap.dedent('''
    import json, sys
    COMMIT = open(".commit").read().strip()
    V = int(open(".schema").read()) if __import__("os").path.exists(".schema") else 2
    KEYS = {"schema_version", "id", "squad", "sim", "boss", "enemy", "operation", "profile", "profile_level", "chars"}
    for n, raw in enumerate(sys.stdin, 1):
        if not raw.strip():
            continue
        req = json.loads(raw)
        squad = req["squad"]
        unknown = sorted(set(req) - KEYS)
        if unknown or "없는 니케" in squad:
            out = {"schema_version": V, "line": n, "error": {"type": "invalid_input", "message": f"없음 {unknown}"}}
        else:
            total = sum(len(name) * 100 ** i for i, name in enumerate(squad))
            out = {"schema_version": V, "line": n, "total_damage": total,
                   "expected": req.get("sim", {}).get("expected", False),
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


# nikke-sim(Rust 포팅) 흉내 — 같은 계약에 evaluator는 빌드 정보(`.version` 파일)를 싣는다.
# 받은 작업 스레드 수·프로필 폴더를 결과에 비춰 어댑터가 넘긴 값을 확인한다
FAKE_RUST = textwrap.dedent('''
    import json, os, sys
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    HERE = os.path.dirname(os.path.abspath(__file__))
    EV = json.load(open(os.path.join(HERE, ".version")))
    KEYS = {"schema_version", "id", "squad", "sim", "boss", "enemy", "operation", "profile", "profile_level", "chars"}
    if sys.argv[1:] != ["--batch"]:
        sys.exit(2)
    with open(os.path.join(HERE, ".calls"), "a") as log:
        log.write("x\\n")
    for n, raw in enumerate(sys.stdin, 1):
        if not raw.strip():
            continue
        req = json.loads(raw)
        squad = req["squad"]
        unknown = sorted(set(req) - KEYS)
        if "죽는 니케" in squad:  # 평가기가 도중에 죽는 경우
            sys.exit(3)
        if "느린 니케" in squad:
            __import__("time").sleep(0.5)
        if unknown or "없는 니케" in squad:
            out = {"schema_version": 2, "line": n, "error": {"type": "invalid_input", "message": f"없음 {unknown}"}}
        else:
            total = sum(len(name) * 100 ** i for i, name in enumerate(squad)) + 7  # 원본과 다른 값
            out = {"schema_version": 2, "line": n, "total_damage": total,
                   "expected": req.get("sim", {}).get("expected", False), "boss": req.get("boss"),
                   "workers": os.environ.get("NIKKE_BATCH_WORKERS"),
                   "profile_dir": os.environ.get("NIKKE_PROFILE_DIR"), "evaluator": EV}
        print(json.dumps(out, ensure_ascii=False), flush=True)
''')

RUST_VERSION = {"repo": "nikke-calc-rs", "commit": "c0ffee" * 6 + "abcd", "dirty": False,
                "port_of": {"repo": "Jgaram/nikke-calc", "commit": "23164e4a88fe46af609cc99b0de38a98313a5f4d"}}


def make_fake_sim(root: Path) -> Path:
    d = root / "rs"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".version").write_text(json.dumps(RUST_VERSION), encoding="utf-8")
    if os.name == "nt":  # Windows는 shebang을 모른다 — .cmd가 같은 폴더의 스크립트를 부른다
        (d / "fake_sim.py").write_text(FAKE_RUST, encoding="utf-8")
        exe = d / "nikke-sim.cmd"
        exe.write_text(f'@"{sys.executable}" "%~dp0fake_sim.py" %*\r\n', encoding="utf-8")
        return exe
    exe = d / "nikke-sim"
    exe.write_text(f"#!{sys.executable}\n" + FAKE_RUST, encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


def sim_calls(exe: Path) -> int:
    calls = exe.parent / ".calls"
    return len(calls.read_text().splitlines()) if calls.exists() else 0


SQUAD = ("리틀 머메이드", "크라운", "라피 : 레드 후드", "미하라", "헬름")


class SharedContract:
    """두 어댑터가 똑같이 지켜야 하는 것. 하위 클래스가 `evaluator()`를 정한다."""

    root: Path

    def evaluator(self, **kw): ...

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
        for opts in ({"duration": 30}, {"sim": {"duration": 30}}):
            with self.assertRaises(ValueError):
                EvalRequest(SQUAD, options=opts).to_line()
        self.assertTrue(self.evaluator(cache=None).evaluate([EvalRequest(SQUAD)])[0].raw["expected"])

    def test_request_is_v2(self):
        line = EvalRequest(SQUAD, boss="솔로 레이드 S40", options={"sim": {"seed": 7}}).to_line()
        self.assertEqual(line["schema_version"], 2)
        # sim은 기본값(기대값 모드 · 게이지 실누적) 위에 얹힌다
        self.assertEqual(line["sim"], {"expected": True, "burst_gauge_mode": "accumulate", "seed": 7})
        self.assertNotIn("expected", line)
        fixed = EvalRequest(SQUAD, options={"sim": {"burst_gauge_mode": "fixed"}}).to_line()
        self.assertEqual(fixed["sim"], {"expected": True, "burst_gauge_mode": "fixed"})  # 옛 조건 재현
        res = self.evaluator(cache=None).evaluate([EvalRequest(SQUAD, options={"chars": {"크라운": {}}})])
        self.assertIsNone(res[0].error)

    def test_inline_profile_is_part_of_the_key(self):
        ev = self.evaluator()
        mid = {"base": "default", "chars": {"크라운": {"skill_levels": "7/7/7"}}}
        low = {"base": "default", "chars": {"크라운": {"skill_levels": "4/4/4"}}}
        ev.evaluate([EvalRequest(SQUAD, options={"profile": mid})])
        ev.evaluate([EvalRequest(SQUAD, options={"profile": low})])
        again = ev.evaluate([EvalRequest(SQUAD, options={"profile": dict(mid)})])
        self.assertEqual(ev.sim_count, 2)
        self.assertTrue(again[0].cached)


class FakeCalcTest(SharedContract, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calc = make_fake_calc(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def evaluator(self, **kw):
        kw.setdefault("cache", Cache(self.root / "cache.sqlite"))
        return NikkeCalcEvaluator(self.calc, **kw)

    def test_contract_version_mismatch_stops(self):
        (self.calc / ".schema").write_text("1")  # 추적 안 하는 파일 — 옛 판 결과를 내는 평가기
        with self.assertRaises(RuntimeError):
            self.evaluator(cache=None).evaluate([EvalRequest(SQUAD)])

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


class FakeSimTest(SharedContract, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.exe = make_fake_sim(self.root)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("NIKKE_PROFILE_DIR", None)

    def tearDown(self):
        self.tmp.cleanup()

    def evaluator(self, **kw):
        kw.setdefault("cache", Cache(self.root / "cache.sqlite"))
        return NikkeSimEvaluator(self.exe, **kw)

    def set_version(self, **change):
        (self.exe.parent / ".version").write_text(json.dumps({**RUST_VERSION, **change}), encoding="utf-8")

    def test_version_comes_from_the_binary_and_probe_is_not_counted(self):
        ev = self.evaluator()
        self.assertEqual(ev.version, RUST_VERSION)
        self.assertEqual(ev.sim_count, 0)
        self.assertEqual(sim_calls(self.exe), 1)

    def test_one_process_reused_across_calls(self):
        ev = self.evaluator(jobs=3, cache=None)
        res = ev.evaluate([EvalRequest(SQUAD[i:] + SQUAD[:i]) for i in range(5)])
        self.assertEqual({r.raw["workers"] for r in res}, {"3"})
        one = ev.evaluate([EvalRequest(SQUAD[::-1])])
        self.assertEqual(one[0].raw["workers"], "3")
        self.assertEqual(sim_calls(self.exe), 1)  # 버전 확인과 두 호출이 프로세스 하나
        self.assertEqual(one[0].raw["line"], 7)  # 버전 확인 1 + 5 + 1
        self.assertEqual(ev.sim_count, 6)

    def test_seeded_call_runs_in_its_own_process(self):
        # 시드 줄은 뒤 줄의 난수 흐름을 잇는다 — 띄워 둔 프로세스에 섞지 않고 그 호출만 따로 돌린다
        ev = self.evaluator(cache=None)
        res = ev.evaluate([EvalRequest(SQUAD, options={"sim": {"seed": 7}}), EvalRequest(SQUAD[::-1])])
        self.assertEqual([r.raw["line"] for r in res], [1, 2])
        self.assertEqual(sim_calls(self.exe), 2)
        after = ev.evaluate([EvalRequest(SQUAD)])  # 띄워 둔 프로세스는 그대로
        self.assertEqual(after[0].raw["line"], 2)
        ev.evaluate([EvalRequest(("없는 니케",) + SQUAD[1:])])  # 오류 줄은 상태를 남기지 않는다
        self.assertEqual(ev.evaluate([EvalRequest(SQUAD[::-1][1:])])[0].raw["line"], 4)
        self.assertEqual(sim_calls(self.exe), 2)
        self.assertEqual(ev.sim_count, 5)

    def test_dead_process_raises_then_restarts(self):
        ev = self.evaluator(cache=None)
        with self.assertRaises(RuntimeError):
            ev.evaluate([EvalRequest(SQUAD), EvalRequest(("죽는 니케",) + SQUAD[1:]), EvalRequest(SQUAD[::-1])])
        self.assertEqual(ev.sim_count, 1)  # 죽기 전에 답한 1회만 센다
        self.assertEqual(ev.pending, 0)
        res = ev.evaluate([EvalRequest(SQUAD[::-1])])
        self.assertIsNotNone(res[0].total_damage)
        self.assertEqual(res[0].raw["line"], 1)  # 새 프로세스는 버전 확인 없이 바로 시작한다
        self.assertEqual(sim_calls(self.exe), 2)

    def test_close_and_context_manager(self):
        with self.evaluator(cache=None) as ev:
            proc = ev._pipe.proc
            fut = ev.submit([EvalRequest(("느린 니케",) + SQUAD[1:])])[0]
        self.assertIsNotNone(proc.poll())  # 끝났다
        self.assertIsNotNone(fut.result(timeout=0).total_damage)  # 처리 중이던 요청은 받고 끝낸다
        self.assertIsNotNone(ev.evaluate([EvalRequest(SQUAD)])[0].total_damage)  # 다시 쓰면 새로 띄운다
        ev.close()
        self.assertEqual(sim_calls(self.exe), 2)

    def test_submit_returns_before_results(self):
        ev = self.evaluator(cache=None)
        t = time.perf_counter()
        slow = ev.submit([EvalRequest(("느린 니케",) + SQUAD[1:])])
        rest = ev.submit([EvalRequest(SQUAD[i:] + SQUAD[:i]) for i in range(5)])
        self.assertLess(time.perf_counter() - t, 0.3)
        self.assertFalse(slow[0].done())
        self.assertEqual(ev.pending, 6)
        got = [f.result(timeout=10).total_damage for f in rest]
        self.assertEqual(got, [r.total_damage for r in ev.evaluate([EvalRequest(SQUAD[i:] + SQUAD[:i])
                                                                    for i in range(5)])])
        self.assertTrue(slow[0].done())
        self.assertEqual((ev.pending, ev.sim_count), (0, 11))

    def test_in_flight_duplicates_and_budget(self):
        ev = self.evaluator(budget=3)
        a = ev.submit([EvalRequest(("느린 니케",) + SQUAD[1:]), EvalRequest(SQUAD)])
        b = ev.submit([EvalRequest(SQUAD)])  # 처리 중인 같은 요청 — 한 번만 돈다
        with self.assertRaises(BudgetExceeded):  # 처리 중 2 + 새 2 > 3
            ev.submit([EvalRequest(SQUAD[::-1]), EvalRequest(SQUAD[1:])])
        c = ev.submit([EvalRequest(SQUAD[::-1])])
        self.assertEqual(b[0].result(timeout=10).total_damage, a[1].result().total_damage)
        self.assertFalse(b[0].result().cached)
        c[0].result(timeout=10)
        self.assertEqual(ev.sim_count, 3)
        self.assertTrue(ev.evaluate([EvalRequest(SQUAD)])[0].cached)

    def test_many_lines_do_not_block(self):
        ev = self.evaluator(cache=None)
        reqs = [EvalRequest((f"니케{i}",) + SQUAD[1:]) for i in range(3000)]
        futs = [f for i in range(0, 3000, 500) for f in ev.submit(reqs[i:i + 500])]
        res = [f.result(timeout=60) for f in futs]
        self.assertEqual([r.raw["line"] for r in res], list(range(2, 3002)))  # 보낸 순서대로 짝지어졌다
        self.assertEqual(ev.sim_count, 3000)

    def test_cache_write_failure_still_returns_results(self):
        ev = self.evaluator()
        def boom(items):
            raise sqlite3.OperationalError("database is locked")
        ev.cache.put_many = boom
        with self.assertWarns(RuntimeWarning):
            res = [f.result(timeout=10) for f in ev.submit([EvalRequest(SQUAD), EvalRequest(SQUAD[::-1])])]
        self.assertTrue(all(r.total_damage for r in res))
        self.assertEqual(ev.pending, 0)

    def test_discarded_evaluator_is_collected(self):
        ev = self.evaluator(cache=None)
        ev.evaluate([EvalRequest(SQUAD)])
        proc = ev._pipe.proc
        del ev
        gc.collect()
        proc.wait(timeout=5)  # 버린 평가기의 프로세스는 끝난다

    def test_exception_in_with_does_not_wait(self):
        t = time.perf_counter()
        with self.assertRaises(KeyError):
            with self.evaluator(cache=None) as ev:
                futs = ev.submit([EvalRequest(("느린 니케", str(i)) + SQUAD[2:]) for i in range(6)])
                raise KeyError
        self.assertLess(time.perf_counter() - t, 2)
        self.assertTrue(all(f.done() for f in futs))

    def test_submit_from_callback(self):
        ev = self.evaluator(cache=None)
        chained: list = []
        first = ev.submit([EvalRequest(SQUAD)])[0]
        first.add_done_callback(lambda f: chained.extend(ev.submit([EvalRequest(SQUAD[::-1])])))
        first.result(timeout=10)
        self.assertIsNotNone(chained[0].result(timeout=10).total_damage)
        ev.close()

    def test_seeded_call_does_not_share_in_flight_results(self):
        ev = self.evaluator(cache=None)
        slow = ev.submit([EvalRequest(("느린 니케",) + SQUAD[1:])])
        ev.evaluate([EvalRequest(("느린 니케",) + SQUAD[1:]), EvalRequest(SQUAD, options={"sim": {"seed": 1}})])
        slow[0].result(timeout=10)
        self.assertEqual(ev.sim_count, 3)

    def test_cache_is_flushed_on_close(self):
        path = self.root / "flush.sqlite"
        with self.evaluator(cache=Cache(path)) as ev:
            ev.evaluate([EvalRequest(SQUAD)])
        self.assertTrue(self.evaluator(cache=Cache(path)).evaluate([EvalRequest(SQUAD)])[0].cached)

    def test_dirty_or_unknown_build_disables_cache(self):
        for change in ({"dirty": True}, {"commit": None, "dirty": None}):
            self.set_version(**change)
            self.assertIsNone(NikkeSimEvaluator(self.exe).cache)

    def test_binary_replaced_mid_run_stops(self):
        # 떠 있는 프로세스는 바뀌기 전 빌드 그대로다. 다시 띄운 프로세스가 다른 빌드면 멈춘다
        ev = self.evaluator(cache=None)
        self.set_version(commit="1" * 40)
        self.assertIsNotNone(ev.evaluate([EvalRequest(SQUAD)])[0].total_damage)
        ev.close()
        with self.assertRaises(RuntimeError):
            ev.evaluate([EvalRequest(SQUAD)])

    def test_cache_does_not_mix_with_python(self):
        cache = Cache(self.root / "cache.sqlite")
        calc = make_fake_calc(self.root)
        py = NikkeCalcEvaluator(calc, cache=cache)
        rs = NikkeSimEvaluator(self.exe, cache=cache)
        a = py.evaluate([EvalRequest(SQUAD)])[0]
        b = rs.evaluate([EvalRequest(SQUAD)])[0]
        self.assertFalse(b.cached)
        self.assertNotEqual(a.total_damage, b.total_damage)
        self.assertTrue(rs.evaluate([EvalRequest(SQUAD)])[0].cached)

    def test_named_profile_needs_a_folder_and_is_keyed_by_content(self):
        req = EvalRequest(SQUAD, options={"profile": "p"})
        with self.assertRaises(ValueError):
            self.evaluator().evaluate([req])
        folder = self.root / "profiles"
        folder.mkdir()
        prof = folder / "p.json"
        prof.write_text('{"chars": {}}', encoding="utf-8")
        ev = self.evaluator(profile_dir=folder)
        self.assertEqual(ev.evaluate([req])[0].raw["profile_dir"], str(folder.resolve()))
        self.assertTrue(ev.evaluate([req])[0].cached)
        prof.write_text('{"chars": {"크라운": {}}}', encoding="utf-8")
        self.assertFalse(ev.evaluate([req])[0].cached)
        self.assertEqual(ev.sim_count, 2)

    def test_relative_boss_file_is_sent_as_absolute(self):
        ev = self.evaluator(cache=None)
        res = ev.evaluate([EvalRequest(SQUAD, boss="bosses/x.json"), EvalRequest(SQUAD, boss="솔로 레이드 S40")])
        self.assertEqual(res[0].raw["boss"], str(Path("bosses/x.json").resolve()))
        self.assertEqual(res[1].raw["boss"], "솔로 레이드 S40")  # 프리셋 이름은 그대로


class MakeEvaluatorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.exe, self.calc = make_fake_sim(root), make_fake_calc(root)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for k in ("NIKKE_SIM_BIN", "NIKKE_CALC_DIR", "NIKKE_PROFILE_DIR"):
            os.environ.pop(k, None)

    def test_auto_prefers_rust(self):
        os.environ["NIKKE_CALC_DIR"] = str(self.calc)
        self.assertIsInstance(make_evaluator(cache=None), NikkeCalcEvaluator)
        os.environ["NIKKE_SIM_BIN"] = str(self.exe)
        self.assertIsInstance(make_evaluator(cache=None), NikkeSimEvaluator)
        self.assertIsInstance(make_evaluator("python", cache=None), NikkeCalcEvaluator)

    def test_nothing_configured(self):
        with self.assertRaises(ValueError):
            make_evaluator()
        with self.assertRaises(ValueError):
            make_evaluator("rust")
        with self.assertRaises(ValueError):
            make_evaluator("java")


class RealContract:
    """진짜 평가기로 확인하는 것. 하위 클래스가 `make()`를 정한다."""

    def make(self, jobs: int): ...

    def test_order_changes_damage(self):
        ev = self.make(jobs=2)
        fwd, rev = ev.evaluate([EvalRequest(SQUAD, boss="솔로 레이드 S40"),
                                EvalRequest(SQUAD[::-1], boss="솔로 레이드 S40")])
        self.assertIsInstance(fwd.total_damage, int)
        self.assertNotEqual(fwd.total_damage, rev.total_damage)
        self.assertEqual(fwd.raw["evaluator"]["commit"], ev.version["commit"])

    def test_inline_profile(self):
        # 빈 인라인 프로필(base=default)은 기본 스펙과 같고, 낮은 육성은 딜을 낮춘다
        ev = self.make(jobs=3)
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


@unittest.skipUnless(os.environ.get("NIKKE_CALC_DIR"), "NIKKE_CALC_DIR 없음 — 진짜 nikke-calc 확인 생략")
class RealCalcTest(RealContract, unittest.TestCase):
    def make(self, jobs):
        return NikkeCalcEvaluator(cache=None, jobs=jobs)


@unittest.skipUnless(os.environ.get("NIKKE_SIM_BIN"), "NIKKE_SIM_BIN 없음 — 진짜 nikke-sim 확인 생략")
class RealSimTest(RealContract, unittest.TestCase):
    def make(self, jobs):
        return NikkeSimEvaluator(cache=None, jobs=jobs)

    def test_version_names_the_port(self):
        v = self.make(jobs=1).version
        self.assertEqual(v["repo"], "nikke-calc-rs")
        self.assertEqual(v["port_of"]["repo"], "Jgaram/nikke-calc")


if __name__ == "__main__":
    unittest.main()
