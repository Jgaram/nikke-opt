"""실험 21 분석 — 1차 기준(실험 19의 1 · 2 · 3) + 유력 대안 기준(6) · 계정별 편성안 (README §판단 기준).

    python experiments/21_first_goal_recheck/analyze21.py     → results.md · plans.md · run_log/analysis.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run21 as R  # noqa: E402

LOG = R.LOG
ALT_RATIO = R.R20.ALT_RATIO
ALT_MIN = 6               # 유력 대안이 있어야 하는 계정 수(8개 중) — 실험 20 다듬은 판 11/12 → 두 개까지 허용(사전 등록)


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


def judge(g_b1: Sequence[float], g_b0w: Sequence[float], q: Sequence[float], alt_found: int,
          alt_min: int | None = None) -> dict[str, Any]:
    alt_min = ALT_MIN if alt_min is None else alt_min
    c = {
        1: med(g_b1) >= 0.003 and sum(1 for g in g_b1 if g >= -0.001) >= 7,
        2: med(g_b0w) >= 0.003,
        3: med(q) >= 0.995 and min(q) >= 0.98,
        6: alt_found >= alt_min,
    }
    first = c[1] and c[2] and c[3]
    line = ("1차 검증 기준 충족(허수아비 · 측정 범위 안)" if first else
            "1차 검증 기준 미충족 — 틀린 항목: " + ", ".join(str(k) for k in (1, 2, 3) if not c[k]))
    line += f"; 유력 대안 {'충족' if c[6] else '미충족'}({alt_found}/8, 기준 {alt_min})"
    return {"criteria": c, "first": first, "alt": c[6], "passed": first and c[6], "line": line}


def analyze() -> dict[str, Any]:
    rows = load()
    keys = [p[0] for p in R.plans()]
    sids = sorted({k[0] for k in rows}, key=lambda s: int(s[1:]))
    full = [s for s in sids if all((s, k) in rows for k in keys)]
    per: dict[str, Any] = {}
    g = {"B1": [], "B0w": [], "P0": [], "Q": [], "Q_P0": []}
    found = 0
    for s in full:
        tot = {k: rows[(s, k)]["total"] for k in keys}
        Rv = max(tot.values())
        cost = {k: rows[(s, k)]["account_evals"] + rows[(s, k)]["post_evals"] for k in keys}
        alt = rows[(s, "P")].get("alt") or {}
        per[s] = {"total": tot, "R": Rv, "cost": cost, "alt": alt}
        g["B1"].append(tot["P"] / tot["B1"] - 1)
        g["B0w"].append(tot["P"] / tot["B0w"] - 1)
        g["P0"].append(tot["P"] / tot["P0"] - 1)
        g["Q"].append(tot["P"] / Rv)
        g["Q_P0"].append(tot["P0"] / Rv)
        found += ((alt.get("ratio") or 0) >= ALT_RATIO and alt.get("rebuilt", 0) >= 2 and alt.get("new_leaders", 0) >= 2)
    verdict = (judge(g["B1"], g["B0w"], g["Q"], found) if len(full) == 8 and ALT_MIN is not None
               else {"line": f"판단 보류 — 계정 {len(full)}개"})
    summary = {k: {"median": med(v), "min": min(v) if v else None, "max": max(v) if v else None} for k, v in g.items()}
    cost = {k: med([per[s]["cost"][k] for s in full]) for k in keys}
    alt_cost = med([per[s]["alt"].get("post_evals", 0) for s in full])
    return {"accounts": full, "keys": keys, "per": per, "gains": g, "summary": summary, "cost_median": cost,
            "alt_found": found, "alt_cost_median": alt_cost, "verdict": verdict, "p_run": R.P_RUN}


def pct(x: float | None, sign: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.2f}%" if sign else f"{x * 100:.2f}%"


def render(a: Mapping[str, Any]) -> str:
    keys = a["keys"]
    L = ["# 실험 21 결과 표", "", f"판단: **{a['verdict']['line']}**", "", f"절차의 계정 탐색: `{a['p_run']}`", "",
         "## 계정별 5덱 합(억)", "", "| 계정 | " + " | ".join(keys) + " | P / R | 대안 / 최선 · 공유 |",
         "|---|" + "---:|" * (len(keys) + 2)]
    for s in a["accounts"]:
        t, al = a["per"][s]["total"], a["per"][s]["alt"]
        L.append(f"| {s} | " + " | ".join(f"{t[k]:.2f}" for k in keys) + f" | {pct(t['P'] / a['per'][s]['R'])} | "
                 f"{pct(al.get('ratio'))} · {al.get('shared_nikkes')}명 |")
    names = {"B1": "P / B1 − 1 (이전 기본)", "B0w": "P / B0w − 1 (조합 4,000 · 고정 운용)", "P0": "P / P0 − 1 (실험 19 절차)",
             "Q": "P / R", "Q_P0": "P0 / R (실험 19 절차)"}
    L += ["", "| 비교 | 중앙 | 최소 | 최대 |", "|---|---:|---:|---:|"]
    for k, d in a["summary"].items():
        f = (lambda x: pct(x)) if k.startswith("Q") else (lambda x: pct(x, True))
        L.append(f"| {names[k]} | {f(d['median'])} | {f(d['min'])} | {f(d['max'])} |")
    L += ["", "| 판 | 비용 중앙(계정 탐색 + 후처리 평가) |", "|---|---:|"]
    for k, c in a["cost_median"].items():
        L.append(f"| {k} | {c:,.0f} |")
    L.append(f"| 유력 대안 후처리(따로) | {a['alt_cost_median'] or 0:,.0f} |")
    return "\n".join(L) + "\n"


def deck_line(v: float, sq: Sequence[str], labels: Sequence[str] | None, start: str) -> str:
    cells = []
    for who in sq:
        cube = R.R17.CB.cube_of(labels or [], who, start).replace(" 큐브", "")
        ctrl = [R.R17.split_label(x)[1] + ":" + R.R17.split_label(x)[2] for x in (labels or [])
                if R.R17.split_label(x)[0] == who and R.R17.split_label(x)[1] != "cube"]
        cells.append(f"{who}[{cube}{'; ' + ', '.join(ctrl) if ctrl else ''}]")
    sqo = [R.R17.split_label(x)[1] + ":" + R.R17.split_label(x)[2] for x in (labels or []) if x.startswith("squad:")]
    return f"**{v:.2f}억** — " + " · ".join(cells) + (f" · 스쿼드[{', '.join(sqo)}]" if sqo else "")


def render_plans(a: Mapping[str, Any], rows: Mapping[tuple[str, str], Mapping[str, Any]]) -> str:
    accts = {s["id"]: s for s in R.A21.check_scenarios()}
    L = ["# 실험 21 — 계정별 최선 편성안과 유력 대안(P 판)", "",
         "각 덱: 배치 순서대로 니케[큐브; 컨트롤], 스쿼드 단위 운용, 180초 시뮬 딜(억). 굵은 이름 = 주력 딜러(기본 레이어 딜 1위).",
         "평가기 nikke-calc-rs `89d2e64`, 허수아비(기본 적), `accumulate`, 기대값, `solo`.", ""]
    for s in a["accounts"]:
        r = rows[(s, "P")]
        start = accts[s]["start_cube"]
        al = r.get("alt") or {}
        L += [f"## {s} — {accts[s]['name']}", "", f"### 최선 5덱: {r['total']:.2f}억", ""]
        for i, ((v, sq), ld) in enumerate(zip(r["decks"], r["leaders"]), 1):
            L.append(f"{i}. 주력 {ld} — " + deck_line(v, sq, r["settings"].get(">".join(sq)), start))
        if al.get("decks"):
            L += ["", f"### 유력 대안: {al['total']:.2f}억(최선의 {al['ratio'] * 100:.1f}%, 주력에서 뺀 니케 {' · '.join(al['pair'] or [])}, "
                  f"공유 {al['shared_nikkes']}명)", ""]
            for i, ((v, sq), ld) in enumerate(zip(al["decks"], al["leaders"]), 1):
                L.append(f"{i}. 주력 {ld} — " + deck_line(v, sq, (al.get("settings") or {}).get(">".join(sq)), start))
        L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    a = analyze()
    (HERE / "results.md").write_text(render(a), encoding="utf-8")
    if a["accounts"]:
        (HERE / "plans.md").write_text(render_plans(a, load()), encoding="utf-8")
    (LOG / "analysis.json").write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(a["verdict"]["line"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
