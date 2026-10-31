"""실험 17 분석 — 큐브 이득 · 5덱 효과 · 기법 비교 · 판단 (README §잴 것 · §판단 기준).

    python experiments/17_cube_control/analyze17.py      → results.md · run_log/analysis.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run17 as R  # noqa: E402

LOG = R.LOG
E8 = R.R16.E8
MARGIN = 0.003     # 0.3%
TIE = 0.001        # 0.1%p
BUDGETS = {"C0": (200, 400), "J": (200, 400), "JT": (200, 400), "SQ": (400,), "REF": (1200,)}
CUBE_METHODS = ("J", "JT", "SQ")
PREF = ("J", "SQ", "JT")   # 동률이면 사전값이 필요 없는 쪽부터


def pct(xs: Sequence[float], q: float) -> float | None:
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def med(xs: Sequence[float]) -> float | None:
    return pct(xs, 0.5)


def ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


# ---------------------------------------------------------------- 구성별 값

def comp_values(cid: str, logdir: Path = LOG / "logs") -> dict[str, Any]:
    """기법 · 예산 → (딜, label). R = 모든 기록의 최고. SQ400 = max(C0200, SQ 이어서 200)."""
    h = R.hname(cid)
    rows = {m: R.read_log(logdir / m / f"{h}.jsonl.gz") for m in BUDGETS if (logdir / m / f"{h}.jsonl.gz").exists()}
    out: dict[str, Any] = {"v": {}, "lab": {}}
    for m, rs in rows.items():
        for b in BUDGETS[m]:
            d, lab = R.best_at(rs, b)
            if m == "SQ":
                c0 = out["v"].get(("C0", 200))
                if c0 is not None and (d is None or c0 > d):
                    d, lab = c0, out["lab"][("C0", 200)]
            out["v"][(m, b)], out["lab"][(m, b)] = d, lab
    allv = [r["total_damage"] for rs in rows.values() for r in rs if r["total_damage"]]
    out["R"] = max(allv) if allv else None
    out["base"] = next((r["total_damage"] for r in rows.get("C0", []) if r["step"] == 0), None)
    return out


def summarize(xs: Sequence[float]) -> dict[str, Any]:
    return {"n": len(xs), "median": med(xs), "p10": pct(xs, 0.1), "p90": pct(xs, 0.9),
            "min": min(xs) if xs else None, "max": max(xs) if xs else None}


def five_deck(best: Mapping[frozenset, tuple[float, tuple]], post: Mapping[tuple, float]) -> float:
    return R.R9.repack_post(best, post)[0]


def judge(G_med: float, F_best: float, q400: Mapping[str, Mapping[str, float]], q200: Mapping[str, Mapping[str, float]]
          ) -> dict[str, Any]:
    """사전 등록 판단. q400 · q200: 기법 → {"median", "p10"}."""
    out: dict[str, Any] = {}
    if G_med < MARGIN and F_best < MARGIN:
        out["case"] = 1
        out["line"] = "큐브 효과 작음(측정 범위 안) — 후처리는 컨트롤만 유지, 큐브는 렐릭 베어 고정"
        return out
    cands = [m for m in CUBE_METHODS if m in q400]
    top = max(q400[m]["median"] for m in cands)
    tied = [m for m in cands if q400[m]["median"] >= top - TIE]
    if len(tied) > 1:
        p = max(q400[m]["p10"] for m in tied)
        tied = [m for m in tied if q400[m]["p10"] >= p - TIE]
    best = next(m for m in PREF if m in tied)
    out.update(case=2, method=best, tied=tied)
    line = f"운용 탐색 기본 = {best} · 400"
    if best in q200:
        drop = q400[best]["median"] - q200[best]["median"]
        out["drop_200"] = drop
        if drop < MARGIN:
            out["budget"] = 200
            line += f" — 예산 200으로 충분(400 대비 −{drop * 100:.2f}%p)"
        else:
            out["budget"] = 400
            line += f" — 예산 400 필요(200은 −{drop * 100:.2f}%p)"
    else:
        out["budget"] = 400
    if "JT" in q200 and "J" in q200:
        gap = q200["JT"]["median"] - q200["J"]["median"]
        out["prior_gap_200"] = gap
        out["prior_helps"] = gap >= MARGIN
        if gap >= MARGIN:
            line += f"; 사전값이 작은 예산에서 돕는다(JT200 − J200 = +{gap * 100:.2f}%p)"
    out["line"] = line
    return out


def analyze() -> dict[str, Any]:
    targets = json.loads((LOG / "targets.json").read_text(encoding="utf-8"))
    sids = list(targets["scenarios"])
    runs = R.R16.load_runs(wanted=[targets["scenarios"][s]["run"] for s in sids])
    rows, per_scn = [], {}
    cube_pick: dict[str, Counter] = defaultdict(Counter)
    cube_kind = Counter()
    ctrl_changed = []
    for sid in sids:
        t = targets["scenarios"][sid]
        best = R.R9.book_of(runs[t["run"]])
        vals_by: dict[str, dict[tuple, float]] = defaultdict(dict)
        bs, js = [], []
        for c in t["comps"]:
            cv = comp_values(c["id"])
            if cv["R"] is None or ("C0", 400) not in cv["v"]:
                continue
            sq = tuple(c["squad"])
            row = {"id": c["id"], "scenario": sid, "B": c["B"], "R": cv["R"], "ref": c["ref"]}
            for (m, b), d in cv["v"].items():
                if d is not None:
                    row[f"{m}{b}"] = d
                    vals_by[f"{m}{b}"][sq] = d / E8
            cube_best = [cv["v"].get((m, 400)) for m in CUBE_METHODS if cv["v"].get((m, 400))]
            if cube_best:
                row["G"] = max(cube_best) / cv["v"][("C0", 400)] - 1
            # 고른 큐브 · 컨트롤(가장 좋은 큐브 기법 400의 최선)
            mbest = max((m for m in CUBE_METHODS if cv["v"].get((m, 400))), key=lambda m: cv["v"][(m, 400)], default=None)
            if mbest:
                lab = cv["lab"][(mbest, 400)]
                for who in c["squad"]:
                    k = R.CB.cube_of(lab, who)
                    cube_pick[who][k] += 1
                    cube_kind[k] += 1
                ctrl = sorted(x for x in lab if R.split_label(x)[1] != "cube")
                ctrl_changed.append(ctrl != sorted(cv["lab"][("C0", 400)]))
            bs.append(c["B"])
            js.append(cv["R"])
            rows.append(row)
        five = {"current": five_deck(best, vals_by.get("C0200", {}))}
        for key in ("C0400", "J400", "JT400", "SQ400", "J200", "JT200"):
            if key in vals_by:
                five[key] = five_deck(best, vals_by[key])
        per_scn[sid] = {"five": five, "spearman_B_R": spearman(bs, js), "n": len(bs)}
    # 기법 품질
    q: dict[str, dict[str, Any]] = {}
    for key in ("C0200", "C0400", "J200", "J400", "JT200", "JT400", "SQ400", "REF1200"):
        xs = [r[key] / r["R"] for r in rows if key in r]
        if xs:
            q[key] = summarize(xs)
    G = [r["G"] for r in rows if "G" in r]
    F = {}
    for key in ("C0400", "J400", "JT400", "SQ400", "J200", "JT200"):
        xs = [d["five"][key] / d["five"]["current"] - 1 for d in per_scn.values() if key in d["five"]]
        if xs:
            F[key] = summarize(xs)
    F_best = max((F[k]["median"] for k in ("J400", "JT400", "SQ400") if k in F), default=0.0)
    q400 = {m: q[f"{m}400"] for m in CUBE_METHODS if f"{m}400" in q}
    q200 = {m: q[f"{m}200"] for m in ("J", "JT") if f"{m}200" in q}
    verdict = judge(med(G) or 0.0, F_best, q400, q200) if q400 else {"line": "판단 보류 — 큐브 기법 결과 없음"}
    modal = {w: (c.most_common(1)[0][0], c.most_common(1)[0][1] / sum(c.values()), sum(c.values()))
             for w, c in cube_pick.items()}
    return {"n": len(rows), "G": summarize(G), "q": q, "F": F, "per_scenario": per_scn, "verdict": verdict,
            "cube_kind": dict(cube_kind.most_common()), "modal": modal,
            "ctrl_changed": sum(ctrl_changed) / len(ctrl_changed) if ctrl_changed else None,
            "rows": rows}


def fp(x: float | None, d: int = 2, sign: bool = True) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def render(a: Mapping[str, Any]) -> str:
    L = ["# 실험 17 결과 표", "", f"구성 {a['n']}개. 판단: **{a['verdict']['line']}**", "",
         "## 큐브 이득 G = max(J400, JT400, SQ400) / C0400 − 1", "",
         "| 중앙 | 10백분위 | 90백분위 | 최대 |", "|---:|---:|---:|---:|"]
    g = a["G"]
    L.append(f"| {fp(g['median'])} | {fp(g['p10'])} | {fp(g['p90'])} | {fp(g['max'])} |")
    L += ["", "## 기법 품질 q = 값 / R(구성마다 어느 기법이든 찾은 최고)", "",
          "| 기법 · 예산 | n | 중앙 | 10백분위 | 최소 |", "|---|---:|---:|---:|---:|"]
    for k, s in a["q"].items():
        L.append(f"| {k} | {s['n']} | {fp(s['median'], 2, False)} | {fp(s['p10'], 2, False)} | {fp(s['min'], 2, False)} |")
    L += ["", "## 5덱 효과 — 지금 기본(C0200 후처리) 대비, 시나리오 8개", "",
          "| 판 | 중앙 | 최소 | 최대 |", "|---|---:|---:|---:|"]
    for k, s in a["F"].items():
        L.append(f"| {k} | {fp(s['median'])} | {fp(s['min'])} | {fp(s['max'])} |")
    L += ["", "| 시나리오 | 지금 기본 5덱(억) | C0400 | J400 | JT400 | SQ400 | S0 안 Spearman(B, R) |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for sid, d in a["per_scenario"].items():
        f = d["five"]
        cells = [fp(f[k] / f["current"] - 1) if k in f else "—" for k in ("C0400", "J400", "JT400", "SQ400")]
        sp = "—" if d["spearman_B_R"] is None else f"{d['spearman_B_R']:.2f}"
        L.append(f"| {sid} | {f['current']:.2f} | " + " | ".join(cells) + f" | {sp} |")
    L += ["", "## 관찰(판단에 쓰지 않음)", "",
          f"- 큐브를 함께 찾은 최선의 컨트롤이 C0400 최선과 다른 구성: {fp(a['ctrl_changed'], 0, False)}",
          "- 고른 큐브(가장 좋은 큐브 기법 400의 최선, 니케 자리 수): " +
          ", ".join(f"{k} {v}" for k, v in a["cube_kind"].items()),
          "- 니케별 최빈 큐브(5자리 이상 나온 니케, 최빈 비율 낮은 순):"]
    for w, (c, share, n) in sorted(a["modal"].items(), key=lambda t: t[1][1]):
        if n >= 5:
            L.append(f"  - {w}: {c} {share * 100:.0f}% ({n}자리)")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    a = analyze()
    (HERE / "results.md").write_text(render(a), encoding="utf-8")
    slim = {k: v for k, v in a.items() if k != "rows"}
    slim["modal"] = {w: list(v) for w, v in a["modal"].items()}
    (LOG / "analysis.json").write_text(json.dumps(slim, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(a["verdict"]["line"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
