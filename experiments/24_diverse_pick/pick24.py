"""실험 24 — 고르기 시험: 탐색 기록만으로(시뮬 0) 최선과 묶는 방식이 다른 5덱을 고르면 5덱 합이 얼마나 떨어지는가.

    python experiments/24_diverse_pick/pick24.py            → results.md · analysis.json (사례당 수 분, 4프로세스)
    python experiments/24_diverse_pick/pick24.py --report   → analysis.json에서 표만 다시

- 기록: 실험 20 개발 계정 12개의 계정 탐색(U4 · 3,000, C3 판) · 실험 22 사전 계산(시즌 × 보스, 15,000평가).
  값은 기록 그대로의 기본 레이어 180초 딜(억)이다. 큐브 · 컨트롤 후처리는 하지 않는다.
- 최선 = 기록에서 겹치지 않는 5덱 합 최대(`run9.pack_vals`). 대안(θ) = 최선과의 쌍 자카드 J ≤ θ인 5덱 중 합 최대.
  5명 덱 5개끼리는 J = S / (100 − S)(S = 공유 쌍)이고, S는 덱별 공유 쌍의 합이라 `pack_vals(cost, budget)`로 정확히 푼다.
- 참고: 기존 규칙(최선과 같은 덱 2개 이하, 실험 9 `MAX_SHARE`)으로 고른 대안.
- 이웃 수: 기록 안에서 그 덱과 4명 이상 같은 다른 구성의 수. 탐색이 그 덱 근처를 얼마나 돌았는지 본다(관찰).
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import math
import statistics
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
EXP = HERE.parent
ACC20 = EXP / "20_search_robust" / "run_log" / "accounts"
LOG22 = EXP / "22_ranker_check" / "run_log"
RUN20 = "U4_3000"                         # 실험 20 C3 판의 계정 탐색
THETAS = (0.5, 0.4, 0.3, 0.2, 0.1, 0.0)
MAIN_THETA = 0.2                          # README §해석 기준(사전 등록)
GOOD, BAD = 0.97, 0.95
E8 = 1e8
LIMIT = 60.0                              # 정확해 제한 시간(초) — 넘으면 하한 · 상한 구간(README §절차 3)
MU_MAX, MU_STEPS = 20.0, 16               # 승수 상한: [0, MU_MAX]에서 황금 분할 탐색(상한이 μ에 대해 볼록)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SIM = sys.modules.get("nikke_opt.similarity") or _load("nikke_opt.similarity", ROOT / "nikke_opt" / "similarity.py")
R9 = sys.modules.get("run9") or _load("run9", EXP / "09_account_pack" / "run9.py")


def budget_of(theta: float) -> int:
    """J ≤ θ ⇔ 공유 쌍 S ≤ 100θ / (1 + θ) (5명 덱 5개끼리)."""
    return math.floor(100 * theta / (1 + theta) + 1e-9)


def book_of(path: Path) -> dict[frozenset, tuple[float, tuple]]:
    """평가 기록 → 구성마다 최선 (딜(억), 순서). 실험 4 `Book.add`와 같다."""
    best: dict[frozenset, tuple[float, tuple]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("total_damage") is None:
                continue
            sq, v = tuple(r["squad"]), r["total_damage"] / E8
            c = frozenset(sq)
            if c not in best or v > best[c][0]:
                best[c] = (v, sq)
    return best


def pair_cost(book: Mapping[frozenset, Any], best: Sequence[frozenset]) -> dict[frozenset, int]:
    """구성마다 최선 5덱과 공유하는 쌍 수 = Σ C(최선 덱과 같은 니케 수, 2)."""
    return {c: sum(math.comb(len(c & b), 2) for b in best) for c in book}


def neighbors(book: Mapping[frozenset, Any], deck: frozenset) -> int:
    return sum(1 for c in book if c != deck and len(c & deck) >= 4)


def multiplier_bound(book: Mapping[frozenset, tuple[float, tuple]], cost: Mapping[frozenset, int], budget: int
                     ) -> tuple[float, tuple[float, list] | None]:
    """승수 완화 상한 min_μ≥0 [max Σ(v − μ·비용) + μ·예산]과, 도중에 나온 예산 안 해 중 최선(값, 덱) — 하한 후보."""
    vals = {c: x for c, x in book.items() if cost[c] <= budget}
    feas: list[tuple[float, list]] = []

    def ub(mu: float) -> float:
        u, d = R9.pack_vals({c: (v - mu * cost[c], sq) for c, (v, sq) in vals.items()})
        if not d:
            return float("inf")
        if sum(cost[frozenset(q)] for _, q in d) <= budget:
            feas.append((sum(vals[frozenset(q)][0] for _, q in d), [(vals[frozenset(q)][0], q) for _, q in d]))
        return u + mu * budget

    g = (math.sqrt(5) - 1) / 2
    lo, hi = 0.0, MU_MAX
    a, b = hi - g * (hi - lo), lo + g * (hi - lo)
    fa, fb = ub(a), ub(b)
    best = min(ub(lo), ub(hi), fa, fb)
    for _ in range(MU_STEPS):
        if fa <= fb:
            hi, b, fb = b, a, fa
            a = hi - g * (hi - lo)
            fa = ub(a)
        else:
            lo, a, fa = a, b, fb
            b = lo + g * (hi - lo)
            fb = ub(b)
        best = min(best, fa, fb)
    return best, max(feas, key=lambda t: t[0]) if feas else None


def constrained(book: Mapping[frozenset, tuple[float, tuple]], cost: Mapping[frozenset, int], budget: int
                ) -> dict[str, Any]:
    """J 상한 묶기: 제한 시간 안이면 정확해, 아니면 하한(찾은 최선 · 승수 탐색 중 예산 안 해) · 상한(승수 완화)."""
    t0 = time.monotonic()
    try:
        t, d = R9.pack_vals(book, cost=cost, budget=budget, deadline=t0 + LIMIT)
        return {"total": t, "decks": d, "exact": True, "upper": t, "seconds": round(time.monotonic() - t0, 1)}
    except R9.PackTimeout as e:
        t, d = e.total, e.decks
    up, feas = multiplier_bound(book, cost, budget)
    if feas and feas[0] > t:
        t, d = feas
    return {"total": t, "decks": d, "exact": False, "upper": max(up, t), "seconds": round(time.monotonic() - t0, 1)}


def pick(book: Mapping[frozenset, tuple[float, tuple]]) -> dict[str, Any]:
    tot, best = R9.pack_vals(book)
    bd = [frozenset(q) for _, q in best]
    bplan = [list(q) for _, q in best]
    cost = pair_cost(book, bd)
    out: dict[str, Any] = {"records": len(book), "best_total": tot, "best": [[v, list(q)] for v, q in best],
                           "best_neighbors": [neighbors(book, d) for d in bd]}

    def row(t: float, d: Sequence[tuple[float, tuple]], **extra: Any) -> dict[str, Any]:
        if not d:
            return {"found": False, **extra}
        plan = [list(q) for _, q in d]
        new = [frozenset(q) for q in plan if frozenset(q) not in set(bd)]
        return {"found": True, "total": t, "ratio": t / tot, **SIM.compare(bplan, plan),
                "same_decks": 5 - len(new), "neighbors": [neighbors(book, c) for c in new],
                "decks": [[v, list(q)] for v, q in d], **extra}

    t, d = R9.pack_vals(book, avoid=[set(bd)], max_share=R9.MAX_SHARE)
    out["rule"] = row(t, d)
    out["thetas"] = {}
    for th in THETAS:
        b = budget_of(th)
        c = constrained(book, cost, b)
        out["thetas"][str(th)] = row(c["total"], c["decks"], budget=b, candidates=sum(1 for x in cost.values() if x <= b),
                                     exact=c["exact"], upper=c["upper"], upper_ratio=c["upper"] / tot, seconds=c["seconds"])
    return out


def cases() -> list[tuple[str, str, Path]]:
    out = [("exp20", p.name.split("_")[0], p) for p in sorted(ACC20.glob(f"*_{RUN20}.jsonl.gz"))]
    out += [("exp22", p.name[len("precompute_"):-len(".jsonl.gz")], p) for p in sorted(LOG22.glob("precompute_S*.jsonl.gz"))]
    return out


def check_best(group: str, name: str, res: Mapping[str, Any]) -> float | None:
    """기록으로 다시 짠 최선과 실험이 남긴 최선 5덱 합의 차(확인용)."""
    if group == "exp20":
        s = json.loads((ACC20 / f"{name}_{RUN20}.json").read_text(encoding="utf-8"))
    else:
        s = json.loads((LOG22 / f"precompute_{name}.json").read_text(encoding="utf-8"))
    return res["best_total"] - s["final"]["total"]


GROUPS = {"exp20": "실험 20 개발 계정 12개(계정 탐색 3,000)", "exp22": "실험 22 사전 계산(시즌 풀, 15,000)"}


def verdict_of(ratios: Sequence[float | None]) -> str:
    """README §해석 기준(θ = MAIN_THETA의 기록별 값 비율, None = 대안 없음)."""
    rs = [r for r in ratios if r is not None]
    if len(rs) < len(ratios) or not rs:
        return "탐색 보강 필요"
    med = statistics.median(rs)
    if med >= GOOD and sum(r >= GOOD for r in rs) * 4 >= 3 * len(rs):
        return "고르기로 충분"
    if med < BAD:
        return "탐색 보강 필요"
    return "일부"


def summarize(rows: Sequence[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for g in GROUPS:
        xs = [r for r in rows if r["group"] == g]
        if not xs:
            continue
        per: dict[str, Any] = {}
        for th in ["rule"] + [str(t) for t in THETAS]:
            ys = [r["rule"] if th == "rule" else r["thetas"][th] for r in xs]
            ok = [y for y in ys if y["found"]]
            rs = [y["ratio"] for y in ok]
            per[th] = {"n": len(ys), "found": len(ok), "ratio_median": statistics.median(rs) if rs else None,
                       "ratio_min": min(rs) if rs else None, "ratio_max": max(rs) if rs else None,
                       "good": sum(r >= GOOD for r in rs),
                       "j_median": statistics.median([y["pair_jaccard"] for y in ok]) if ok else None,
                       "moves_median": statistics.median([y["moves"] for y in ok]) if ok else None,
                       "shared_median": statistics.median([y["shared_nikkes"] for y in ok]) if ok else None,
                       "neighbors_median": statistics.median([n for y in ok for n in y["neighbors"]] or [0]) if ok else None}
            if th != "rule":
                loose = [y for y in ys if not y["exact"]]          # 못 찾은 기록도 센다(그때 상한은 해가 있다면의 최대)
                us = [y["upper_ratio"] for y in loose]
                per[th].update(inexact=len(loose), upper_median=statistics.median(us) if us else None,
                               upper_max=max(us) if us else None, upper_good=sum(u >= GOOD for u in us))
        ys = [r["thetas"][str(MAIN_THETA)] for r in xs]
        lo = verdict_of([y["ratio"] if y["found"] else None for y in ys])
        hi = verdict_of([y["upper_ratio"] if y["found"] else None for y in ys])
        verdict = lo if lo == hi else f"구간 때문에 보류(하한으로 {lo} · 상한으로 {hi})"
        out[g] = {"per": per, "verdict": verdict, "verdict_lower": lo, "verdict_upper": hi,
                  "best_neighbors_median": statistics.median([n for r in xs for n in r["best_neighbors"]])}
    return out


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def f2(x: float | None) -> str:
    return "—" if x is None else f"{x:.2f}"


def num(x: float | None) -> str:
    return "—" if x is None else f"{x:g}"


def interval(v: Mapping[str, Any]) -> str:
    if "inexact" not in v:
        return "—"
    if not v["inexact"]:
        return "0"
    return f"{v['inexact']} · {pct(v['upper_median'])} · {v['upper_good']}/{v['inexact']}"


def cell(y: Mapping[str, Any]) -> str:
    if not y["found"]:
        return "없음" if y["exact"] else f"없음(있어도 ≤ {pct(y['upper_ratio'])})"
    return pct(y["ratio"]) if y["exact"] else f"{pct(y['ratio'])} ~ {pct(y['upper_ratio'])}"


def report(a: Mapping[str, Any]) -> str:
    L = ["# 실험 24 결과 — 고르기 시험", "",
         "`python experiments/24_diverse_pick/pick24.py`가 만든다. 시뮬 0회. 절차 · 해석 기준은 [README](README.md).", "",
         "- 값 비율 = 대안 5덱 합 ÷ 최선 5덱 합(같은 기록 · 기본 레이어, 후처리 전). J · 바꿀 · 공유는 [실험 23](../23_deck_similarity/README.md#지표) 정의.",
         "- 이웃 수 = 기록 안에서 그 덱과 4명 이상 같은 다른 구성 수(대안 덱 중 최선에 없는 덱의 중앙). 최선 덱의 이웃 수 중앙은 표 아래에 적는다.", ""]
    for g, s in a["summary"].items():
        L += [f"## {GROUPS[g]}", "", f"**해석(θ = {MAIN_THETA}, 사전 등록): {s['verdict']}**", "",
              "- 값 비율은 찾은 해(하한)다. 제한 시간 안에 최적을 증명하지 못한 기록은 「구간」 칸에 수와 상한 중앙을 적는다.", "",
              "- 「없음」은 예산 안 5덱이 없음을 증명한 것, 「없음(있어도 ≤ x)」은 시간 안에 못 찾고 상한만 낸 것이다.", "",
              "| 조건 | 공유 쌍 상한 | 값 비율 중앙 (최소 ~ 최대) | 97% 이상 | 구간(최적 미증명): 기록 수 · 상한 중앙 · 그중 상한 97% 이상 | J 중앙 | 바꿀 중앙 | 공유 중앙 | 이웃 수 중앙 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for th, v in s["per"].items():
            label = "기존 규칙(같은 덱 2개 이하)" if th == "rule" else f"J ≤ {th}"
            cap = "—" if th == "rule" else str(budget_of(float(th)))
            found = "" if v["found"] == v["n"] else f" · 못 찾음 {v['n'] - v['found']}"
            L.append(f"| {label} | {cap} | {pct(v['ratio_median'])} ({pct(v['ratio_min'])} ~ {pct(v['ratio_max'])}){found} | "
                     f"{v['good']}/{v['n']} | {interval(v)} | {f2(v['j_median'])} | "
                     f"{num(v['moves_median'])} | {num(v['shared_median'])} | {num(v['neighbors_median'])} |")
        L += ["", f"최선 덱의 이웃 수 중앙: {num(s['best_neighbors_median'])}.", "",
              "| 기록 | 구성 수 | 최선(억) | 기존 규칙 | " + " | ".join(f"J ≤ {t}" for t in THETAS) + " |",
              "|---|---|---|---|" + "---|" * len(THETAS)]
        for r in a["cases"]:
            if r["group"] != g:
                continue
            cells = [pct(r["rule"].get("ratio")) if r["rule"]["found"] else "—"]
            cells += [cell(r["thetas"][str(t)]) for t in THETAS]
            L.append(f"| {r['name']} | {r['records']} | {r['best_total']:.1f} | " + " | ".join(cells) + " |")
        L.append("")
    return "\n".join(L)


def run_case(case: tuple[str, str, Path]) -> dict[str, Any]:
    g, name, p = case
    t0 = time.monotonic()
    res = pick(book_of(p))
    res.update(group=g, name=name, best_check=check_best(g, name, res))
    print(f"{g} {name}: 기록 {res['records']} · {time.monotonic() - t0:.0f}초", flush=True)
    return res


def main() -> int:
    if "--report" in sys.argv:            # 계산은 그대로 두고 analysis.json에서 표만 다시 만든다
        a = json.loads((HERE / "analysis.json").read_text(encoding="utf-8"))
        a["summary"] = summarize(a["cases"])
        (HERE / "analysis.json").write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (HERE / "results.md").write_text(report(a), encoding="utf-8")
        print(" · ".join(f"{g}: {s['verdict']}" for g, s in a["summary"].items()))
        return 0
    with Pool(4) as pool:                 # 사례마다 독립(시뮬 없음) — 결과는 순서대로 모은다
        rows = pool.map(run_case, cases(), chunksize=1)
    a = {"thetas": THETAS, "main_theta": MAIN_THETA, "cases": rows, "summary": summarize(rows)}
    (HERE / "analysis.json").write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (HERE / "results.md").write_text(report(a), encoding="utf-8")
    print(" · ".join(f"{g}: {s['verdict']}" for g, s in a["summary"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
