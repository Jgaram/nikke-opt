"""실험 42 — 규칙 없는 묶음 단위 탐색. README.

    source .cache/evaluators.env && python -I experiments/42_bundle_search/run42.py free --season 36       # 0a 규칙 없는 표(끊기면 같은 명령)
    python -I experiments/42_bundle_search/run42.py freepack --season 36                                    # 0b 규칙 없는 OPT(시뮬 0)
    source .cache/evaluators.env && python -I experiments/42_bundle_search/run42.py ordercheck --season 36  # 0c 단계 안 순서 × 카메라
    python -I experiments/42_bundle_search/run42.py replay --season 36 --arm P --seed 0                     # 1단계(시뮬 0)

- 값 · 계정 · 풀은 실험 41과 같다(`run41.options` · `pool41.json`, 기본 순서 `run41.base_order`). 바꾸는 것은 공간(5인 조합 전부)이다.
- 0a 표는 실험 41 표(규칙 공간)의 같은 구성을 그대로 다시 쓴다 — 같은 요청(같은 순서 · options · 평가기)이라 값이 같다.
- 실행 중 기록은 `NIKKE42_LOG`(레포 밖 작업 폴더)에 쓸 수 있다. 없으면 이 폴더의 `run_log/`.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import sys
import time
from itertools import combinations
from math import comb
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
ROOT = EXPS.parent
sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R41 = sys.modules.get("run41") or _load("run41", EXPS / "41_ground_truth" / "run41.py")
P41, run31, R10, R9 = R41.P41, R41.run31, R41.R10, R41.R9
E8 = 1e8

SEASONS = R41.SEASONS
CHUNK = 5000
LOG = Path(os.environ.get("NIKKE42_LOG") or HERE / "run_log")
BURST = R41.BURST


def sdir(s: int) -> Path:
    return LOG / f"S{int(s):02d}"


jload, jdump, pool, options, base_order = R41.jload, R41.jdump, R41.pool, R41.options, R41.base_order


# ---------------------------------------------------------------- 0a 규칙 없는 표

def free_comps(s: int) -> list[tuple[str, ...]]:
    """풀의 5인 조합 전부(이름순 조합 순서 — 원소도 이름순 튜플, 실험 41 구성과 같은 모양)."""
    return list(combinations(sorted(pool(s)), 5))


def free_count(s: int) -> int:
    return comb(len(pool(s)), 5)


def chunk_file(s: int, k: int) -> Path:
    return sdir(s) / "free" / f"c{k:04d}.jsonl.gz"


def exp41_rows(s: int) -> dict[tuple, tuple[float | None, list | None]]:
    """실험 41 표(레포 기록) — 구성 → (값, 니케별 딜)."""
    cs = R41.comps(s)
    out: dict[tuple, tuple[float | None, list | None]] = {}
    for i, v, m in R41.iter_table(s):
        out[cs[i]] = (v, m)
    return out


def iter_free(s: int) -> Iterator[list]:
    for f in sorted((sdir(s) / "free").glob("c*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                yield json.loads(line)


def load_free(s: int) -> tuple[list[tuple[str, ...]], list[float | None]]:
    cs = free_comps(s)
    vals: list[float | None] = [None] * len(cs)
    for r in iter_free(s):
        vals[r[0]] = r[1]
    return cs, vals


def free_table(s: int) -> Any:
    """규칙 없는 표를 실험 41 `Table`로(기본 순서 값만)."""
    cs, vals = load_free(s)
    miss = sum(v is None for v in vals)
    if miss:
        meta = jload(sdir(s) / "free_meta.json") or {}
        errs = sum(p.get("errors", 0) for p in meta.get("parts", {}).values())
        if miss > errs:
            raise RuntimeError(f"S{s} 규칙 없는 표가 덜 됐다: 값 없는 구성 {miss:,} (오류 {errs})")
    return R41.Table(s, cs, vals, None, pool(s))


def cmd_free(a: argparse.Namespace) -> int:
    s = a.season
    cs = free_comps(s)
    n_chunks = (len(cs) + CHUNK - 1) // CHUNK
    meta_f = sdir(s) / "free_meta.json"
    meta = jload(meta_f) or {"season": s, "comps": len(cs), "chunk": CHUNK, "chunks": n_chunks, "options": options(s),
                             "order": "실험 41 base_order(단계 1 · 2 · A · 3, 같은 단계 안 이름순)", "parts": {}}
    old = exp41_rows(s)
    with R41.evaluator(a.jobs) as ev:
        ver = R41.ev_version(ev)
        for k in range(n_chunks):
            f = chunk_file(s, k)
            if f.exists():
                continue
            if a.limit is not None and a.limit <= 0:
                break
            idx = list(range(k * CHUNK, min((k + 1) * CHUNK, len(cs))))
            new = [i for i in idx if cs[i] not in old]
            t0, n0 = time.time(), ev.sim_count
            got = dict(zip(new, R41.run_orders(s, [base_order(cs[i]) for i in new], ev))) if new else {}
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                for i in idx:
                    if i in got:
                        v, m = got[i]
                        fh.write(json.dumps([i, v, m, 0], ensure_ascii=False) + "\n")
                    else:
                        v, m = old[cs[i]]
                        fh.write(json.dumps([i, v, m, 41], ensure_ascii=False) + "\n")
            tmp.rename(f)
            sec = time.time() - t0
            meta["parts"][str(k)] = {"sims": ev.sim_count - n0, "reused": len(idx) - len(new), "seconds": round(sec, 1),
                                     "errors": sum(got[i][0] is None for i in got), "evaluator": ver}
            jdump(meta_f, meta)
            print(f"S{s} 조각 {k + 1}/{n_chunks} ({len(meta['parts'])} 끝) 새 {len(new)} · 재사용 {len(idx) - len(new)} "
                  f"{sec:.0f}초 {(ev.sim_count - n0) / max(sec, 1e-9):.1f}/초", flush=True)
            if a.limit is not None:
                a.limit -= 1
    return 0


# ---------------------------------------------------------------- 명령

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("free")
    f.add_argument("--season", type=int, required=True)
    f.add_argument("--jobs", type=int, default=4)
    f.add_argument("--limit", type=int, default=None)
    a = p.parse_args(argv)
    return {"free": cmd_free}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
