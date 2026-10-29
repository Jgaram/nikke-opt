"""평가기 인터페이스와 어댑터 — nikke-calc(Python 원본) · nikke-sim(Rust 포팅).

최적화 코드는 `Evaluator.evaluate()`만 쓴다. 계산기 내부는 import하지 않고 `--batch` 서브프로세스로만 부른다
(입출력 계약: nikke-calc `docs/SIM-JSON.md`, 요청 JSON v2 — `squad` · `sim` · `boss` · `enemy` · `operation` ·
`profile` · `chars`. nikke-calc `167698c`부터). 평가기는 `make_evaluator()`가 고른다 — Rust 실행 파일
(`NIKKE_SIM_BIN`)이 있으면 그것, 없으면 nikke-calc 체크아웃(`NIKKE_CALC_DIR`).

- **평가는 언제나 180초 전체.** 요청에 `sim.duration`을 적으면 거절한다.
- **기본은 기대값 모드**(`sim.expected: true`) — 1회로 결정론적이라 캐시할 수 있다.
- **계약 판을 맞춘다.** 요청에 `schema_version`을 싣고, 판이 다른 결과는 받지 않는다 — 평가기가 계약을 바꾸면
  조용히 틀리지 않고 바로 끊긴다.
- **예산 = 실제로 돌린 시뮬 횟수.** 캐시 적중은 세지 않는다.
- **캐시 키에는 평가기 커밋이 들어간다.** 커밋 안 된 변경이 있는(dirty) 평가기는 결과를 캐시하지 않는다.
- **육성은 요청에 인라인으로 싣는다** — `options={"profile": {"base": "default", "chars": {...}}}`
  (형식: nikke-calc `docs/SIM-JSON.md` §육성). 요청 줄이 곧 육성이라 캐시 키가 내용을 따라간다.
  평가기의 프로필 폴더에 파일을 쓰지 않는다. 프로필을 *이름*으로 주면(내 계정 `me` 등) 그 파일
  내용의 해시를 캐시 키에 넣는다 — 이름은 같은데 내용이 바뀐 프로필을 옛 결과로 읽지 않게.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import weakref
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "evals.sqlite"
SCHEMA_VERSION = 2  # nikke-calc 요청·결과 계약의 판 (docs/SIM-JSON.md §버전)
FORBIDDEN_OPTIONS = frozenset({"squad", "id", "schema_version", "duration"})
RUST_REPO = "nikke-calc-rs"  # nikke-sim 결과의 evaluator.repo
VERSION_PROBE = {"schema_version": SCHEMA_VERSION, "squad": ["크라운"], "sim": {"expected": True}}


@dataclass(frozen=True)
class EvalRequest:
    """스쿼드 하나의 평가 요청. `squad`는 배치 순서 그대로다 (순서가 딜을 바꾼다)."""

    squad: tuple[str, ...]
    boss: str | Mapping[str, Any] | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def to_line(self) -> dict[str, Any]:
        """`--batch` 입력 한 줄(요청 v2). 캐시 키도 이것으로 만든다.

        `options`는 요청의 나머지 칸이다(`sim` · `enemy` · `operation` · `profile` · `chars` …).
        `sim`은 기본값 `{"expected": true}` 위에 얹는다.
        """
        sim = self.options.get("sim") or {}
        bad = sorted(FORBIDDEN_OPTIONS & set(self.options)) + (["sim.duration"] if "duration" in sim else [])
        if bad:
            raise ValueError(f"평가 요청에 쓸 수 없는 옵션: {bad} (평가는 언제나 180초 전체)")
        line: dict[str, Any] = {"schema_version": SCHEMA_VERSION, **self.options,
                                "squad": list(self.squad), "sim": {"expected": True, **sim}}
        if self.boss is not None:
            line["boss"] = self.boss
        return line


@dataclass
class EvalResult:
    total_damage: int | None
    raw: dict[str, Any]
    cached: bool = False

    @property
    def error(self) -> dict[str, Any] | None:
        return self.raw.get("error")


class BudgetExceeded(RuntimeError):
    pass


class Evaluator(Protocol):
    version: dict[str, Any]
    sim_count: int
    cache_hits: int

    def evaluate(self, requests: Sequence[EvalRequest]) -> list[EvalResult]: ...

    def close(self) -> None: ...


class Cache:
    """(평가기 커밋, 요청) → 결과 JSON. 같은 프로세스의 메인 스레드에서만 쓴다."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS evals (key TEXT PRIMARY KEY, result TEXT NOT NULL)")

    @staticmethod
    def key(commit: str, line: Mapping[str, Any]) -> str:
        blob = json.dumps({"commit": commit, "request": line}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT result FROM evals WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_many(self, items: Sequence[tuple[str, dict[str, Any]]]) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO evals VALUES (?, ?)",
            [(k, json.dumps(v, ensure_ascii=False)) for k, v in items],
        )
        self._db.commit()


