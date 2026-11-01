"""실험 20 분석 — 계정 탐색 판별 품질(P / R) · 비용 · 유력 대안 · 판단 (README §판단 기준).

    python experiments/20_search_robust/analyze20.py     → results.md · run_log/analysis.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run20 as R  # noqa: E402

LOG = R.LOG
KEYS = [p[0] for p in R.PLANS]
COST_RANK = {"C0": 0, "C3": 1, "CL3": 1, "REF": 2}   # C3 · CL3은 같은 비용(계정 탐색 3,000)
Q_MED, Q_MIN = 0.995, 0.98                            # 실험 19 기준 3과 같다
LOW_BEAR = ("t5", "d1", "d2", "d3", "d4")             # 렐릭 베어 없음 · 낮음


def med(xs: Sequence[float]) -> float | None:
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def load(log: Path = LOG) -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for path in sorted(log.glob("plans_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[(r["scenario"], r["plan"])] = r
    return out


def judge(q: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    """q: 판 → 계정별 P / R. 기준 3(중앙 ≥ 99.5% · 최소 ≥ 98%)을 넘는 판 중 가장 싼 것. 같은 비용이면 최소 → 중앙이 높은 쪽,
    그래도 같으면 C3(더 단순). 넘는 판이 없으면 최소가 가장 높은 판을 고르고 「미충족」으로 적는다."""
    ok = [k for k in q if q[k] and med(q[k]) >= Q_MED and min(q[k]) >= Q_MIN]
    pool = ok or list(q)
    if ok:
        low = min(COST_RANK[k] for k in ok)
        pool = [k for k in ok if COST_RANK[k] == low]
    pick = max(pool, key=lambda k: (min(q[k]), med(q[k]), k == "C3"))
    line = (f"계정 탐색 = {pick}(기준 3 충족 판 중 가장 쌈)" if ok else
            f"기준 3을 넘는 판 없음 — 최소가 가장 높은 {pick}")
    return {"eligible": ok, "pick": pick, "met": bool(ok), "line": line}


def analyze() -> dict[str, Any]:
    rows = load()
    sids = sorted({k[0] for k in rows}, key=lambda s: (s[0] != "t", int(s[1:])))
    full = [s for s in sids if all((s, k) in rows for k in KEYS)]
    per: dict[str, Any] = {}
    q: dict[str, list[float]] = {k: [] for k in KEYS}
    q_low: dict[str, list[float]] = {k: [] for k in KEYS}
    for s in full:
        tot = {k: rows[(s, k)]["total"] for k in KEYS}
        Rv = max(tot.values())
        cost = {k: rows[(s, k)]["account_evals"] + rows[(s, k)]["post_evals"] for k in KEYS}
        alt = {k: rows[(s, k)].get("alt") for k in R.ALT_PLANS}
        per[s] = {"total": tot, "R": Rv, "cost": cost, "q": {k: tot[k] / Rv for k in KEYS},
                  "alt": {k: (None if a is None else {"ratio": a["ratio"], "shared": a["shared_nikkes"],
                                                       "pair": a["pair"], "post_evals": a["post_evals"]})
                          for k, a in alt.items()}}
        for k in KEYS:
            q[k].append(tot[k] / Rv)
            if s in LOW_BEAR:
                q_low[k].append(tot[k] / Rv)
    verdict = judge(q) if len(full) == 12 else {"line": f"판단 보류 — 계정 {len(full)}개", "pick": None}
    alt_rate = {k: sum(1 for s in full if (per[s]["alt"][k] or {}).get("ratio", 0) >= R.ALT_RATIO) for k in R.ALT_PLANS}
    summary = {k: {"median": med(q[k]), "min": min(q[k]) if q[k] else None,
                   "low_bear_median": med(q_low[k]), "low_bear_min": min(q_low[k]) if q_low[k] else None,
                   "cost_median": med([per[s]["cost"][k] for s in full])} for k in KEYS}
    alt_summary = {k: {"found": alt_rate[k], "of": len(full),
                       "ratio_median": med([per[s]["alt"][k]["ratio"] for s in full if per[s]["alt"][k]]),
                       "shared_median": med([per[s]["alt"][k]["shared"] for s in full if per[s]["alt"][k]]),
                       "post_evals_median": med([per[s]["alt"][k]["post_evals"] for s in full if per[s]["alt"][k]])}
                   for k in R.ALT_PLANS}
    return {"accounts": full, "per": per, "summary": summary, "alt": alt_summary, "verdict": verdict}


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.2f}%"


def render(a: Mapping[str, Any]) -> str:
    L = ["# 실험 20 결과 표", "", f"판단: **{a['verdict']['line']}**", "",
         "## 판별 P / R(R = 계정마다 네 판 중 최고)", "",
         "| 판 | 중앙 | 최소 | 렐릭 베어 없음 · 낮음 5개 중앙 | 그 최소 | 비용 중앙(평가) |", "|---|---:|---:|---:|---:|---:|"]
    for k, d in a["summary"].items():
        L.append(f"| {k} | {pct(d['median'])} | {pct(d['min'])} | {pct(d['low_bear_median'])} | {pct(d['low_bear_min'])} | "
                 f"{d['cost_median']:,.0f} |")
    L += ["", "## 계정별 5덱 합(억)", "", "| 계정 | " + " | ".join(KEYS) + " |", "|---|" + "---:|" * len(KEYS)]
    for s in a["accounts"]:
        t = a["per"][s]["total"]
        L.append(f"| {s} | " + " | ".join(f"{t[k]:.2f}" for k in KEYS) + " |")
    L += ["", f"## 유력 대안(주력 딜러가 다른 덱 2개 이상 · 최선의 {R.ALT_RATIO:.0%} 이상)", "",
          "| 판 | 유력 대안 있는 계정 | 대안 / 최선 중앙 | 공유 니케 중앙 | 대안 후처리 평가 중앙 |", "|---|---:|---:|---:|---:|"]
    for k, d in a["alt"].items():
        L.append(f"| {k} | {d['found']} / {d['of']} | {pct(d['ratio_median'])} | {d['shared_median']} | {d['post_evals_median']} |")
    L += ["", "| 계정 | " + " | ".join(f"{k} 대안" for k in R.ALT_PLANS) + " |", "|---|" + "---:|" * len(R.ALT_PLANS)]
    for s in a["accounts"]:
        cells = []
        for k in R.ALT_PLANS:
            x = a["per"][s]["alt"][k]
            cells.append("—" if not x else f"{pct(x['ratio'])} · {x['shared']}명 · {'/'.join(x['pair'] or [])}")
        L.append(f"| {s} | " + " | ".join(cells) + " |")
    return "\n".join(L) + "\n"


def main() -> int:
    a = analyze()
    (HERE / "results.md").write_text(render(a), encoding="utf-8")
    (LOG / "analysis.json").write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(a["verdict"]["line"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
