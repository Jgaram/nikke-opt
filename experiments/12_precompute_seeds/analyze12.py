"""실험 12 분석 — README §판단 기준(질문 1 시드 강건성 · 질문 2 PBD · PBS 유망) · 사전 계산 표.

    python experiments/12_precompute_seeds/analyze12.py --runs <실행 요약 dir> [--summary val_summary.jsonl]
        [--precompute <precompute_*.json dir>] --out experiments/12_precompute_seeds/results.md [--json <요약.json>] [--meta <메모.json>]

K 2,000은 실험 10 `val177_summary.jsonl`, K 800 · PB15(s0)는 실험 11 `val_summary.jsonl`, PB15 사전 계산(s0)은 실험 11 `precompute_PB15.json`.
같은 실행이 여러 곳에 있으면 실험 10 < 실험 11 < `--summary` < `--runs` 순으로 덮는다. 판단 상수 · 규칙은 analyze10 · analyze11 그대로다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP10_LOG = HERE.parent / "10_rankerless_start" / "run_log"
EXP11 = HERE.parent / "11_wide_precompute"
EXP11_LOG = EXP11 / "run_log"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


B = sys.modules.get("analyze11") or _load("analyze11", EXP11 / "analyze11.py")
A = B.A

POOL = 177
BASE = "K"
REF = "PB15"                       # s0 = 실험 11 PB15
SEEDS = ("PB15s1", "PB15s2", "PB15s3")
ALL_PB15 = (REF,) + SEEDS
VARIANTS = ("PBD", "PBS")
BUDGETS = (800, 2000)
TOP = 2000
VAL = A.VAL_SCENARIOS
TARGET = 195.0                     # T195(억, 임시 기준)
EARLY = 10000                      # (a) T195 ≤ 이 값이면 10k 판
QUALITY = 1.01                     # (b) 최종 ≥ PB15 네 시드 최종 중앙 × 이 값이면 15,000 판
CORE = {"토브", "아르카나 : 포츈 메이트", "도로시 : 세렌디피티", "드레이크"}
Key = tuple[str, int, str, int]
COND_RE = re.compile(r"^(PBD|PBS)s(\d+)$")


def _warn(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------- 읽기

def load_precompute(dirs: Sequence[Path | None]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    p0 = EXP11_LOG / "precompute_PB15.json"
    if p0.is_file():
        out[REF] = json.loads(p0.read_text(encoding="utf-8"))
    for d in dirs:
        if d is None or not d.is_dir():
            continue
        for p in sorted(d.glob("precompute_*.json")):
            name = p.stem[len("precompute_"):]
            if name in out:
                continue
            try:
                out[name] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                _warn(f"읽을 수 없는 사전 계산 건너뜀: {p.name} ({e!r})")
    return out


def load_runs(runs: Path | None, summary: Path | None) -> dict[Key, dict[str, Any]]:
    layers = [("실험 10", B.load_jsonl(EXP10_LOG / "val177_summary.jsonl", (BASE,))),
              ("실험 11", B.load_jsonl(EXP11_LOG / "val_summary.jsonl", (BASE, REF)))]
    if summary:
        layers.append((summary.name, B.load_jsonl(summary)))
    if runs:
        layers.append((runs.name, B.load_dir(runs)))
    return B.merge_runs(layers)


# ---------------------------------------------------------------- 지표

def t_reach(history: Sequence[Mapping[str, Any]], target: float = TARGET) -> int | None:
    for h in history or []:
        if h["pack"] >= target - 1e-9:
            return h["evals"]
    return None


def core_in(final: Mapping[str, Any]) -> bool:
    return any(CORE <= set(sq) for _, sq in (final or {}).get("squads", []))


def pre_rows(pre: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name, d in pre.items():
        h = d.get("history", [])
        rs = d.get("restarts") or []
        ks = d.get("kicks") or []
        rows.append({"name": name, "seed": d.get("seed", 0), "kind": d.get("kind", "PB15"), "evals": d["evals"],
                     "sims": d["sims"], "seconds": d["seconds"], "at5k": B.pack_at(h, 5000), "at10k": B.pack_at(h, 10000),
                     "final": d["final"]["total"], "t195": t_reach(h), "core": core_in(d["final"]),
                     "sets": [min(d["set_totals"]), max(d["set_totals"])] if d.get("set_totals") else None,
                     "kicks": len(ks), "kicks_up": sum(bool(k.get("improved")) for k in ks),
                     "restarts": len(rs), "climb_best": max((r["end_val"] for r in rs), default=None),
                     "cut_from": d.get("cut_from")})
    order = {n: i for i, n in enumerate(ALL_PB15 + VARIANTS)}
    return sorted(rows, key=lambda r: (order.get(r["name"], 99), r["name"]))


def totals(runs: Mapping[Key, Mapping[str, Any]]) -> dict[Key, float]:
    return {k: r["final"]["total"] for k, r in runs.items()}


def hstats(T: Mapping[Key, float], m: str, b: int) -> dict[str, Any]:
    return B.stat(B.rel(T, m, BASE, b, VAL), len(VAL))


# ---------------------------------------------------------------- 판단

def judge1(T: Mapping[Key, float]) -> dict[str, Any]:
    st = {m: {b: hstats(T, m, b) for b in BUDGETS} for m in ALL_PB15}
    ok = [m for m in SEEDS if all(st[m][b]["noninf"] for b in BUDGETS)]
    complete = all(st[m][b]["complete"] for m in SEEDS for b in BUDGETS)
    n = len(ok)
    line = 3 if n == 3 else 2 if n == 2 else 1
    text = {3: "시드에 강건 — 랭커 없는 기본 PB15 유지", 2: "대체로 강건, 실패 시드 있음 — PB15 유지",
            1: "s0는 운이 좋았다 — PB15를 기본으로 단정하지 않는다"}[line]
    pooled = {b: [g for m in ALL_PB15 for g in B.rel(T, m, BASE, b, VAL)] for b in BUDGETS}
    pooled_st = {b: {"n": len(v), "median": A.med(v), "low": A.n_low(v), "min": min(v) if v else None} for b, v in pooled.items()}
    return {"stats": st, "ok": ok, "n_ok": n, "line": line, "text": text, "complete": complete, "pooled": pooled_st}


def retry_seed(pre: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """PB15s1~s3 중 15,000 안에 195억 미도달 시드, 그중 최종이 가장 낮은 것."""
    failed = [m for m in SEEDS if m in pre and t_reach(pre[m].get("history", [])) is None]
    pick = min(failed, key=lambda m: (pre[m]["final"]["total"], m)) if failed else None
    return {"failed": failed, "pick": pick, "seed": pre[pick].get("seed") if pick else None,
            "missing": [m for m in SEEDS if m not in pre]}


def targets(pre: Mapping[str, Mapping[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    """기법(PBD · PBS · 조건부) → [(계정에서 검증할 판, 이유)]."""
    finals = [pre[m]["final"]["total"] for m in ALL_PB15 if m in pre]
    med = statistics.median(finals) if finals else None
    out: dict[str, list[tuple[str, str]]] = {}
    for name, d in pre.items():
        if d.get("cut_from"):
            continue
        t = t_reach(d.get("history", []))
        if name in VARIANTS:
            lst = []
            if t is not None and t <= EARLY:
                lst.append((f"{name}10k", f"(a) T195 {t} ≤ {EARLY}"))
            if med is not None and d["final"]["total"] >= med * QUALITY - 1e-9:
                lst.append((name, f"(b) 최종 {d['final']['total']:.1f} ≥ PB15 중앙 {med:.1f} × {QUALITY}"))
            out[name] = lst
        elif COND_RE.match(name):
            out[name] = [(name, f"(a') T195 {t}")] if t is not None else []
    return out


def judge2(T: Mapping[Key, float], pre: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    tg = targets(pre)
    per: dict[str, Any] = {}
    for x, lst in tg.items():
        checks = []
        for m, why in lst:
            st = {b: hstats(T, m, b) for b in BUDGETS}
            done = all(st[b]["complete"] for b in BUDGETS)
            checks.append({"method": m, "why": why, "stats": st, "done": done,
                           "promising": done and all(st[b]["noninf"] for b in BUDGETS)})
        if not lst:
            verdict = "효과 없음(이 시드) — 계정 검증 대상 아님"
        elif not all(c["done"] for c in checks) and not any(c["promising"] for c in checks):
            verdict = "판단 불가 — 계정 실행이 모자란다"
        elif any(c["promising"] for c in checks):
            good = [c["method"] for c in checks if c["promising"]]
            if COND_RE.match(x):
                verdict = f"그 시드를 구제({', '.join(good)})"
            elif any(g.endswith("10k") for g in good):
                verdict = f"사전 계산 2/3로 유망({', '.join(good)})"
            else:
                verdict = f"유망({', '.join(good)})"
        else:
            verdict = "효과 없음(이 시드)"
        per[x] = {"checks": checks, "verdict": verdict}
    promising = [x for x, v in per.items() if v["verdict"].startswith(("유망", "사전 계산", "그 시드"))]
    early = [x for x in promising if per[x]["verdict"].startswith("사전 계산")]
    return {"per": per, "promising": promising, "early": early}


def next_step(q1: Mapping[str, Any], q2: Mapping[str, Any]) -> str:
    if q1["n_ok"] == 3:
        if q2["early"]:
            return f"{', '.join(q2['early'])}의 10k를 시드 3개로 확인(사전 계산 비용 2/3)"
        if q2["promising"]:
            return f"PB15 유지 — {', '.join(q2['promising'])}는 시드 확인 후보(표에 없는 경우: 15,000 판 유망)"
        return "PB15 채택 유지 — 다음 과제로(랭커 자료가 있을 때 K 대신 PB15 · 큐브)"
    if q2["promising"]:
        return f"{', '.join(q2['promising'])}를 시드 3개로 확인 → 기본 교체 후보"
    return "시드 묶기(시드 2개 기록 합치기) 등 다른 강건화"


def missing_runs(runs: Mapping[Key, Any], methods: Sequence[str]) -> list[str]:
    return [f"{s}_P177_{m}_{b}" for m in methods for b in BUDGETS for s in VAL if (s, POOL, m, b) not in runs]


def analyze(runs: Mapping[Key, Mapping[str, Any]], pre: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    T = totals(runs)
    q1 = judge1(T)
    q2 = judge2(T, pre)
    need = [BASE] + list(ALL_PB15) + [c["method"] for v in q2["per"].values() for c in v["checks"]]
    g = {m: {b: A.gstats(B.rel(T, m, REF, b, VAL)) for b in BUDGETS} for m in SEEDS}
    by_seed = {s: {m: {b: (T.get((s, POOL, m, b))) for b in BUDGETS} for m in [BASE] + list(ALL_PB15)} for s in VAL}
    return {"pre": pre_rows(pre), "q1": q1, "retry": retry_seed(pre), "q2": q2, "next": next_step(q1, q2),
            "g_vs_s0": g, "by_seed": by_seed, "missing": missing_runs(runs, need)}


# ---------------------------------------------------------------- 출력

def f(x: Any, nd: int = 1) -> str:
    return "—" if x is None else f"{x:,.{nd}f}"


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:+.1f}%"


def srow(s: Mapping[str, Any]) -> str:
    return f"{pct(s['median'])} ({s['low']}) [{pct(s['min'])} ~ {pct(s['max'])}] {B.label(s)}"


def render(a: Mapping[str, Any], meta: Mapping[str, Any] | None = None) -> str:
    L = ["# 실험 12 결과 (analyze12.py 생성)", ""]
    if meta:
        L += [f"- {k}: {v}" for k, v in meta.items()] + [""]
    L += ["## 사전 계산 (사전 계산 계정, 억)", "",
          "| 기호 | 시드 | 평가 | 시뮬 | 초 | 5,000 | 10,000 | 최종 | T195 | 뼈대 | 8벌 | 킥(개선) | 등반자(최고) |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|:-:|---|---:|---:|"]
    for r in a["pre"]:
        sets = f"{r['sets'][0]:.1f}~{r['sets'][1]:.1f}" if r["sets"] else "—"
        L.append(f"| {r['name']} | s{r['seed']} | {r['evals']:,} | {r['sims']:,} | {f(r['seconds'], 0)} | {f(r['at5k'])} | "
                 f"{f(r['at10k'])} | {f(r['final'])} | {f(r['t195'], 0) if r['t195'] else '미도달'} | {'O' if r['core'] else '—'} | "
                 f"{sets} | {r['kicks']}({r['kicks_up']}) | {r['restarts']}({f(r['climb_best'])}) |")
    q1 = a["q1"]
    L += ["", f"## 질문 1 — PB15가 시드에 강건한가: **{q1['n_ok']}/3 → {q1['text']}**"
          + ("" if q1["complete"] else " (실행이 모자라 판단 불가)"), "",
          "K177 대비 H: 중앙 (−3% 밑 개수) [최소 ~ 최대] 판정", "", "| 기호 | 800 | 2,000 |", "|---|---|---|"]
    for m in ALL_PB15:
        L.append(f"| {m}{' (실험 11)' if m == REF else ''} | {srow(q1['stats'][m][800])} | {srow(q1['stats'][m][2000])} |")
    L += ["", "네 시드 묶음(관찰): " + " · ".join(f"{b}: 중앙 {pct(s['median'])}, −3% 밑 {s['low']}/{s['n']}, 최소 {pct(s['min'])}"
                                         for b, s in q1["pooled"].items())]
    L += ["", "보조 G(PB15 s0 대비) 중앙: " + " · ".join(
        f"{m} {pct(a['g_vs_s0'][m][800]['median'])} / {pct(a['g_vs_s0'][m][2000]['median'])}" for m in SEEDS) + " (800 / 2,000)"]
    rt = a["retry"]
    L += ["", f"실패 시드 재시도 조건: 195억 미도달 {rt['failed'] or '없음'} → "
          + (f"**{rt['pick']}(s{rt['seed']})에서 PBD · PBS 재시도**" if rt["pick"] else "재시도 없음")]
    q2 = a["q2"]
    L += ["", "## 질문 2 — PBD · PBS가 유망한가", ""]
    for x, v in q2["per"].items():
        L.append(f"- **{x}: {v['verdict']}**")
        for c in v["checks"]:
            L.append(f"  - {c['method']} ({c['why']}): 800 {srow(c['stats'][800])} · 2,000 {srow(c['stats'][2000])}")
    L += ["", f"## 다음 방향 (사전 등록 표): {a['next']}", "", "## 시나리오별 최종 5덱 합(억)", "",
          "| 시나리오 | " + " | ".join(f"{m} {b}" for m in [BASE] + list(ALL_PB15) for b in BUDGETS) + " |",
          "|---|" + "---:|" * (2 * (1 + len(ALL_PB15)))]
    for s, row in a["by_seed"].items():
        L.append(f"| {s} | " + " | ".join(f(row[m][b]) for m in [BASE] + list(ALL_PB15) for b in BUDGETS) + " |")
    if a["missing"]:
        L += ["", f"빠진 실행 {len(a['missing'])}개: {', '.join(a['missing'][:12])}{' …' if len(a['missing']) > 12 else ''}"]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=Path)
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--precompute", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--meta", type=Path)
    args = ap.parse_args(argv)
    runs = load_runs(args.runs, args.summary)
    pre = load_precompute([args.precompute, args.runs, args.summary.parent if args.summary else None])
    a = analyze(runs, pre)
    meta = json.loads(args.meta.read_text(encoding="utf-8")) if args.meta else None
    args.out.write_text(render(a, meta), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(a, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"q1": [a["q1"]["n_ok"], a["q1"]["ok"]], "retry": a["retry"]["pick"],
                      "q2": {x: v["verdict"] for x, v in a["q2"]["per"].items()}, "next": a["next"],
                      "missing": len(a["missing"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
