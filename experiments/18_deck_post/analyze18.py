"""실험 18 분석 — 정책 × 기법 5덱 합 · 비용 · 판단 (README §잴 것 · §판단 기준).

    python experiments/18_deck_post/analyze18.py     → results.md · run_log/analysis.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
LOG = HERE / "run_log"
MARGIN, TIE = 0.003, 0.001
METHODS = ("C", "J", "S", "T")
POLICIES = ("PS", "PF", "PF2")
CHEAP = {"C": 0, "T": 1, "J": 2, "S": 3}   # 동률이면 C(싸다), 큐브 기법끼리는 T → J → S


def med(xs: Sequence[float]) -> float | None:
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def load(path: Path = LOG / "policies.jsonl") -> dict[tuple[str, str, str], dict[str, Any]]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[(r["scenario"], r["policy"], r["method"])] = r
    return out


def judge(gain_pf_ps: Mapping[str, float], gain_vs_base: Mapping[str, Mapping[str, float]],
          gain_pf2_pf: Mapping[str, float]) -> dict[str, Any]:
    """gain_pf_ps: 기법 → PF − PS 합 이득 중앙. gain_vs_base: 정책 → 기법 → PS · C 대비 이득 중앙. gain_pf2_pf: 기법 → PF2 − PF."""
    pf_wins = [m for m, g in gain_pf_ps.items() if g >= MARGIN]
    policy = "PF" if len(pf_wins) >= 2 else "PS"
    g = gain_vs_base[policy]
    top = max(g.values())
    tied = [m for m in g if g[m] >= top - TIE]
    method = min(tied, key=lambda m: CHEAP[m])
    cube_small = method == "C" or (g["C"] >= top - TIE)
    out = {"policy": policy, "pf_wins": pf_wins, "method": method, "tied": tied, "cube_small": cube_small}
    alt = gain_pf2_pf.get(method)
    out["use_pf2"] = alt is not None and alt >= MARGIN and policy == "PF"
    line = f"후처리 대상 = {'5덱 고정점(PF)' if policy == 'PF' else '틀별 상위 5(PS)'}, 운용 탐색 = {method}"
    if cube_small and method != "C":
        line += "(C와 0.1%p 안)"
    if cube_small:
        line += " — 5덱 합에서 큐브 몫이 작다"
    line += "; 대안 5덱까지 넣기" if out["use_pf2"] else "; 대안 5덱은 출력용"
    out["line"] = line
    return out


def analyze() -> dict[str, Any]:
    rows = load()
    sids = sorted({k[0] for k in rows})
    base = {s: rows[(s, "PS", "C")]["total"] for s in sids if (s, "PS", "C") in rows}
    table: dict[str, dict[str, Any]] = {}
    gain_vs_base: dict[str, dict[str, float]] = {}
    for p in POLICIES:
        gain_vs_base[p] = {}
        for m in METHODS:
            gs = [rows[(s, p, m)]["total"] / base[s] - 1 for s in sids if (s, p, m) in rows and s in base]
            ev = [rows[(s, p, m)]["evals"] for s in sids if (s, p, m) in rows]
            inn = [rows[(s, p, m)]["in_5deck_processed"] for s in sids if (s, p, m) in rows]
            if gs:
                gain_vs_base[p][m] = med(gs)
                table[f"{p}·{m}"] = {"n": len(gs), "median": med(gs), "min": min(gs), "max": max(gs),
                                     "evals_median": med(ev), "in5_median": med(inn),
                                     "rounds_max": max(rows[(s, p, m)]["rounds"] for s in sids if (s, p, m) in rows)}
    gain_pf_ps = {m: med([rows[(s, "PF", m)]["total"] / rows[(s, "PS", m)]["total"] - 1 for s in sids
                          if (s, "PF", m) in rows and (s, "PS", m) in rows]) for m in METHODS}
    gain_pf2_pf = {m: med([rows[(s, "PF2", m)]["total"] / rows[(s, "PF", m)]["total"] - 1 for s in sids
                           if (s, "PF2", m) in rows and (s, "PF", m) in rows]) for m in METHODS}
    verdict = judge(gain_pf_ps, gain_vs_base, gain_pf2_pf) if len(sids) == 8 else {"line": f"판단 보류 — 시나리오 {len(sids)}개"}
    alt = {}
    for m in METHODS:
        xs = [(rows[(s, "PF2", m)]["alt_total"] / rows[(s, "PF2", m)]["total"],
               len({n for _, sq in rows[(s, "PF2", m)]["decks"] for n in sq} &
                   {n for _, sq in rows[(s, "PF2", m)]["alt_decks"] for n in sq}))
              for s in sids if (s, "PF2", m) in rows and rows[(s, "PF2", m)].get("alt_decks")]
        if xs:
            alt[m] = {"ratio_median": med([x for x, _ in xs]), "shared_median": med([y for _, y in xs])}
    per = {s: {f"{p}·{m}": rows[(s, p, m)]["total"] for p in POLICIES for m in METHODS if (s, p, m) in rows} for s in sids}
    return {"scenarios": sids, "base": base, "table": table, "gain_pf_ps": gain_pf_ps, "gain_pf2_pf": gain_pf2_pf,
            "verdict": verdict, "alt": alt, "per_scenario": per}


def fp(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:+.2f}%"


def render(a: Mapping[str, Any]) -> str:
    L = ["# 실험 18 결과 표", "", f"판단: **{a['verdict']['line']}**", "",
         "## 판별 5덱 합 이득 — 지금 기본(PS · C) 대비, 시나리오 8개", "",
         "| 판 | 중앙 | 최소 | 최대 | 비용 중앙(평가) | 5덱 중 운용 찾은 덱(중앙) | 라운드 최대 |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    for k, t in a["table"].items():
        L.append(f"| {k} | {fp(t['median'])} | {fp(t['min'])} | {fp(t['max'])} | {t['evals_median']:.0f} | "
                 f"{t['in5_median']:.0f} | {t['rounds_max']} |")
    L += ["", "| 기법 | PF − PS 중앙 | PF2 − PF 중앙 |", "|---|---:|---:|"]
    for m in METHODS:
        L.append(f"| {m} | {fp(a['gain_pf_ps'].get(m))} | {fp(a['gain_pf2_pf'].get(m))} |")
    L += ["", "## 시나리오별 5덱 합(억)", "", "| 시나리오 | " + " | ".join(next(iter(a["per_scenario"].values())).keys()) + " |",
          "|---|" + "---:|" * len(next(iter(a["per_scenario"].values())))]
    for s, d in a["per_scenario"].items():
        L.append(f"| {s} | " + " | ".join(f"{v:.2f}" for v in d.values()) + " |")
    L += ["", "## 대안 5덱(PF2, 관찰)", "", "| 기법 | 대안 / 최선 중앙 | 최선과 공유 니케 중앙 |", "|---|---:|---:|"]
    for m, d in a["alt"].items():
        L.append(f"| {m} | {d['ratio_median'] * 100:.2f}% | {d['shared_median']:.0f}명 |")
    return "\n".join(L) + "\n"


def main() -> int:
    a = analyze()
    (HERE / "results.md").write_text(render(a), encoding="utf-8")
    (LOG / "analysis.json").write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(a["verdict"]["line"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
