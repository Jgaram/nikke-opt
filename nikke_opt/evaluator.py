"""평가기 인터페이스와 어댑터 — nikke-calc(Python 원본) · nikke-sim(Rust 포팅).

최적화 코드는 `Evaluator.evaluate()`·`submit()`만 쓴다. 계산기 내부는 import하지 않고 `--batch` 서브프로세스로만 부른다
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
import queue
import threading
import time
import warnings
import weakref
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

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

    def submit(self, requests: Sequence[EvalRequest]) -> list[Future[EvalResult]]: ...

    def close(self) -> None: ...


class Cache:
    """(평가기 커밋, 요청) → 결과 JSON. 여러 스레드에서 써도 된다(연결 하나를 잠금으로 나눠 쓴다).

    쓰기는 모아서 commit한다(`COMMIT_ROWS`줄 또는 `COMMIT_SECONDS`초마다, `flush()`·평가기 `close()`·종료 때).
    같은 연결은 commit 전 줄도 읽으므로 캐시 적중에는 차이가 없다. 비정상 종료 때는 마지막 몇 줄을 잃을 수 있다.
    """

    COMMIT_ROWS = 64
    COMMIT_SECONDS = 2.0

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._lock = threading.Lock()
        self._dirty = 0
        self._last_commit = time.monotonic()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("CREATE TABLE IF NOT EXISTS evals (key TEXT PRIMARY KEY, result TEXT NOT NULL)")
            self._db.commit()
        weakref.finalize(self, _commit_quietly, self._db, self._lock)

    @staticmethod
    def key(commit: str, line: Mapping[str, Any]) -> str:
        blob = json.dumps({"commit": commit, "request": line}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT result FROM evals WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_many(self, items: Sequence[tuple[str, dict[str, Any]]]) -> None:
        rows = [(k, json.dumps(v, ensure_ascii=False)) for k, v in items]
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO evals VALUES (?, ?)", rows)
            self._dirty += len(rows)
            if self._dirty >= self.COMMIT_ROWS or time.monotonic() - self._last_commit >= self.COMMIT_SECONDS:
                self._commit()

    def flush(self) -> None:
        with self._lock:
            if self._dirty:
                self._commit()

    def _commit(self) -> None:
        self._db.commit()
        self._dirty = 0
        self._last_commit = time.monotonic()


def _commit_quietly(db: sqlite3.Connection, lock: threading.Lock) -> None:
    try:
        with lock:
            db.commit()
            db.close()
    except sqlite3.Error:
        pass


def _git(calc_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(calc_dir), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _file_digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class _BatchEvaluator:
    """두 어댑터가 함께 쓰는 부분 — 캐시·중복 제거·예산·계약 판 확인. 실행은 하위 클래스의 `_start`.

    `submit()`은 요청마다 Future를 바로 돌려준다. 결과를 기다리지 않고 다음 요청을 넣을 수 있어, 평가기가
    비동기로 받는 경우(Rust) 작업 스레드를 쉬지 않게 채울 수 있다. `evaluate()`는 `submit()` 뒤 전부 기다린다.

    - 캐시 적중은 바로 끝난 Future다. 같은 요청이 이미 처리 중이면(이번 호출이든 앞 호출이든) 그 결과를 함께 받는다.
    - 예산은 끝난 시뮬 + 처리 중인 시뮬로 확인한다. `sim_count`는 응답이 온 시뮬만 센다.
    - Future 콜백(`add_done_callback`)은 평가기의 읽기 스레드에서 돌 수 있다 — 콜백에서 오래 막지 않고,
      `evaluate()`·`close()`를 부르지 않는다(`submit()`은 된다).
    - 시드 줄이 있는 호출은 다른 호출과 처리 중 결과를 나누지 않는다(그 호출 안 난수 흐름에 기댄다).
    """

    version: dict[str, Any]
    cache: Cache | None
    _cache_id: str  # 캐시 키에 들어가는 평가기 식별자

    def __init__(self, *, budget: int | None):
        self.budget = budget
        self.sim_count = 0
        self.cache_hits = 0
        self._lock = threading.Lock()
        # 처리 중 키 → (캐시 키, 그 결과를 기다리는 Future). 처리 중 키는 보통 캐시 키와 같다
        self._inflight: dict[str, tuple[str, list[Future[EvalResult]]]] = {}
        self._calls = 0

    @property
    def pending(self) -> int:
        """처리 중인(응답을 기다리는) 시뮬 수."""
        return len(self._inflight)

    def close(self) -> None:
        """띄워 둔 평가기 프로세스를 끝낸다(처리 중인 요청은 끝까지 받는다). 다시 쓰면 새로 띄운다.

        Future 콜백 안에서는 `close()`·`evaluate()`를 부르지 않는다(읽기 스레드가 자기를 기다리게 된다).
        """
        if self.cache:
            self.cache.flush()

    def _abort(self) -> None:
        """처리 중인 요청을 기다리지 않고 끝낸다 — 예외로 `with`를 빠져나갈 때."""
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type: Any, *exc: Any) -> None:
        if exc_type is None:
            self.close()
        else:
            self._abort()

    def _setup_cache(self, cache: Cache | None | bool, cacheable: bool) -> None:
        if cache is True:
            cache = Cache(DEFAULT_CACHE) if cacheable else None
        self.cache = cache or None

    def evaluate(self, requests: Sequence[EvalRequest]) -> list[EvalResult]:
        return [f.result() for f in self.submit(requests)]

    def submit(self, requests: Sequence[EvalRequest]) -> list[Future[EvalResult]]:
        lines = [self._prepare(r.to_line()) for r in requests]
        keys = [Cache.key(self._cache_id, self._key_line(ln)) for ln in lines]
        futures: list[Future[EvalResult]] = [Future() for _ in lines]
        # 시드 줄이 있는 호출은 줄 결과가 호출 안 난수 흐름에 기대므로 다른 호출과 처리 중 결과를 나누지 않는다
        private = any((ln.get("sim") or {}).get("seed") is not None for ln in lines)
        new: dict[str, tuple[str, dict[str, Any]]] = {}  # 처리 중 키 → (캐시 키, 줄). 같은 요청은 한 번만
        waiters: dict[str, tuple[str, list[Future[EvalResult]]]] = {}
        registered = False
        try:
            with self._lock:
                self._calls += 1
                for fut, key, line in zip(futures, keys, lines):
                    ikey = f"{key}#{self._calls}" if private else key
                    if ikey in self._inflight:
                        self._inflight[ikey][1].append(fut)
                        continue
                    if ikey in new:
                        waiters[ikey][1].append(fut)
                        continue
                    hit = self.cache.get(key) if self.cache else None
                    if hit is not None:
                        fut.set_result(EvalResult(hit.get("total_damage"), hit, cached=True))
                        self.cache_hits += 1
                    else:
                        new[ikey] = (key, line)
                        waiters[ikey] = (key, [fut])
                if self.budget is not None and self.sim_count + len(self._inflight) + len(new) > self.budget:
                    for ikey in new:  # 처리 중 요청에 붙인 Future는 그대로 끝난다
                        waiters.pop(ikey)
                    raise BudgetExceeded(f"예산 {self.budget}회 중 {self.sim_count}회 사용·"
                                         f"{len(self._inflight)}회 처리 중 — {len(new)}회 더 필요")
                registered = True
                self._inflight.update(waiters)
            if new:
                self._start([(ikey, line) for ikey, (_, line) in new.items()])
        except BaseException as e:
            if registered:  # 보내지 못한(또는 보냈는지 모르는) 요청 — 기다리던 Future를 실패로 끝낸다
                for ikey in new:
                    self._finish(ikey, e)
            raise
        return futures

    def _finish(self, ikey: str, out: dict[str, Any] | BaseException) -> None:
        """요청 하나의 응답(또는 실패)을 기다리던 Future에 넘긴다. 어느 스레드에서 불려도 되고 예외를 내지 않는다."""
        failed = isinstance(out, BaseException)
        with self._lock:
            if not failed:
                self.sim_count += 1  # 실패로 먼저 끝낸 요청의 늦은 응답도 돈 시뮬이다
            entry = self._inflight.get(ikey)
            if entry is None:
                return
            key, waiters = entry
            try:
                if not failed:
                    try:
                        self._check(out)
                    except RuntimeError as e:
                        out, failed = e, True
                    else:
                        if self.cache and "error" not in out:
                            try:
                                self.cache.put_many([(key, out)])
                            except Exception as e:  # 캐시 실패는 결과를 막지 않는다
                                warnings.warn(f"평가 결과를 캐시에 쓰지 못했다: {e!r}", RuntimeWarning, stacklevel=2)
            finally:
                del self._inflight[ikey]
        for fut in waiters:
            if failed:
                fut.set_exception(out)
            else:
                fut.set_result(EvalResult(out.get("total_damage"), out))

    def _start(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        """새 요청을 평가기에 넘기고, 응답마다 `_finish(키, 응답)`을 부르게 한다. 기본은 `_run`으로 동기 실행."""
        try:
            outputs = self._run([line for _, line in items])
        except BaseException as e:
            for ikey, _ in items:
                self._finish(ikey, e)
            raise
        for (ikey, _), out in zip(items, outputs):
            self._finish(ikey, out)

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


Done = Callable[[Any, "dict[str, Any] | BaseException"], None]


class _BatchPipe:
    """계속 떠 있는 `--batch` 프로세스 하나. 줄을 보내 두면 응답이 오는 대로 `done(태그, 응답)`을 부른다.

    평가기는 응답을 요청 순서대로 쓰므로 응답 i번은 보낸 줄 i번의 것이다(응답의 `line`으로 확인한다). 쓰기·읽기·
    stderr 비우기는 각각 스레드가 한다 — 보내는 쪽은 막히지 않고, 평가기가 동시에 받는 줄 수를 제한해도 읽기가
    계속 비워 주므로 서로 기다리다 멈추지 않는다. 프로세스가 죽거나 응답이 어긋나면 남은 줄은 모두 예외로 끝나고
    이 파이프는 다시 쓰지 않는다.
    """

    def __init__(self, cmd: list[str], *, what: str, env: Mapping[str, str] | None = None):
        self.what = what
        self.proc = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.dead: BaseException | None = None
        self._closing = False
        self._lock = threading.Lock()
        self._slots: deque[tuple[Any, Done]] = deque()  # 보냈고 응답을 기다리는 줄
        self._queue: queue.SimpleQueue[str | None] = queue.SimpleQueue()
        self._answered = 0
        self._stderr: deque[str] = deque(maxlen=100)
        self._threads = [threading.Thread(target=t, daemon=True, name=f"{what}-{t.__name__}")
                         for t in (self._write, self._read, self._drain)]
        for t in self._threads:
            t.start()

    def send(self, items: Sequence[tuple[Any, dict[str, Any]]], done: Done) -> None:
        payload = "".join(json.dumps(line, ensure_ascii=False) + "\n" for _, line in items)
        with self._lock:
            if self.dead is not None or self._closing:
                raise RuntimeError(f"{self.what} --batch 프로세스가 이미 끝났거나 끝나는 중이다") from self.dead
            # 보낼 것을 먼저 넣는다 — 그 사이 끊기면 「보내지 않은 줄의 응답」으로 잡혀 파이프가 멈춘다(짝이 밀리지 않는다)
            self._queue.put(payload)
            self._slots.extend((tag, done) for tag, _ in items)

    def run(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """보내고 응답을 모두 기다린다."""
        futures = [Future() for _ in lines]

        def done(i: int, out: dict[str, Any] | BaseException) -> None:
            futures[i].set_exception(out) if isinstance(out, BaseException) else futures[i].set_result(out)

        self.send(list(enumerate(lines)), done)
        return [f.result() for f in futures]

    def alive(self) -> bool:
        return self.dead is None and not self._closing and self.proc.poll() is None

    def close(self, *, wait: bool = True) -> None:
        """입력을 닫는다. 평가기는 받은 줄을 다 답하고 끝난다 — `wait`면 그때까지 기다린다(안 끝나면 죽인다).
        `wait=False`면 바로 죽이고 처리 중인 줄은 실패로 끝난다. 읽기 스레드 안에서 부르면 기다리지 않는다."""
        with self._lock:
            self._closing = True
            self._queue.put(None)
        if not wait:
            self.proc.kill()
        if threading.current_thread() is self._threads[1]:
            return
        self._threads[1].join(timeout=600 if wait else 5)
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self._threads[1].join(timeout=5)

    def abort(self) -> None:
        self.close(wait=False)

    def _write(self) -> None:
        while (payload := self._queue.get()) is not None:
            try:
                self.proc.stdin.write(payload)
                self.proc.stdin.flush()
            except (OSError, ValueError):
                break  # 프로세스가 먼저 끝났다 — 읽기 스레드가 보고한다
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass

    def _read(self) -> None:
        failure: BaseException | None = None
        try:
            for s in self.proc.stdout:
                if not s.strip():
                    continue
                row = json.loads(s)
                with self._lock:
                    if not self._slots:
                        raise RuntimeError(f"{self.what} --batch: 보내지 않은 줄의 응답이 왔다: {s[:200]}")
                    tag, done = self._slots.popleft()
                    self._answered += 1
                    if row.get("line", self._answered) != self._answered:
                        raise RuntimeError(f"{self.what} --batch 응답 줄이 어긋났다:"
                                           f" {row.get('line')} ≠ {self._answered}")
                done(tag, row)
                del tag, done  # 다음 줄을 기다리는 동안 평가기를 붙잡지 않는다(버린 평가기가 수거되게)
        except BaseException as e:  # 응답을 믿을 수 없다 — 프로세스를 끝내고 남은 줄을 실패로
            failure = e
            self.proc.kill()
        code = self.proc.wait()
        with self._lock:
            pending = list(self._slots)
            self._slots.clear()
            if failure is None and pending:
                failure = RuntimeError(f"{self.what} --batch 실패 (코드 {code}, 응답 못 받은 줄 {len(pending)}개)\n"
                                       f"{''.join(self._stderr)[-2000:]}")
            self.dead = failure or RuntimeError(f"{self.what} --batch 끝남 (코드 {code})")
        for tag, done in pending:
            done(tag, failure)
        try:
            self.proc.stdout.close()
        except (OSError, ValueError):
            pass

    def _drain(self) -> None:
        try:
            for s in self.proc.stderr:
                self._stderr.append(s)
        except (OSError, ValueError):
            pass
        finally:
            self.proc.stderr.close()


class NikkeCalcEvaluator(_BatchEvaluator):
    """`Jgaram/nikke-calc`(Python 원본)를 `--batch` 프로세스 `jobs`개로 나눠 돌린다.

    calc_dir: nikke-calc 체크아웃 경로. 없으면 환경변수 `NIKKE_CALC_DIR`.
    budget:   돌릴 수 있는 시뮬 횟수 상한 (None = 무제한). 넘칠 요청은 아예 시작하지 않는다.

    `submit()`은 그 자리에서 다 돌리고 끝난 Future를 돌려준다(비동기 아님).
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

    **프로세스는 한 번 띄워 계속 쓰고, `submit()`은 줄을 보내 두기만 하고 바로 돌아온다.** 호출마다 띄우면 시작과
    작업 스레드마다의 데이터 적재가 매번 들고, 호출마다 다 끝나기를 기다리면 마지막 줄들을 도는 동안 다른 작업
    스레드가 논다. 탐색은 결과를 기다리지 않고 다음 후보를 넣어 작업 스레드를 채울 수 있다. `close()`(또는
    `with`)는 처리 중인 줄을 다 받은 뒤 끝내며, 끝낸 뒤 다시 쓰면 새로 띄운다. 프로세스가 죽으면 처리 중이던
    요청은 예외로 끝나고 다음 요청에서 새로 띄운다.

    평가기는 시드(`sim.seed`)가 있는 줄 뒤의 시드 없는 줄을 그 줄의 난수 흐름에 이어 한 스레드에서 차례로
    돌린다(nikke-calc-rs `batch_pool.rs`). 그래서 **시드가 있는 요청이 들어간 호출은 띄워 둔 프로세스에 섞지 않고**
    그 호출만의 프로세스에서 동기로 돌린다 — 호출 하나의 결과는 호출마다 띄우던 때와 같다. 시드 없는 줄만
    받는 프로세스에는 줄 사이 상태가 생기지 않는다(예외: 읽기 단계에서 지원 밖인 줄 — 포팅이 예약한 문자
    U+10F000..U+10F7FF를 담은 줄 — 은 시드가 있는 것으로 친다).

    버전은 처음 띄울 때 짧은 요청 1회로 결과의 `evaluator`(빌드 때의 nikke-calc-rs 커밋·dirty, 원본 기준 커밋
    `port_of`)를 받아 둔다. 이 1회는 탐색 평가가 아니라 시뮬 횟수에 세지 않는다. 다시 띄운 프로세스가 다른
    빌드면 결과마다 하는 `evaluator` 대조에서 멈춘다.
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
        self._pipe: _BatchPipe | None = None
        self._pipe_lock = threading.Lock()
        self._finalizer: weakref.finalize | None = None

        self.cache = None
        probe = self._live_pipe().run([VERSION_PROBE])[0]
        ev = probe.get("evaluator")
        if probe.get("schema_version") != SCHEMA_VERSION or "error" in probe or not isinstance(ev, dict) \
                or ev.get("repo") != RUST_REPO:
            self._abort()
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

    def _live_pipe(self) -> _BatchPipe:
        old = None
        with self._pipe_lock:
            if self._pipe is None or not self._pipe.alive():
                old = self._detach_pipe()
                self._pipe = _BatchPipe([str(self.sim_bin), "--batch"], what="nikke-sim", env=self._env(self.jobs))
                # 닫지 않고 버리거나 종료하면 기다리지 않고 끝낸다
                self._finalizer = weakref.finalize(self, self._pipe.abort)
            pipe = self._pipe
        if old is not None:
            old.close()
        return pipe

    def _detach_pipe(self) -> _BatchPipe | None:
        """`_pipe_lock` 안에서 부른다. 끝내는 일은 잠금 밖에서 한다(읽기 스레드를 기다리는 동안 막지 않게)."""
        pipe, self._pipe = self._pipe, None
        if self._finalizer is not None:
            self._finalizer.detach()
        self._finalizer = None
        return pipe

    def close(self) -> None:
        with self._pipe_lock:
            pipe = self._detach_pipe()
        if pipe is not None:
            pipe.close()
        super().close()

    def _abort(self) -> None:
        with self._pipe_lock:
            pipe = self._detach_pipe()
        if pipe is not None:
            pipe.abort()
        super().close()

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

    def _start(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        if any((line.get("sim") or {}).get("seed") is not None for _, line in items):
            super()._start(items)  # 난수 흐름을 잇는 줄 — 이 호출만의 프로세스에서 (`_run`)
            return
        try:
            self._live_pipe().send(items, self._finish)
        except RuntimeError:  # 막 죽은 프로세스 — 한 번 새로 띄워 보낸다
            self._live_pipe().send(items, self._finish)

    def _run(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _run_batch([str(self.sim_bin), "--batch"], lines, what="nikke-sim",
                          env=self._env(min(self.jobs, len(lines))))


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
