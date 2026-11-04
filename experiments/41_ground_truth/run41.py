"""실험 41 — 답안지: 작은 풀 전수 계산으로 풀 안의 최적 5덱(OPT)을 알고 탐색 · 랭커 · 실전을 채점한다. README.

    source .cache/evaluators.env && python -I experiments/41_ground_truth/run41.py check --season 36     # 평가기 대조(실험 36 기록)
    source .cache/evaluators.env && python -I experiments/41_ground_truth/run41.py table --season 36     # 1단계 · 끊기면 같은 명령
    source .cache/evaluators.env && python -I experiments/41_ground_truth/run41.py refine --season 36    # 2단계
    python -I experiments/41_ground_truth/run41.py pack --season 36                                      # 3단계(시뮬 0)
    python -I experiments/41_ground_truth/run41.py replay --season 36 --seed 0                           # 4단계(시뮬 0)
    python -I experiments/41_ground_truth/run41.py analyze                                               # → analysis.json · results.md

- 값 = 기본 레이어 1시뮬 사전 값: 실험 31 `options`(시즌 보스 속성 · 그때 없던 애장품 0단계) + `sim.camera_reload_cancel`
  (사용자 결정 2026-11-04 「켬」). 코어 없음, 계산기 기본 스펙. 평가기는 nikke-calc-rs master(`83a6d54` 이후).
- 1단계 표는 `run_log/S??/table/c????.jsonl.gz`(구성 CHUNK개씩)에 쓴다. 조각이 있으면 건너뛰므로 끊기면 같은 명령으로 잇는다.
  줄 = [구성 번호(pool41.iter_comps 순), 값(억), 니케별 딜(억, 배치 순서대로)] — 배치 순서는 `base_order`로 다시 만든다.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import random
import sys
import time
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


P41 = sys.modules.get("pool41") or _load("pool41", HERE / "pool41.py")
run31 = sys.modules.get("run31") or _load("run31", EXPS / "31_recent_seasons" / "run31.py")
R10, R9, R30, R2 = run31.R10, run31.R9, run31.R30, run31.R9.R2
E8 = 1e8

# ---------------------------------------------------------------- 정한 값(README — 사용자 결정 2026-11-04)
CAMERA_RELOAD_CANCEL = True    # 평가기 옵션 켬(사용자 결정)
SEASONS = P41.SEASONS          # (36, 39, 42)
CHUNK = 5000
LOG = HERE / "run_log"
EXP36_LOG = EXPS / "36_season_refresh" / "run_log"
POOLS = json.loads(P41.OUT.read_text(encoding="utf-8"))["seasons"] if P41.OUT.exists() else {}
BURST = P41.BURST


def sdir(s: int) -> Path:
    return LOG / f"S{int(s):02d}"


def jload(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def jdump(p: Path, x: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def pool(s: int) -> list[str]:
    return list(POOLS[str(s)]["pool"])


def options(s: int) -> dict[str, Any]:
    o = run31.options(s, 0)
    if CAMERA_RELOAD_CANCEL:
        o["sim"] = {**o.get("sim", {}), "camera_reload_cancel": True}
    return o


def base_order(comp: Sequence[str]) -> tuple[str, ...]:
    """기본 배치 순서: 단계 1 · 2 · A · 3(실험 10 `arrange`), 같은 단계 안은 이름순."""
    names = sorted(comp)
    return tuple(n for st in "12A3" for n in names if BURST[n] == st)


def comps(s: int) -> list[tuple[str, ...]]:
    return list(P41.iter_comps(pool(s)))


def evaluator(jobs: int = 4) -> Any:
    from nikke_opt.evaluator import make_evaluator
    return make_evaluator("rust", jobs=jobs, cache=False)


def ev_version(ev: Any) -> str:
    v = ev.version
    return f"{v.get('repo')} {str(v.get('commit'))[:7]}" + (" dirty" if v.get("dirty") else "")


def run_orders(s: int, orders: Sequence[Sequence[str]], ev: Any) -> list[tuple[float | None, list[float] | None]]:
    """배치 순서마다 (값(억), 니케별 딜(억, 배치 순서대로))."""
    from nikke_opt.evaluator import EvalRequest
    o = options(s)
    res = ev.evaluate([EvalRequest(tuple(q), boss=None, options=o) for q in orders])
    out = []
    for q, r in zip(orders, res):
        if r.error or r.total_damage is None:
            out.append((None, None))
            continue
        dmg = {x["name"]: x["damage"] for x in r.raw.get("members", [])}
        out.append((r.total_damage / E8, [round(dmg.get(n, 0) / E8, 4) for n in q]))
    return out


# ---------------------------------------------------------------- 대조: 카메라 옵션을 켠 값이 실험 36 사전 값과 같은가

def cmd_check(a: argparse.Namespace) -> int:
    """실험 36 기록(랭커 덱 rankers.json 코어 없음 · B_s0 무작위 a.n개)을 이 실험의 options로 다시 재 차이를 센다."""
    out = {}
    with evaluator(a.jobs) as ev:
        for s in [int(x) for x in str(a.season).split(",")]:
            d = EXP36_LOG / f"S{s}"
            rk = jload(d / "rankers.json")["squads"]
            pairs = [(tuple(k.split(",")), v["nocore"]) for k, v in rk.items() if v.get("nocore") is not None]
            recs = [r for r in run31.load_recs(d / "B_s0.jsonl.gz") if r.get("total_damage") is not None]
            rng = random.Random(f"exp41-check-{s}")
            pairs += [(tuple(r["squad"]), r["total_damage"] / E8) for r in rng.sample(recs, min(a.n, len(recs)))]
            t0, n0 = time.time(), ev.sim_count
            got = run_orders(s, [q for q, _ in pairs], ev)
            diffs = [(q, old, new) for (q, old), (new, _) in zip(pairs, got) if new is None or abs(new - old) > 1e-6]
            out[str(s)] = {"decks": len(pairs), "diff": len(diffs), "examples": [[list(q), old, new] for q, old, new in diffs[:5]],
                           "sims": ev.sim_count - n0, "seconds": round(time.time() - t0, 1), "evaluator": ev_version(ev),
                           "sims_per_s": round((ev.sim_count - n0) / max(time.time() - t0, 1e-9), 2)}
            print(json.dumps({"season": s, **out[str(s)]}, ensure_ascii=False), flush=True)
    prev = jload(HERE / "run_log" / "check.json") or {}
    jdump(HERE / "run_log" / "check.json", {**prev, **out, "camera_reload_cancel": CAMERA_RELOAD_CANCEL})
    return 0


# ---------------------------------------------------------------- 1단계: 전수 표

def chunk_file(s: int, k: int) -> Path:
    return sdir(s) / "table" / f"c{k:04d}.jsonl.gz"


def iter_table(s: int) -> Iterator[list]:
    """표 줄 [번호, 값, 니케별 딜] — 조각 순서대로."""
    for f in sorted((sdir(s) / "table").glob("c*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                yield json.loads(line)


def load_table(s: int) -> tuple[list[tuple[str, ...]], list[float | None]]:
    """(구성 목록, 기본 순서 값) — 값이 없는 구성(오류 · 아직 안 돈 조각)은 None."""
    cs = comps(s)
    vals: list[float | None] = [None] * len(cs)
    for i, v, _ in iter_table(s):
        vals[i] = v
    return cs, vals


def cmd_table(a: argparse.Namespace) -> int:
    s = a.season
    cs = comps(s)
    assert len(cs) == POOLS[str(s)]["comps"], (len(cs), POOLS[str(s)]["comps"])
    n_chunks = (len(cs) + CHUNK - 1) // CHUNK
    meta_f = sdir(s) / "table_meta.json"
    meta = jload(meta_f) or {"season": s, "comps": len(cs), "chunk": CHUNK, "chunks": n_chunks, "options": options(s),
                             "order": "단계 1 · 2 · A · 3, 같은 단계 안 이름순", "parts": {}}
    with evaluator(a.jobs) as ev:
        ver = ev_version(ev)
        for k in range(n_chunks):
            f = chunk_file(s, k)
            if f.exists():
                continue
            if a.limit is not None and a.limit <= 0:
                break
            idx = list(range(k * CHUNK, min((k + 1) * CHUNK, len(cs))))
            orders = [base_order(cs[i]) for i in idx]
            t0, n0 = time.time(), ev.sim_count
            got = run_orders(s, orders, ev)
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                for i, (v, m) in zip(idx, got):
                    fh.write(json.dumps([i, v, m], ensure_ascii=False) + "\n")
            tmp.rename(f)
            sec = time.time() - t0
            meta["parts"][str(k)] = {"sims": ev.sim_count - n0, "seconds": round(sec, 1),
                                     "errors": sum(v is None for v, _ in got), "evaluator": ver}
            jdump(meta_f, meta)
            done = len(meta["parts"])
            print(f"S{s} 조각 {k + 1}/{n_chunks} ({done} 끝) {ev.sim_count - n0}시뮬 {sec:.0f}초 "
                  f"{(ev.sim_count - n0) / max(sec, 1e-9):.1f}/초", flush=True)
            if a.limit is not None:
                a.limit -= 1
    return 0


# ---------------------------------------------------------------- 명령

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--season", default="36,39,42")
    c.add_argument("--n", type=int, default=300)
    c.add_argument("--jobs", type=int, default=4)
    t = sub.add_parser("table")
    t.add_argument("--season", type=int, required=True)
    t.add_argument("--jobs", type=int, default=4)
    t.add_argument("--limit", type=int, default=None, help="이번에 돌릴 조각 수 상한")
    a = p.parse_args(argv)
    return {"check": cmd_check, "table": cmd_table}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