def _git(calc_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(calc_dir), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _file_digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class _BatchEvaluator:
    """두 어댑터가 함께 쓰는 부분 — 캐시·중복 제거·예산·계약 판 확인. 실행은 하위 클래스의 `_run`."""

    version: dict[str, Any]
    cache: Cache | None
    _cache_id: str  # 캐시 키에 들어가는 평가기 식별자

    def __init__(self, *, budget: int | None):
        self.budget = budget
        self.sim_count = 0
        self.cache_hits = 0

    def close(self) -> None:
        """띄워 둔 평가기 프로세스를 끝낸다. 다시 `evaluate()`하면 새로 띄운다."""

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _setup_cache(self, cache: Cache | None | bool, cacheable: bool) -> None:
        if cache is True:
            cache = Cache(DEFAULT_CACHE) if cacheable else None
        self.cache = cache or None

    def evaluate(self, requests: Sequence[EvalRequest]) -> list[EvalResult]:
        lines = [self._prepare(r.to_line()) for r in requests]
        results: list[EvalResult | None] = [None] * len(lines)
        keys = [Cache.key(self._cache_id, self._key_line(ln)) for ln in lines]

        todo: dict[str, list[int]] = {}  # 같은 요청은 한 번만 돌린다
        for i, key in enumerate(keys):
            hit = self.cache.get(key) if self.cache else None
            if hit is not None:
                results[i] = EvalResult(hit.get("total_damage"), hit, cached=True)
                self.cache_hits += 1
            else:
                todo.setdefault(key, []).append(i)

        if self.budget is not None and self.sim_count + len(todo) > self.budget:
            raise BudgetExceeded(f"예산 {self.budget}회 중 {self.sim_count}회 사용 — {len(todo)}회 더 필요")

        run_keys = list(todo)
        outputs = self._run([lines[todo[k][0]] for k in run_keys])
        self.sim_count += len(run_keys)

        fresh = []
        for key, out in zip(run_keys, outputs):
            self._check(out)
            for i in todo[key]:
                results[i] = EvalResult(out.get("total_damage"), out)
            if "error" not in out:
                fresh.append((key, out))
        if self.cache and fresh:
            self.cache.put_many(fresh)
        return results  # type: ignore[return-value]

    def _check(self, out: dict[str, Any]) -> None:
        if out.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError(f"평가기 계약 판이 다르다: 결과 {out.get('schema_version')} ≠ 어댑터 {SCHEMA_VERSION}"
                               f" ({self.version.get('repo')} {str(self.version.get('commit'))[:7]},"
                               f" nikke-calc docs/SIM-JSON.md §버전)")
        if "error" not in out and not self._same_evaluator(out.get("evaluator") or {}):
            raise RuntimeError(f"평가기가 실행 중에 바뀌었다: {out.get('evaluator')} ≠ {self.version}")

    def _same_evaluator(self, ev: Mapping[str, Any]) -> bool:
        return ev.get("commit") == self.version["commit"]

    def _prepare(self, line: dict[str, Any]) -> dict[str, Any]:
        """평가기로 보낼 줄. 캐시 키도 이 줄로 만든다."""
        return line

    def _profile_file(self, name: str) -> Path | None:
        raise NotImplementedError

    def _key_line(self, line: dict[str, Any]) -> dict[str, Any]:
        """캐시 키용 요청 줄. 프로필 *이름*은 파일 내용 해시로 바꿔 넣는다(인라인은 줄 자체가 내용)."""
        prof = line.get("profile")
        if not isinstance(prof, str) or prof.lstrip().startswith("{"):
            return line
        path = self._profile_file(prof)
        return {**line, "profile": {"file": prof, "sha256": _file_digest(path) if path else None}}

    def _run(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise NotImplementedError


def _run_batch(cmd: list[str], lines: list[dict[str, Any]], *, what: str,
               cwd: Path | None = None, env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    stdin = "".join(json.dumps(ln, ensure_ascii=False) + "\n" for ln in lines)
    proc = subprocess.run(cmd, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, encoding="utf-8")
    rows = [json.loads(s) for s in proc.stdout.splitlines() if s.strip()]
    if proc.returncode != 0 or len(rows) != len(lines):
        raise RuntimeError(f"{what} --batch 실패 (코드 {proc.returncode}, {len(rows)}/{len(lines)}줄)\n"
                           f"{proc.stderr[-2000:]}")
    return rows


class _BatchProcess:
    """계속 떠 있는 `--batch` 프로세스 하나. 요청 줄을 쓰고 같은 수의 응답 줄을 순서대로 읽는다.

    쓰기는 별도 스레드가 한다 — 평가기는 동시에 처리 중인 줄 수를 제한하므로, 다 쓴 뒤에 읽으면 막힌다.
    stderr도 별도 스레드가 비운다(실패 보고용으로 끝부분만 남긴다). 응답의 `line`이 지금까지 보낸 줄 번호와
    다르면 입출력이 어긋난 것이라 멈춘다.
    """

    def __init__(self, cmd: list[str], *, what: str, env: Mapping[str, str] | None = None):
        self.what = what
        self.proc = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.sent = 0
        self._stderr: deque[str] = deque(maxlen=100)
        threading.Thread(target=self._drain, args=(self.proc.stderr, self._stderr), daemon=True).start()

    @staticmethod
    def _drain(stream: Any, tail: deque[str]) -> None:
        try:
            for s in stream:
                tail.append(s)
        except (OSError, ValueError):
            pass
        finally:
            stream.close()  # 프로세스가 끝나면 여기까지 온다

    def alive(self) -> bool:
        return self.proc.poll() is None

    def run(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payload = "".join(json.dumps(ln, ensure_ascii=False) + "\n" for ln in lines)
        failed: list[BaseException] = []

        def write() -> None:
            try:
                self.proc.stdin.write(payload)
                self.proc.stdin.flush()
            except (OSError, ValueError) as e:  # 프로세스가 먼저 끝났다 — 읽는 쪽이 보고한다
                failed.append(e)

        writer = threading.Thread(target=write, daemon=True)
        writer.start()
        rows = []
        for _ in lines:
            s = self.proc.stdout.readline()
            if not s:
                writer.join(timeout=5)
                code = self.proc.wait(timeout=5)
                raise RuntimeError(f"{self.what} --batch 실패 (코드 {code}, {len(rows)}/{len(lines)}줄)\n"
                                   f"{''.join(self._stderr)[-2000:]}")
            row = json.loads(s)
            self.sent += 1
            if row.get("line", self.sent) != self.sent:
                raise RuntimeError(f"{self.what} --batch 응답 줄이 어긋났다: {row.get('line')} ≠ {self.sent}")
            rows.append(row)
        writer.join()
        if failed:
            raise RuntimeError(f"{self.what} --batch 입력 실패: {failed[0]}")
        return rows

    def close(self) -> None:
        _close_process(self.proc)


def _close_process(proc: subprocess.Popen) -> None:
    """입력을 닫아 스스로 끝나게 하고, 안 끝나면 죽인다."""
    if proc.poll() is None:
        try:
            proc.stdin.close()
            proc.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait()
    for stream in (proc.stdin, proc.stdout):
        try:
            stream.close()
        except (OSError, ValueError):
            pass


class NikkeCalcEvaluator(_BatchEvaluator):
    """`Jgaram/nikke-calc`(Python 원본)를 `--batch` 프로세스 `jobs`개로 나눠 돌린다.

    calc_dir: nikke-calc 체크아웃 경로. 없으면 환경변수 `NIKKE_CALC_DIR`.
    budget:   돌릴 수 있는 시뮬 횟수 상한 (None = 무제한). 넘칠 요청은 아예 시작하지 않는다.
    """

    def __init__(self, calc_dir: str | Path | None = None, *, jobs: int | None = None,
                 cache: Cache | None | bool = True, budget: int | None = None):
        super().__init__(budget=budget)
        calc_dir = calc_dir or os.environ.get("NIKKE_CALC_DIR")
        if not calc_dir:
            raise ValueError("nikke-calc 경로가 필요하다 — calc_dir 인자나 NIKKE_CALC_DIR 환경변수")
        self.calc_dir = Path(calc_dir).resolve()
        if not (self.calc_dir / "runner" / "sim.py").is_file():
            raise ValueError(f"nikke-calc 체크아웃이 아니다: {self.calc_dir}")
        self.jobs = jobs or min(os.cpu_count() or 1, 8)

        dirty = bool(_git(self.calc_dir, "status", "--porcelain", "--untracked-files=no"))
        self.version = {"repo": "Jgaram/nikke-calc", "commit": _git(self.calc_dir, "rev-parse", "HEAD"),
                        "dirty": dirty}
        self._cache_id = self.version["commit"]
        self._setup_cache(cache, cacheable=not dirty)

    def _profile_file(self, name: str) -> Path | None:
        return self.calc_dir / "profiles" / f"{name}.json"

    def _run(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not lines:
            return []
        n = min(self.jobs, len(lines))
        chunks = [lines[i::n] for i in range(n)]
        with ThreadPoolExecutor(max_workers=n) as ex:
            parts = list(ex.map(self._run_batch, chunks))
        out: list[dict[str, Any]] = [{}] * len(lines)
        for i, part in enumerate(parts):
            out[i::n] = part
        return out

    def _run_batch(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _run_batch([sys.executable, "-m", "runner.sim", "--batch"], lines,
                          what="nikke-calc", cwd=self.calc_dir)


class NikkeSimEvaluator(_BatchEvaluator):
    """Rust 포팅 `nikke-sim` 실행 파일을 `--batch` 프로세스 하나로 돌린다(작업 스레드 `jobs`개).

    sim_bin:     `nikke-sim` 실행 파일. 없으면 환경변수 `NIKKE_SIM_BIN`. 코드는 이 레포에 두지 않는다.
    profile_dir: 이름으로 준 프로필을 읽을 폴더. 없으면 환경변수 `NIKKE_PROFILE_DIR`. 둘 다 없으면 이름 프로필은
                 거절한다(인라인 육성은 그대로 된다).
    budget:      돌릴 수 있는 시뮬 횟수 상한 (None = 무제한). 넘칠 요청은 아예 시작하지 않는다.

    **프로세스는 한 번 띄워 `evaluate()` 호출 사이에 재사용한다.** 호출마다 띄우면 프로세스 시작과 작업 스레드마다의
    데이터 적재가 매번 들어 작은 호출의 처리량이 떨어진다. `close()`(또는 `with`)로 끝내며, 끝낸 뒤 다시 부르면
    새로 띄운다.

    평가기는 시드(`sim.seed`)가 있는 줄 — 그리고 일부 오류 줄 — 뒤의 시드 없는 줄을 그 줄의 난수 흐름에 이어
    한 스레드에서 차례로 돌린다(nikke-calc-rs `batch_pool.rs`). 이 영향이 다음 호출로 넘어가지 않도록, 그런 줄이
    있었던 호출 뒤에는 프로세스를 새로 띄운다 — 호출 하나의 결과는 호출마다 띄우던 때와 같다.

    버전은 처음 띄울 때 짧은 요청 1회로 결과의 `evaluator`(빌드 때의 nikke-calc-rs 커밋·dirty, 원본 기준 커밋
    `port_of`)를 받아 둔다. 이 1회는 탐색 평가가 아니라 시뮬 횟수에 세지 않는다. 다시 띄운 프로세스가 다른
    빌드면 첫 결과의 `evaluator` 대조에서 멈춘다.
    """

    def __init__(self, sim_bin: str | Path | None = None, *, jobs: int | None = None,
                 cache: Cache | None | bool = True, budget: int | None = None,
                 profile_dir: str | Path | None = None):
        super().__init__(budget=budget)
        sim_bin = sim_bin or os.environ.get("NIKKE_SIM_BIN")
        if not sim_bin:
            raise ValueError("nikke-sim 실행 파일이 필요하다 — sim_bin 인자나 NIKKE_SIM_BIN 환경변수")
        self.sim_bin = Path(sim_bin).resolve()
        if not (self.sim_bin.is_file() and os.access(self.sim_bin, os.X_OK)):
            raise ValueError(f"nikke-sim 실행 파일이 아니다: {self.sim_bin}")
        profile_dir = profile_dir or os.environ.get("NIKKE_PROFILE_DIR")
        self.profile_dir = Path(profile_dir).resolve() if profile_dir else None
        self.jobs = jobs or os.cpu_count() or 1
        self._proc: _BatchProcess | None = None
        self._finalizer: weakref.finalize | None = None

        probe = self._process().run([VERSION_PROBE])[0]
        ev = probe.get("evaluator")
        if probe.get("schema_version") != SCHEMA_VERSION or "error" in probe or not isinstance(ev, dict) \
                or ev.get("repo") != RUST_REPO:
            self.close()
            raise RuntimeError(f"nikke-sim 버전 확인 실패: {probe}")
        self.version = ev
        self._cache_id = f"{RUST_REPO}@{ev.get('commit')}"
        self._setup_cache(cache, cacheable=bool(ev.get("commit")) and ev.get("dirty") is False)

    def _same_evaluator(self, ev: Mapping[str, Any]) -> bool:
        return ev == self.version

    def _env(self, workers: int) -> dict[str, str]:
        env = {**os.environ, "NIKKE_BATCH_WORKERS": str(workers)}
        if self.profile_dir:
            env["NIKKE_PROFILE_DIR"] = str(self.profile_dir)
        return env

    def _process(self) -> _BatchProcess:
        if self._proc is None or not self._proc.alive():
            self.close()
            self._proc = _BatchProcess([str(self.sim_bin), "--batch"], what="nikke-sim", env=self._env(self.jobs))
            self._finalizer = weakref.finalize(self, _close_process, self._proc.proc)
        return self._proc

    def close(self) -> None:
        if self._finalizer is not None:
            self._finalizer()  # _close_process(proc) — 한 번만 돈다
        self._proc = self._finalizer = None

    def _prepare(self, line: dict[str, Any]) -> dict[str, Any]:
        """보스 스크립트 파일의 상대 경로를 절대 경로로 — 어느 폴더에서 돌려도 같은 파일·같은 캐시 키가 되게."""
        boss = line.get("boss")
        if isinstance(boss, str) and boss.endswith(".json") and not Path(boss).is_absolute():
            return {**line, "boss": str(Path(boss).resolve())}
        return line

    def _profile_file(self, name: str) -> Path | None:
        if self.profile_dir is None:
            raise ValueError(f"이름 프로필 {name!r}에는 프로필 폴더가 필요하다 — profile_dir 인자나 NIKKE_PROFILE_DIR"
                             " (인라인 육성은 폴더 없이 된다)")
        return self.profile_dir / f"{name}.json"

    def _run(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not lines:
            return []
        proc = self._process()
        try:
            rows = proc.run(lines)
        except BaseException:
            self.close()  # 입출력이 어긋났을 수 있다 — 다음 호출은 새 프로세스로
            raise
        if any("seed" in (ln.get("sim") or {}) for ln in lines) or any("error" in r for r in rows):
            self.close()  # 난수 흐름을 잇는 줄이 있었다 — 다음 호출에 넘기지 않는다
        return rows


EVALUATORS = ("auto", "rust", "python")


def make_evaluator(kind: str = "auto", *, calc_dir: str | Path | None = None, sim_bin: str | Path | None = None,
                   profile_dir: str | Path | None = None, **common: Any) -> NikkeSimEvaluator | NikkeCalcEvaluator:
    """평가기를 고른다. `auto`: Rust 실행 파일(sim_bin · `NIKKE_SIM_BIN`)이 있으면 Rust, 없으면 nikke-calc.

    common: jobs · cache · budget (두 어댑터 공통).
    """
    if kind not in EVALUATORS:
        raise ValueError(f"평가기 종류는 {EVALUATORS} 중 하나: {kind!r}")
    if kind == "auto":
        kind = "rust" if sim_bin or os.environ.get("NIKKE_SIM_BIN") else "python"
    if kind == "rust":
        return NikkeSimEvaluator(sim_bin, profile_dir=profile_dir, **common)
    return NikkeCalcEvaluator(calc_dir, **common)
