"""평가기 인터페이스와 nikke-calc 어댑터.

최적화 코드는 `Evaluator.evaluate()`만 쓴다. 계산기 내부는 import하지 않고, nikke-calc는
`python -m runner.sim --batch` 서브프로세스로만 부른다 (입출력 계약: nikke-calc `docs/SIM-JSON.md`,
요청 JSON v2 — `squad` · `sim` · `boss` · `enemy` · `operation` · `profile` · `chars`. nikke-calc `167698c`부터).

- **평가는 언제나 180초 전체.** 요청에 `sim.duration`을 적으면 거절한다.
- **기본은 기대값 모드**(`sim.expected: true`) — 1회로 결정론적이라 캐시할 수 있다.
- **계약 판을 맞춘다.** 요청에 `schema_version`을 싣고, 판이 다른 결과는 받지 않는다 — 평가기가 계약을 바꾸면
  조용히 틀리지 않고 바로 끊긴다.
- **예산 = 실제로 돌린 시뮬 횟수.** 캐시 적중은 세지 않는다.
- **캐시 키에는 평가기 커밋이 들어간다.** 커밋 안 된 변경이 있는(dirty) 평가기는 결과를 캐시하지 않는다.
- **육성은 요청에 인라인으로 싣는다** — `options={"profile": {"base": "default", "chars": {...}}}`
  (형식: nikke-calc `docs/SIM-JSON.md` §육성). 요청 줄이 곧 육성이라 캐시 키가 내용을 따라간다.
  nikke-calc `profiles/`에 파일을 쓰지 않는다. 프로필을 *이름*으로 주면(내 계정 `me` 등) 그 파일
  내용의 해시를 캐시 키에 넣는다 — 이름은 같은데 내용이 바뀐 프로필을 옛 결과로 읽지 않게.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = REPO_ROOT / ".cache" / "evals.sqlite"
SCHEMA_VERSION = 2  # nikke-calc 요청·결과 계약의 판 (docs/SIM-JSON.md §버전)
FORBIDDEN_OPTIONS = frozenset({"squad", "id", "schema_version", "duration"})


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

    def evaluate(self, requests: Sequence[EvalRequest]) -> list[EvalResult]: ...


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


class NikkeCalcEvaluator:
    """`Jgaram/nikke-calc`를 `--batch` 프로세스 `jobs`개로 나눠 돌린다.

    calc_dir: nikke-calc 체크아웃 경로. 없으면 환경변수 `NIKKE_CALC_DIR`.
    budget:   돌릴 수 있는 시뮬 횟수 상한 (None = 무제한). 넘칠 요청은 아예 시작하지 않는다.
    """

    def __init__(self, calc_dir: str | Path | None = None, *, jobs: int | None = None,
                 cache: Cache | None | bool = True, budget: int | None = None):
        calc_dir = calc_dir or os.environ.get("NIKKE_CALC_DIR")
        if not calc_dir:
            raise ValueError("nikke-calc 경로가 필요하다 — calc_dir 인자나 NIKKE_CALC_DIR 환경변수")
        self.calc_dir = Path(calc_dir).resolve()
        if not (self.calc_dir / "runner" / "sim.py").is_file():
            raise ValueError(f"nikke-calc 체크아웃이 아니다: {self.calc_dir}")
        self.jobs = jobs or min(os.cpu_count() or 1, 8)
        self.budget = budget
        self.sim_count = 0
        self.cache_hits = 0

        dirty = bool(_git(self.calc_dir, "status", "--porcelain", "--untracked-files=no"))
        self.version = {"repo": "Jgaram/nikke-calc", "commit": _git(self.calc_dir, "rev-parse", "HEAD"),
                        "dirty": dirty}
        if cache is True:
            cache = None if dirty else Cache(DEFAULT_CACHE)
        self.cache: Cache | None = cache or None

    def evaluate(self, requests: Sequence[EvalRequest]) -> list[EvalResult]:
        lines = [r.to_line() for r in requests]
        results: list[EvalResult | None] = [None] * len(lines)
        keys = [Cache.key(self.version["commit"], self._key_line(ln)) for ln in lines]

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
            if out.get("schema_version") != SCHEMA_VERSION:
                raise RuntimeError(f"평가기 계약 판이 다르다: 결과 {out.get('schema_version')} ≠ 어댑터 {SCHEMA_VERSION}"
                                   f" (nikke-calc {self.version['commit'][:7]}, docs/SIM-JSON.md §버전)")
            if "error" not in out and out.get("evaluator", {}).get("commit") != self.version["commit"]:
                raise RuntimeError(f"평가기 커밋이 실행 중에 바뀌었다: {out.get('evaluator')} ≠ {self.version}")
            for i in todo[key]:
                results[i] = EvalResult(out.get("total_damage"), out)
            if "error" not in out:
                fresh.append((key, out))
        if self.cache and fresh:
            self.cache.put_many(fresh)
        return results  # type: ignore[return-value]

    def _key_line(self, line: dict[str, Any]) -> dict[str, Any]:
        """캐시 키용 요청 줄. 프로필 *이름*은 파일 내용 해시로 바꿔 넣는다(인라인은 줄 자체가 내용)."""
        prof = line.get("profile")
        if not isinstance(prof, str) or prof.lstrip().startswith("{"):
            return line
        path = self.calc_dir / "profiles" / f"{prof}.json"
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        return {**line, "profile": {"file": prof, "sha256": digest}}

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
        stdin = "".join(json.dumps(ln, ensure_ascii=False) + "\n" for ln in lines)
        proc = subprocess.run(
            [sys.executable, "-m", "runner.sim", "--batch"], cwd=self.calc_dir,
            input=stdin, capture_output=True, text=True, encoding="utf-8",
        )
        rows = [json.loads(s) for s in proc.stdout.splitlines() if s.strip()]
        if proc.returncode != 0 or len(rows) != len(lines):
            raise RuntimeError(f"nikke-calc --batch 실패 (코드 {proc.returncode}, {len(rows)}/{len(lines)}줄)\n"
                               f"{proc.stderr[-2000:]}")
        return rows
