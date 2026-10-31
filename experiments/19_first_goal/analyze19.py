"""실험 19 분석 — 판별 5덱 합 · 비용 · 1차 판단 · 계정별 편성안 (README §판 · §판단 기준).

    python experiments/19_first_goal/analyze19.py     → results.md · plans.md(계정별 최선 · 대안 편성안) · run_log/analysis.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run19 as R  # noqa: E402

LOG = R.LOG
PLAN_KEYS = [p[0] for p in R.PLANS]


def med(xs: Sequence[float]) -> float | None:
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def load(path: Path = LOG / "plans.jsonl") -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[(r["scenario"], r["plan"])] = r
    return out


def judge(g_b1: Sequence[float], g_b0w: Sequence[float], q_ref: Sequence[float], g_i1: Sequence[float],
          g_nc: Sequence[float]) -> dict[str, Any]:
    c = {
        1: med(g_b1) >= 0.003 and sum(1 for g in g_b1 if g >= -0.001) >= 7,
        2: med(g_b0w) >= 0.003,
        3: med(q_ref) >= 0.995 and min(q_ref) >= 0.98,
        4: med(g_i1) >= -0.005 and not any(g < -0.03 for g in g_i1),
        5: med(g_nc) >= -0.003 and not any(g < -0.03 for g in g_nc),
    }
    ok = c[1] and c[2] and c[3]
    line = ("1차 목표의 검증 기준 충족(허수아비 · 측정 범위 안)" if ok else
            "1차 검증 기준 미충족 — 틀린 항목: " + ", ".join(str(k) for k in (1, 2, 3) if not c[k]))
    line += f"; 신캐 뒤 I1 {'통과' if c[4] else '실패'}, 새 큐브 {'통과' if c[5] else '실패'}"
    return {"criteria": c, "passed": ok, "line": line}


def cube_and_ctrl(labels: Sequence[str] | None, squad: Sequence[str], start: str) -> list[dict[str, Any]]:
    labels = list(labels or [])
    out = []
    for who in squad:
        cube = R.CB.cube_of(labels, who, start)
        ctrl = [R.R17.split_label(x)[1] + ":" + R.R17.split_label(x)[2] for x in labels
                if R.R17.split_label(x)[0] == who and R.R17.split_label(x)[1] != "cube"]
        out.append({"nikke": who, "cube": cube, "control": ctrl})
    squad_ops = [R.R17.split_label(x)[1] + ":" + R.R17.split_label(x)[2] for x in labels if x.startswith("squad:")]
    return out + ([{"squad": squad_ops}] if squad_ops else [])


def alternative_for(sid: str, rec: Mapping[str, Any]) -> tuple[float, list]:
    """P 판의 운용 값으로 대안 5덱(최선과 덱 2개 이하 공유) — 시뮬 0."""
    book = R.load_book(sid, *rec["account_run"].split("_")[1:2], int(rec["account_run"].split("_")[2]))
    m = rec["method"]
    post = {}
    d = LOG / "ops" / m
    if d.exists():
        for p in d.glob("*.json"):
            j = json.loads(p.read_text(encoding="utf-8"))
            if j["id"].startswith(f"{sid}|") and j.get("value"):
                post[tuple(j["squad"])] = j["value"] / R.E8
    decks = [(v, tuple(sq)) for v, sq in rec["decks"]]
    return R.R18.alternative(book, post, decks)


def analyze() -> dict[str, Any]:
    rows = load()
    sids = sorted({k[0] for k in rows}, key=lambda s: int(s[1:]))
    accts = {s["id"]: s for s in R.AC.test_scenarios()}
    per, g = {}, {k: [] for k in ("B1", "B0w", "REF", "PI1", "PNC", "B0", "B2")}
    for s in sids:
        tot = {k: rows[(s, k)]["total"] for k in PLAN_KEYS if (s, k) in rows}
        cost = {k: rows[(s, k)]["account_evals"] + rows[(s, k)]["post_evals"] for k in PLAN_KEYS if (s, k) in rows}
        Rv = max(tot.values())
        per[s] = {"total": tot, "cost": cost, "R": Rv, "name": accts[s]["name"]}
        if "P" not in tot:
            continue
        for k in ("B1", "B0w", "B0", "B2"):
            if k in tot:
                g[k].append(tot["P"] / tot[k] - 1)
        g["REF"].append(tot["P"] / Rv)
        for k in ("PI1", "PNC"):
            if k in tot:
                g[k].append(tot[k] / tot["P"] - 1)
    full = all(all((s, k) in rows for k in PLAN_KEYS) for s in sids) and len(sids) == 8
    verdict = judge(g["B1"], g["B0w"], g["REF"], g["PI1"], g["PNC"]) if full else {"line": f"판단 보류 — 계정 {len(sids)}개 · 판 일부 없음"}
    plans = {}
    for s in sids:
        rec = rows.get((s, "P"))
        if not rec:
            continue
        start = accts[s]["start_cube"]
        decks = [{"value": v, "squad": sq, "setting": cube_and_ctrl((rec.get("settings") or {}).get(">".join(sq)), sq, start)}
                 for v, sq in rec["decks"]]
        at, alt = alternative_for(s, rec)
        shared = len({n for _, sq in rec["decks"] for n in sq} & {n for _, sq in alt for n in sq})
        plans[s] = {"total": rec["total"], "decks": decks, "alt_total": at, "alt": [[v, list(sq)] for v, sq in alt],
                    "alt_shared": shared, "cost": per[s]["cost"]["P"]}
    summary = {k: {"median": med(v), "min": min(v) if v else None, "max": max(v) if v else None} for k, v in g.items()}
    cost = {k: med([per[s]["cost"][k] for s in sids if k in per[s]["cost"]]) for k in PLAN_KEYS}
    return {"accounts": sids, "per": per, "gains": g, "summary": summary, "cost_median": cost, "verdict": verdict,
            "plans": plans}


def fp(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:+.2f}%"


def render(a: Mapping[str, Any]) -> str:
    L = ["# 실험 19 결과 표", "", f"판단: **{a['verdict']['line']}**", "", "## 계정별 5덱 합(억)", "",
         "| 계정 | " + " | ".join(PLAN_KEYS) + " | P / R |", "|---|" + "---:|" * (len(PLAN_KEYS) + 1)]
    for s in a["accounts"]:
        t = a["per"][s]["total"]
        cells = [f"{t[k]:.2f}" if k in t else "—" for k in PLAN_KEYS]
        q = t["P"] / a["per"][s]["R"] if "P" in t else None
        L.append(f"| {s} | " + " | ".join(cells) + f" | {'—' if q is None else f'{q * 100:.2f}%'} |")
    L += ["", "| 비교 | 중앙 | 최소 | 최대 |", "|---|---:|---:|---:|"]
    names = {"B1": "P / B1 − 1 (이전 기본)", "B0w": "P / B0w − 1 (조합 4,000 · 고정 운용)", "B0": "P / B0 − 1 (고정 운용)",
             "B2": "P / B2 − 1 (같은 정책 · 컨트롤만)", "REF": "P / R", "PI1": "PI1 / P − 1 (신캐 뒤 I1)", "PNC": "PNC / P − 1 (새 큐브)"}
    for k, d in a["summary"].items():
        if d["median"] is None:
            continue
        f = (lambda x: f"{x * 100:.2f}%") if k == "REF" else fp
        L.append(f"| {names[k]} | {f(d['median'])} | {f(d['min'])} | {f(d['max'])} |")
    L += ["", "| 판 | 비용 중앙(계정 탐색 + 후처리 평가) |", "|---|---:|"]
    for k, c in a["cost_median"].items():
        if c is not None:
            L.append(f"| {k} | {c:,.0f} |")
    L += ["", "## 대안 5덱(관찰 — P 판의 운용 값, 최선과 덱 2개 이하 공유)", "", "| 계정 | 대안 / 최선 | 공유 니케 |", "|---|---:|---:|"]
    for s, p in a["plans"].items():
        L.append(f"| {s} | {p['alt_total'] / p['total'] * 100:.2f}% | {p['alt_shared']}명 |")
    return "\n".join(L) + "\n"


def render_plans(a: Mapping[str, Any]) -> str:
    L = ["# 실험 19 — 계정별 최선 편성안(P 판)", "",
         "각 덱: 배치 순서대로 니케 · 큐브 · 컨트롤(실험 6 선택지 이름, 비어 있으면 기본 레이어), 스쿼드 단위 운용(카메라 · 버충), 180초 시뮬 딜(억).",
         "평가기 nikke-calc-rs `89d2e64`, 허수아비(기본 적), `accumulate`, 기대값, `solo`.", ""]
    for s, p in a["plans"].items():
        L += [f"## {s} — {a['per'][s]['name']}: 5덱 합 {p['total']:.2f}억 (대안 {p['alt_total']:.2f}억, 공유 {p['alt_shared']}명)", ""]
        for i, d in enumerate(p["decks"], 1):
            L.append(f"{i}. **{d['value']:.2f}억** — " + " · ".join(
                f"{x['nikke']}[{x['cube'].replace(' 큐브', '')}{'; ' + ', '.join(x['control']) if x['control'] else ''}]"
                for x in d["setting"] if "nikke" in x) +
                "".join(f" · 스쿼드[{', '.join(x['squad'])}]" for x in d["setting"] if "squad" in x))
        L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    a = analyze()
    (HERE / "results.md").write_text(render(a), encoding="utf-8")
    if a["plans"]:
        (HERE / "plans.md").write_text(render_plans(a), encoding="utf-8")
    (LOG / "analysis.json").write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(a["verdict"]["line"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
