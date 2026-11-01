"""실험 30 0단계 — 기존 사전 계산 기록으로 5덱 지도 크기 재기(시뮬 0).

    python experiments/30_element_map/pre30.py [--workers 4] [--limit 60]
        → pre_map.json · pre_map.md
    python experiments/30_element_map/pre30.py --pack      → pre_pack.json · pre_pack.md

- 지도 = 기록에서 탐욕으로 고른 큰 분류 대표들. 1번 = 최선 5덱(A). 다음 대표 = 앞의 대표 **모두와** J ≤ 0.2
  (기준마다 공유 쌍 16 이하)인 겹치지 않는 5덱 중 합 최대(실험 28 `pick_far`). 합이 A의 95% 아래로 내려가거나
  못 찾으면 멈춘다. 대표 수는 97% · 95% 문턱마다 센다.
- 기록: 허수아비 SSR 177명 시드 4개(실험 11 PB15 · 실험 12 PB15s1~s3) 각각 · 시드 4개 합치기(U4),
  실험 22 시즌 8개 × {코어 없음, 코어 30}(시즌 보스 속성, 시즌 풀, 시드 1개).
- 코어 재평가 근사(관찰): 실험 22 같은 시즌의 코어 없음 기록 상위 N 구성 중 코어 30 기록에도 있는 것만으로
  코어 30 값을 묶어 본다(실제 재평가의 하한 근사). 기록에 없는 구성은 값이 없어 빠진다.
  → 두 기록이 겹치는 구성이 약 20%뿐이라 이 근사는 쓸 수 없었다(대부분 0%). 대신 `--pack`(아래)으로 후보 고르는 법을 봤다.
- `--pack`: 코어 없음 기록에서 후보 n개만 남겼을 때 5덱이 짜지는가(값 순 상위 대 니케마다 돌아가며).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

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


T28 = sys.modules.get("tree28") or _load("tree28", EXPS / "28_plan_tree" / "tree28.py")
R9, P24, SIM = T28.R9, T28.P24, T28.SIM

THETA = 0.2
GOOD, LOW = 0.97, 0.95
MAX_CLASSES = 8
CORE_TOP = (1000, 3000)

EXP11 = EXPS / "11_wide_precompute" / "run_log"
EXP12 = EXPS / "12_precompute_seeds" / "run_log"
EXP22 = EXPS / "22_ranker_check" / "run_log"
SEASONS = (4, 9, 14, 18, 23, 28, 34, 40)


def seed_files() -> dict[str, Path]:
    return {"s0": EXP11 / "precompute_PB15.jsonl.gz", **{f"s{k}": EXP12 / f"precompute_PB15s{k}.jsonl.gz" for k in (1, 2, 3)}}


def book_from(paths: Sequence[Path]) -> dict[frozenset, tuple[float, tuple]]:
    best: dict[frozenset, tuple[float, tuple]] = {}
    for p in paths:
        for c, (v, sq) in P24.book_of(p).items():
            if c not in best or v > best[c][0]:
                best[c] = (v, sq)
    return best


def class_map(book: Mapping[frozenset, tuple[float, tuple]], limit: float) -> dict[str, Any]:
    """탐욕 지도: A = 최선, 다음 = 앞 대표 모두와 J ≤ θ인 최선. LOW 아래면 멈춘다."""
    t0 = time.time()
    a_total, a_decks = R9.pack_vals(book)
    reps = [{"total": a_total, "decks": [[v, list(q)] for v, q in a_decks], "exact": True}]
    while len(reps) < MAX_CLASSES:
        refs = [[tuple(q) for _, q in r["decks"]] for r in reps]
        got = T28.pick_far(book, book, refs, theta=THETA, limit=limit)
        if not got["found"] or got["total"] < LOW * a_total:
            if got["found"]:
                reps.append({"total": got["total"], "decks": [[v, list(q)] for v, q in got["decks"]],
                             "exact": got["exact"], "below": True})
            break
        reps.append({"total": got["total"], "decks": [[v, list(q)] for v, q in got["decks"]], "exact": got["exact"]})
    for r in reps:
        r["ratio"] = r["total"] / a_total
    plans = [[q for _, q in r["decks"]] for r in reps]
    jmax = [max((SIM.pair_jaccard(plans[i], plans[j]) for j in range(len(plans)) if j != i), default=None)
            for i in range(len(plans))]
    for r, j in zip(reps, jmax):
        r["jmax"] = j
    ok = [r for r in reps if not r.get("below")]
    return {"comps": len(book), "best": a_total,
            "n97": sum(1 for r in ok if r["ratio"] >= GOOD - 1e-12),
            "n95": sum(1 for r in ok if r["ratio"] >= LOW - 1e-12),
            "exact": all(r["exact"] for r in reps), "reps": reps, "seconds": round(time.time() - t0, 1)}


def core_proxy(s: int) -> dict[str, Any]:
    """코어 없음 상위 N 구성 ∩ 코어 30 기록 → 코어 30 값으로 묶기(실제 재평가의 하한 근사)."""
    no = P24.book_of(EXP22 / f"precompute_S{s:02d}_nocore.jsonl.gz")
    co = P24.book_of(EXP22 / f"precompute_S{s:02d}_core30.jsonl.gz")
    co_best = R9.pack_vals(co)[0]
    no_in_co = R9.pack_vals({c: co[c] for c in no if c in co})[0]
    out: dict[str, Any] = {"season": s, "nocore_comps": len(no), "core30_comps": len(co),
                           "overlap": sum(1 for c in no if c in co), "core30_best": co_best,
                           "all_overlap_ratio": no_in_co / co_best}
    ranked = sorted(no, key=lambda c: -no[c][0])
    for n in CORE_TOP:
        top = ranked[:n]
        have = {c: co[c] for c in top if c in co}
        v = R9.pack_vals(have)[0] if len(have) >= 5 else 0.0
        out[f"top{n}"] = {"have": len(have), "packed": v, "ratio": v / co_best}
    # 코어 30 최선 5덱 덱들이 코어 없음 순위 몇 위였나
    rank = {c: i for i, c in enumerate(ranked)}
    best_decks = R9.pack_vals(co)[1]
    out["core30_best_deck_nocore_rank"] = [rank.get(frozenset(q)) for _, q in best_decks]
    return out


def rr_select(book: Mapping[frozenset, tuple[float, tuple]], n: int) -> list[frozenset]:
    """니케마다 돌아가며 그 니케가 든 구성 중 k번째로 값이 큰 것(run30.rr_select와 같은 규칙)."""
    by: dict[str, list[frozenset]] = {}
    for c, _ in sorted(book.items(), key=lambda t: (-t[1][0], t[1][1])):
        for x in c:
            by.setdefault(x, []).append(c)
    out, seen, names, k = [], set(), sorted(by), 0
    while len(out) < n and any(k < len(by[x]) for x in names):
        for x in names:
            if k < len(by[x]) and by[x][k] not in seen:
                seen.add(by[x][k])
                out.append(by[x][k])
                if len(out) >= n:
                    break
        k += 1
    return out


def packability(s: int) -> dict[str, Any]:
    """코어 없음 기록에서 후보 n개만 남겼을 때 겹치지 않는 5덱 최선 ÷ 기록 전체 최선(코어 없음 값, 시뮬 0)."""
    no = P24.book_of(EXP22 / f"precompute_S{s:02d}_nocore.jsonl.gz")
    best = R9.pack_vals(no)[0]
    ranked = sorted(no, key=lambda c: -no[c][0])
    out: dict[str, Any] = {"season": s}
    for n in (1000, 2000, 3000):
        out[f"top{n}"] = R9.pack_vals({c: no[c] for c in ranked[:n]})[0] / best
        out[f"rr{n}"] = R9.pack_vals({c: no[c] for c in rr_select(no, n)})[0] / best
    return out


def cmd_pack(workers: int) -> int:
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(packability, SEASONS))
    (HERE / "pre_pack.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    L = ["# 실험 30 0단계 — 후보만으로 5덱이 짜지는가(시뮬 0)", "",
         "실험 22 코어 없음 기록. 후보 n개만 남겨 묶은 최선 ÷ 기록 전체 최선(코어 없음 값). 0% = 겹치지 않는 5덱을 못 짬.",
         "값 순 = 전체 상위 n, 돌아가며 = 니케마다 돌아가며 상위(run30 `rr_select`).", "",
         "| 시즌 | 값 순 1,000 | 2,000 | 3,000 | 돌아가며 1,000 | 2,000 | 3,000 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| S{r['season']:02d} | " + " | ".join(f"{r[k] * 100:.1f}%" for k in
                                                       ("top1000", "top2000", "top3000", "rr1000", "rr2000", "rr3000")) + " |")
    (HERE / "pre_pack.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


def job(item: tuple[str, list[str], float]) -> tuple[str, dict[str, Any]]:
    name, paths, limit = item
    return name, class_map(book_from([Path(p) for p in paths]), limit)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=float, default=60.0)
    p.add_argument("--pack", action="store_true", help="후보만으로 5덱이 짜지는가만 → pre_pack.md")
    a = p.parse_args(argv)
    if a.pack:
        return cmd_pack(a.workers)
    seeds = seed_files()
    items = [(k, [str(v)], a.limit) for k, v in seeds.items()]
    items.append(("U4", [str(v) for v in seeds.values()], a.limit))
    for s in SEASONS:
        for b in ("nocore", "core30"):
            items.append((f"S{s:02d}_{b}", [str(EXP22 / f"precompute_S{s:02d}_{b}.jsonl.gz")], a.limit))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        maps = dict(pool.map(job, items))
        cores = list(pool.map(core_proxy, SEASONS))
    out = {"theta": THETA, "good": GOOD, "low": LOW, "maps": maps, "core": cores, "seconds": round(time.time() - t0, 1)}
    (HERE / "pre_map.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    L = ["# 실험 30 0단계 — 기존 기록의 5덱 지도(시뮬 0)", "",
         f"큰 분류 대표끼리 J ≤ {THETA}, 탐욕(실험 28 `pick_far`). 값은 기본 레이어(후처리 전). 계산 {out['seconds']}초.", "",
         "| 기록 | 구성 | 최선(억) | 대표 비율(1번 = 100%) | ≥97% | ≥95% | 정확해 |", "|---|---|---|---|---|---|---|"]
    for k, m in maps.items():
        rs = " · ".join(f"{r['ratio'] * 100:.1f}" + ("↓" if r.get("below") else "") for r in m["reps"])
        L.append(f"| {k} | {m['comps']:,} | {m['best']:.1f} | {rs} | {m['n97']} | {m['n95']} | {'O' if m['exact'] else 'X'} |")
    n97 = [m["n97"] for k, m in maps.items() if k.startswith("S")]
    L += ["", f"실험 22 16판: ≥97% 대표 수 중앙 {statistics.median(n97)} (최소 {min(n97)} · 최대 {max(n97)})", "",
          "## 코어 재평가 근사(코어 없음 상위 N ∩ 코어 30 기록 → 코어 30 값으로 묶기)", "",
          "| 시즌 | 겹친 구성 | 겹친 것 전부 | 상위 1,000 | 상위 3,000 | 코어 30 최선 덱의 코어 없음 순위 |", "|---|---|---|---|---|---|"]
    for c in cores:
        L.append(f"| S{c['season']:02d} | {c['overlap']:,} / {c['nocore_comps']:,} | {c['all_overlap_ratio'] * 100:.1f}% | "
                 f"{c['top1000']['ratio'] * 100:.1f}% ({c['top1000']['have']}) | {c['top3000']['ratio'] * 100:.1f}% ({c['top3000']['have']}) | "
                 f"{', '.join('-' if r is None else str(r + 1) for r in c['core30_best_deck_nocore_rank'])} |")
    (HERE / "pre_map.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
