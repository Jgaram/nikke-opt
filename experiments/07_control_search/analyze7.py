"""실험 7 분석 — 예산별 최선 / 상한 참조, 사전 등록한 판단 기준 (README §잴 것 · §판단 기준).

    python experiments/07_control_search/analyze7.py --runs <dir>... [--ref <exp6 Record jsonl>...] \
        [--exp6-reference] --comps dev|val --out <md> [--json <json>]

- 기법 기록: methods.py `run`의 `<comp>__<method>.jsonl`(step = 그 실행의 평가 순번).
- 상한 참조 U(조합) = 그 조합의 모든 기록(기법 · 상한 참조 실행 · 개발이면 실험 6 기록) 중 최대 총딜.
- r(기법, 예산 b, 조합) = 그 실행의 step < b 기록 중 최대 총딜 / U. 실행이 b 전에 끝났으면 끝까지의 최선.
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP6_RECORDS = HERE.parent / "06_control_menu" / "run_log" / "main.jsonl.gz"
BUDGETS = (100, 200, 400, 800)
REACH = 0.995        # 판단 기준: 상한의 99.5%
DECIDE_BUDGET = 400  # 판단 기준: 이 예산 안에
LEARN_MARGIN = 0.001  # 학습 기법이 M3보다 「낫다」: 400평가 중앙이 0.1%p 이상 높고
LEARN_WINS = 9        # 16개 중 이 수 이상에서 높다(동률 제외 아님 — 엄격히 높은 조합 수)
SIMPLE_ORDER = ("M0", "M3", "M1", "M2")  # 같은 예산에서 닿으면 앞의 것(계산 부담이 작은 순)


def _open(p: Path):
    return gzip.open(p, "rt", encoding="utf-8") if str(p).endswith(".gz") else open(p, encoding="utf-8")


def read_jsonl(p: Path) -> Iterable[dict[str, Any]]:
    with _open(p) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_runs(dirs: Sequence[Path]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    runs: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for d in dirs:
        for p in sorted(d.glob("*.jsonl")):
            recs = list(read_jsonl(p))
            if recs:
                runs[(recs[0]["comp_id"], recs[0]["method"])] = recs
    return runs


def done_info(dirs: Sequence[Path]) -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for d in dirs:
        for p in sorted(d.glob("*.done")):
            s = json.loads(p.read_text(encoding="utf-8"))
            out[(s["comp_id"], s["method"])] = s
    return out


def best_at(recs: Sequence[Mapping[str, Any]], b: int) -> int | None:
    vals = [r["total_damage"] for r in recs if r["step"] < b and r["total_damage"] is not None]
    return max(vals) if vals else None


def first_reach(recs: Sequence[Mapping[str, Any]], target: float) -> int | None:
    best = None
    for r in sorted(recs, key=lambda r: r["step"]):
        d = r["total_damage"]
        if d is not None and (best is None or d > best):
            best = d
        if best is not None and best >= target:
            return r["step"] + 1
    return None


def family(method: str) -> str:
    return method.split(":", 1)[0]


def quantile(xs: Sequence[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def summarize(runs, upper_extra: Mapping[str, int], comp_ids: Sequence[str]) -> dict[str, Any]:
    by_comp: dict[str, dict[str, list]] = defaultdict(dict)
    for (cid, m), recs in runs.items():
        by_comp[cid][m] = recs
    U: dict[str, int] = {}
    layer: dict[str, int] = {}
    for cid in comp_ids:
        vals = [r["total_damage"] for recs in by_comp[cid].values() for r in recs if r["total_damage"] is not None]
        if cid in upper_extra:
            vals.append(upper_extra[cid])
        U[cid] = max(vals) if vals else None
        for recs in by_comp[cid].values():
            for r in recs:
                if not r["variants"] and r["total_damage"] is not None:
                    layer[cid] = r["total_damage"]
    methods = sorted({m for (_, m) in runs}, key=lambda m: (SIMPLE_ORDER.index(family(m)), m))
    table: dict[str, dict[int, dict[str, Any]]] = {}
    ratios: dict[str, dict[int, dict[str, float]]] = {}
    for m in methods:
        table[m], ratios[m] = {}, {}
        for b in BUDGETS:
            rs = {}
            for cid in comp_ids:
                recs = by_comp[cid].get(m)
                if recs is None or U[cid] is None:
                    continue
                v = best_at(recs, b)
                rs[cid] = (v / U[cid]) if v is not None else 0.0
            ratios[m][b] = rs
            xs = list(rs.values())
            table[m][b] = {"n": len(xs), "median": statistics.median(xs) if xs else None,
                           "q1": quantile(xs, 0.25) if xs else None, "min": min(xs) if xs else None,
                           "reach": sum(1 for x in xs if x >= REACH)}
    evals = {m: {cid: len(by_comp[cid][m]) for cid in comp_ids if m in by_comp[cid]} for m in methods}
    reach_step = {m: {cid: first_reach(by_comp[cid][m], REACH * U[cid]) for cid in comp_ids
                      if m in by_comp[cid] and U[cid]} for m in methods}
    return {"U": U, "layer": layer, "methods": methods, "table": table, "ratios": ratios, "evals": evals,
            "reach_step": reach_step, "comp_ids": list(comp_ids)}


def decide(s: Mapping[str, Any]) -> dict[str, Any]:
    """README §판단 기준(사전 등록) 적용."""
    table, ratios = s["table"], s["ratios"]
    notes = []
    reached = []  # (예산, 단순 순서, 기법)
    for m in s["methods"]:
        for b in BUDGETS:
            med = table[m][b]["median"]
            if med is not None and med >= REACH:
                reached.append((b, SIMPLE_ORDER.index(family(m)), m))
                break
    reached.sort()
    m3s = [m for m in s["methods"] if family(m) == "M3"]

    def better_than_m3(m: str) -> bool:
        if not m3s:
            return True
        best_m3 = max(m3s, key=lambda x: table[x][DECIDE_BUDGET]["median"] or 0)
        a, c = ratios[m][DECIDE_BUDGET], ratios[best_m3][DECIDE_BUDGET]
        wins = sum(1 for cid in a if cid in c and a[cid] > c[cid])
        med_gap = (table[m][DECIDE_BUDGET]["median"] or 0) - (table[best_m3][DECIDE_BUDGET]["median"] or 0)
        notes.append(f"{m} vs {best_m3} @ {DECIDE_BUDGET}: 중앙 차 {med_gap * 100:+.2f}%p, 높은 조합 {wins}/{len(a)}")
        return med_gap >= LEARN_MARGIN and wins >= LEARN_WINS

    within = [x for x in reached if x[0] <= DECIDE_BUDGET]
    if within:
        b, _, m = within[0]
        if family(m) in ("M1", "M2") and not better_than_m3(m):
            m3_within = [x for x in within if family(x[2]) == "M3"]
            if m3_within:
                notes.append(f"{m}가 M3보다 낫지 않다 — M3를 쓴다")
                b, _, m = m3_within[0]
        return {"line": 1, "method": m, "budget": b, "reached": reached, "notes": notes,
                "text": f"{m}가 {b}평가에 검증 중앙 {REACH:.1%} 도달 — 채택"}
    if reached:
        b, _, m = reached[0]
        return {"line": 2, "method": m, "budget": b, "reached": reached, "notes": notes,
                "text": f"{DECIDE_BUDGET}평가 안에는 없음, {m}가 {b}평가에 도달 — 부분 도달"}
    return {"line": 3, "method": None, "budget": None, "reached": [], "notes": notes,
            "text": "800평가 안에 닿는 기법 없음 — 선택지 공간을 줄이는 방향을 다음 질문으로"}


def _p(x: float | None, nd: int = 2) -> str:
    return "—" if x is None else f"{x * 100:.{nd}f}%"


def render(s: Mapping[str, Any], dec: Mapping[str, Any] | None, title: str, info: Mapping[str, Any]) -> str:
    L = [f"# {title}", "", "`analyze7.py`가 만든다. 정의는 [README §잴 것](README.md#잴-것).", ""]
    for k, v in info.items():
        L.append(f"- {k}: {v}")
    L += ["", "## 예산별 최선 / 상한 참조 (조합 중앙 · 1사분위 · 최소 · 99.5% 도달 수)", "",
          "| 기법 | " + " | ".join(f"{b}평가" for b in BUDGETS) + " | 평가 수 중앙 |",
          "|---|" + "---|" * len(BUDGETS) + "---:|"]
    for m in s["methods"]:
        cells = []
        for b in BUDGETS:
            t = s["table"][m][b]
            cells.append(f"{_p(t['median'])} · {_p(t['q1'])} · {_p(t['min'])} · {t['reach']}/{t['n']}")
        ev = list(s["evals"][m].values())
        L.append(f"| {m} | " + " | ".join(cells) + f" | {statistics.median(ev):.0f} |")
    L += ["", "## 조합별 (400평가 최선 / U − 1, U는 기본 레이어 대비)", ""]
    ms = s["methods"]
    L.append("| 조합 | U / 기본 레이어 − 1 | " + " | ".join(ms) + " |")
    L.append("|---|---:|" + "---:|" * len(ms))
    for cid in s["comp_ids"]:
        u, lay = s["U"][cid], s["layer"].get(cid)
        row = [f"{(u / lay - 1) * 100:+.2f}%" if u and lay else "—"]
        for m in ms:
            r = s["ratios"][m][DECIDE_BUDGET].get(cid)
            row.append("—" if r is None else f"{(r - 1) * 100:+.2f}%")
        L.append(f"| {cid} | " + " | ".join(row) + " |")
    L += ["", "## 99.5%에 처음 닿은 평가 수 (닿지 못하면 —)", "",
          "| 조합 | " + " | ".join(ms) + " |", "|---|" + "---:|" * len(ms)]
    for cid in s["comp_ids"]:
        L.append(f"| {cid} | " + " | ".join("—" if s["reach_step"][m].get(cid) is None else str(s["reach_step"][m][cid])
                                            for m in ms) + " |")
    if dec:
        L += ["", "## 판단 (사전 등록 기준)", "", f"- **{dec['text']}** (줄 {dec['line']})"]
        for n in dec["notes"]:
            L.append(f"- {n}")
        L.append(f"- 중앙 {REACH:.1%}에 처음 닿은 (예산, 기법): "
                 + (", ".join(f"{m} {b}" for b, _, m in dec["reached"]) or "없음"))
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=Path, nargs="+", required=True)
    ap.add_argument("--ref", type=Path, nargs="*", default=[], help="상한 참조 실행 기록(실험 6 Record 형식)")
    ap.add_argument("--exp6-reference", action="store_true", help="실험 6 기록(바탕 layer)을 U에 넣는다(개발)")
    ap.add_argument("--comps", required=True, help="조합 id 콤마 목록")
    ap.add_argument("--title", default="실험 7 결과")
    ap.add_argument("--decide", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    comp_ids = args.comps.split(",")
    runs = load_runs(args.runs)
    upper: dict[str, int] = {}
    srcs = list(args.ref) + ([EXP6_RECORDS] if args.exp6_reference else [])
    for p in srcs:
        for r in read_jsonl(p):
            if r.get("total_damage") is None or r.get("condition") in ("auto", "search_from_auto", "fixed_layer"):
                continue
            upper[r["comp_id"]] = max(upper.get(r["comp_id"], 0), r["total_damage"])
    s = summarize(runs, upper, comp_ids)
    dec = decide(s) if args.decide else None
    done = done_info(args.runs)
    info = {"조합": len(comp_ids), "기법 실행": len(runs),
            "새 시뮬(기록의 cached=false)": sum(1 for recs in runs.values() for r in recs if r.get("cached") is False),
            "실험 6 기록 재사용": sum(1 for recs in runs.values() for r in recs if r.get("cached") == "lookup"),
            "상한 참조 실행 기록": ", ".join(str(p) for p in args.ref) or "없음",
            "기법 실행 시간 합(초)": round(sum(d.get("seconds", 0) for d in done.values()))}
    args.out.write_text(render(s, dec, args.title, info), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps({"summary": s, "decision": dec}, ensure_ascii=False, indent=1, default=str),
                             encoding="utf-8")
    print(args.out.read_text(encoding="utf-8")[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
