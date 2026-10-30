"""실험 9 분석 — README §잴 것 · §판단 기준.

    python experiments/09_account_pack/analyze9.py --runs <val 탐색 dir> --post <val 후처리 dir> [--dev-runs <dev dir>]
        --out experiments/09_account_pack/results.md [--json <요약.json>]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

METHODS = ("L0", "L0k", "L1", "L2")
BUDGETS = (300, 800, 2000)
MARGIN = 0.005
SHARE = 0.75  # 시나리오 수의 이 몫 이상(8개면 6개)


def load_dir(d: Path, suffix: str = ".json") -> dict[tuple[str, str, int], dict[str, Any]]:
    out = {}
    for p in sorted(d.glob(f"*{suffix}")):
        if suffix == ".json" and p.name.endswith(".post.json"):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        out[(r["scenario"], r["method"], r["budget"])] = r
    return out


def need(n: int) -> int:
    return math.ceil(SHARE * n)


def better(gs: Sequence[float]) -> bool:
    return bool(gs) and statistics.median(gs) >= MARGIN and sum(g > 0 for g in gs) >= need(len(gs))


def worse(gs: Sequence[float]) -> bool:
    return bool(gs) and statistics.median(gs) <= -MARGIN and sum(g < 0 for g in gs) >= need(len(gs))


def gains(P: Mapping[tuple[str, str, int], float], scen: Sequence[str], m: str, b: int) -> list[float]:
    return [P[(s, m, b)] / P[(s, "L0", b)] - 1 for s in scen if (s, m, b) in P and (s, "L0", b) in P]


def judge(P: Mapping[tuple[str, str, int], float], scen: Sequence[str]) -> dict[str, Any]:
    wins = {m: [b for b in BUDGETS if better(gains(P, scen, m, b))] for m in METHODS[1:]}
    loses = {m: [b for b in BUDGETS if worse(gains(P, scen, m, b))] for m in METHODS[1:]}
    top = [m for m in ("L1", "L2") if len(wins[m]) >= 2]
    if top:
        def key(m):
            return tuple(statistics.median(gains(P, scen, m, b)) for b in (800, 2000))
        pick = max(top, key=key) if len(top) > 1 else top[0]
        line = 1
    elif len(wins["L0k"]) >= 2:
        pick, line = "L0k", 2
    else:
        pick, line = "L0", 3
    small = [m for m in METHODS[1:] if wins[m] == [300]]
    return {"line": line, "pick": pick, "wins": wins, "loses": loses, "small_budget": small}


def nikkes(squads: Sequence[Sequence[Any]]) -> set[str]:
    return {n for x in squads for n in x[1]}


def pct(x: float | None, nd: int = 1) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def analyze(runs: Mapping, post: Mapping, top10: Mapping | None = None, dev: Mapping | None = None) -> dict[str, Any]:
    scen = sorted({k[0] for k in runs})
    names = {k[0]: r["name"] for k, r in runs.items()}
    P = {k: r["total"] for k, r in post.items()}
    Q = {k: r["final"]["total"] for k, r in runs.items()}
    rows = []
    for b in BUDGETS:
        for m in METHODS[1:]:
            g, gq = gains(P, scen, m, b), gains(Q, scen, m, b)
            rows.append({"budget": b, "method": m, "n": len(g),
                         "median": statistics.median(g) if g else None,
                         "pos": sum(x > 0 for x in g), "neg": sum(x < 0 for x in g),
                         "min": min(g) if g else None, "max": max(g) if g else None,
                         "better": better(g), "worse": worse(g),
                         "pre_median": statistics.median(gq) if gq else None, "pre_pos": sum(x > 0 for x in gq),
                         "pre_better": better(gq)})
    per = []
    for s in scen:
        for b in BUDGETS:
            row = {"scenario": s, "name": names[s], "budget": b}
            for m in METHODS:
                k = (s, m, b)
                row[m] = {"pre": Q.get(k), "post": P.get(k)}
            per.append(row)
    alt = []
    for k, r in sorted(runs.items()):
        f, a = r["final"], r["alt"]
        alt.append({"scenario": k[0], "method": k[1], "budget": k[2], "ratio": a["total"] / f["total"] if f["total"] else None,
                    "shared": len(nikkes(f["squads"]) & nikkes(a["squads"]))})
    postc = [{"scenario": k[0], "method": k[1], "budget": k[2], "gain": r["total"] / r["pre"] - 1,
              "evals": r["post_evals"], "targets": r["targets"]} for k, r in sorted(post.items())]
    base = {}
    for s in scen:
        r = runs.get((s, "L0", 2000))
        if r and r.get("baseline"):
            bl = r["baseline"]
            base[s] = {"best": bl["best"], "median": bl["median"], "repack": bl["repack"],
                       "players": bl["players_done"],
                       "final": {m: Q.get((s, m, b)) for m in METHODS for b in BUDGETS},
                       "post": {m: P.get((s, m, b)) for m in METHODS for b in BUDGETS}}
    sec = None
    if top10:
        sec = [{"scenario": k[0], "top5": post[k]["total"], "top10": r["total"],
                "same": sorted(map(tuple, (x[1] for x in post[k]["squads"]))) == sorted(map(tuple, (x[1] for x in r["squads"])))}
               for k, r in sorted(top10.items()) if k in post]
    devrows = None
    if dev:
        dscen = sorted({k[0] for k in dev})
        Qd = {k: r["final"]["total"] for k, r in dev.items()}
        devrows = [{"budget": b, "method": m, "median": statistics.median(g) if (g := gains(Qd, dscen, m, b)) else None,
                    "pos": sum(x > 0 for x in g), "n": len(g)}
                   for b in BUDGETS for m in METHODS[1:]]
    evals = {m: statistics.median([r["evals"] for k, r in runs.items() if k[1] == m]) for m in METHODS}
    trans = {m: statistics.median([r["transplant_evals"] for k, r in runs.items() if k[1] == m]) for m in METHODS}
    return {"scenarios": scen, "names": names, "rows": rows, "per": per, "alt": alt, "post": postc, "baseline": base,
            "top10": sec, "dev": devrows, "judge": judge(P, scen), "judge_pre": judge(Q, scen),
            "evals": evals, "transplant": trans}


def render(a: Mapping[str, Any], meta: Mapping[str, Any] | None = None) -> str:
    j = a["judge"]
    L = ["# 실험 9 결과 — 계정별 5덱 조립 기법 비교", "",
         "`analyze9.py` 생성. 판단은 검증 시나리오 8개의 **후처리 후** 5덱 합. G = 기법 / L0 − 1.", ""]
    if meta:
        L += [f"평가기: {meta.get('evaluator', '—')}", ""]
    L += ["## 판단", "",
          f"**{j['line']}줄 — {j['pick']}.** 「낫다」(중앙 ≥ +0.5% 그리고 G > 0이 {need(len(a['scenarios']))}개 이상) 예산: "
          + " · ".join(f"{m} {j['wins'][m] or '없음'}" for m in METHODS[1:])
          + ". 「못하다」: " + " · ".join(f"{m} {j['loses'][m] or '없음'}" for m in METHODS[1:]) + ".",
          f"후처리 전 값으로 같은 판단: {a['judge_pre']['line']}줄 — {a['judge_pre']['pick']}.", ""]
    if j["small_budget"]:
        L += [f"예산 300에서만 나은 기법: {', '.join(j['small_budget'])}.", ""]
    L += ["## 기법별 G (검증 8개)", "",
          "| 예산 | 기법 | 중앙 | G>0 | G<0 | 최소 | 최대 | 낫다 | 못하다 | 후처리 전 중앙 | 후처리 전 G>0 |",
          "|---:|---|---:|---:|---:|---:|---:|---|---|---:|---:|"]
    for r in a["rows"]:
        L.append(f"| {r['budget']} | {r['method']} | {pct(r['median'], 2)} | {r['pos']}/{r['n']} | {r['neg']}/{r['n']} | "
                 f"{pct(r['min'])} | {pct(r['max'])} | {'예' if r['better'] else ''} | {'예' if r['worse'] else ''} | "
                 f"{pct(r['pre_median'], 2)} | {r['pre_pos']}/{r['n']} |")
    L += ["", f"평가 수 중앙(예산 소진): " + " · ".join(f"{m} {v:.0f}" for m, v in a["evals"].items())
          + f". 랭커 옮기기 평가 중앙: " + " · ".join(f"{m} {v:.0f}" for m, v in a["transplant"].items()) + ".", ""]
    L += ["## 시나리오별 5덱 합 (억, 후처리 후 · 괄호는 전)", "",
          "| 시나리오 | 예산 | " + " | ".join(METHODS) + " |", "|---|---:|" + "---:|" * len(METHODS)]
    for r in a["per"]:
        cells = []
        for m in METHODS:
            v = r[m]
            cells.append("—" if v["post"] is None else f"{v['post']:.1f} ({v['pre']:.1f})")
        L.append(f"| {r['scenario']} {r['name']} | {r['budget']} | " + " | ".join(cells) + " |")
    if a["baseline"]:
        L += ["", "## 실험 5식 기준선 (L0 예산 2,000 실행의 랭커 옮기기)", "",
              "| 시나리오 | 랭커 최선 | 랭커 중앙 | 옮긴 스쿼드 재조립 | 최선 기법 · 2,000 후처리 후 | 랭커 최선 대비 |", "|---|---:|---:|---:|---|---:|"]
        for s, b in a["baseline"].items():
            best_m = max(METHODS, key=lambda m: b["post"].get(m) or 0)
            v = b["post"][best_m]
            L.append(f"| {s} | {b['best']:.1f} | {b['median']:.1f} | {b['repack']:.1f} | {best_m} {v:.1f} | {pct(v / b['best'] - 1)} |")
    L += ["", "## 대안 5덱 (최선 5덱의 덱을 2개 이하만 공유, 후처리 전)", "",
          "| 기법 | 예산 | 최선 대비 중앙 | 공유 니케 중앙 |", "|---|---:|---:|---:|"]
    for m in METHODS:
        for b in BUDGETS:
            xs = [x for x in a["alt"] if x["method"] == m and x["budget"] == b and x["ratio"]]
            if xs:
                L.append(f"| {m} | {b} | {statistics.median(x['ratio'] for x in xs) * 100:.1f}% | "
                         f"{statistics.median(x['shared'] for x in xs):.0f}/25 |")
    L += ["", "## 컨트롤 후처리 (틀별 상위 5 × M3:k2 200평가)", "",
          "| 기법 | 예산 | 이득 중앙 | 이득 최소~최대 | 후처리 평가 중앙 |", "|---|---:|---:|---|---:|"]
    for m in METHODS:
        for b in BUDGETS:
            xs = [x for x in a["post"] if x["method"] == m and x["budget"] == b]
            if xs:
                g = [x["gain"] for x in xs]
                L.append(f"| {m} | {b} | {pct(statistics.median(g), 2)} | {pct(min(g))} ~ {pct(max(g))} | "
                         f"{statistics.median(x['evals'] for x in xs):.0f} |")
    if a["top10"]:
        L += ["", "## 보조 — 틀별 상위 10 후처리 (L0 · 2,000)", "", "| 시나리오 | 상위 5 | 상위 10 | 5덱 같음 |", "|---|---:|---:|---|"]
        for x in a["top10"]:
            L.append(f"| {x['scenario']} | {x['top5']:.2f} | {x['top10']:.2f} | {'예' if x['same'] else '아니오'} |")
    if a["dev"]:
        L += ["", "## 개발 8개 (후처리 전, 참고)", "", "| 예산 | 기법 | 중앙 G | G>0 |", "|---:|---|---:|---:|"]
        for r in a["dev"]:
            L.append(f"| {r['budget']} | {r['method']} | {pct(r['median'], 2)} | {r['pos']}/{r['n']} |")
    if meta:
        L += ["", "## 실행", ""] + [f"- {k}: {v}" for k, v in meta.items() if k != "evaluator"]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--post", type=Path, required=True)
    ap.add_argument("--top10", type=Path, help="틀별 상위 10 후처리 dir(보조)")
    ap.add_argument("--dev-runs", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--meta", type=Path, help="실행 메모 JSON(시뮬 수 등)")
    args = ap.parse_args(argv)
    runs = load_dir(args.runs)
    post = load_dir(args.post, ".top5.post.json")
    top10 = load_dir(args.top10, ".top10.post.json") if args.top10 else None
    dev = load_dir(args.dev_runs) if args.dev_runs else None
    missing = [k for k in runs if k not in post]
    if missing:
        print(f"후처리 없는 실행 {len(missing)}개: {missing[:4]}", file=sys.stderr)
        return 1
    a = analyze(runs, post, top10, dev)
    meta = json.loads(args.meta.read_text(encoding="utf-8")) if args.meta else None
    args.out.write_text(render(a, meta), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(a, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(a["judge"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
