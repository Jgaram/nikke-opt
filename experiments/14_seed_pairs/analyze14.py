"""실험 14 분석 — README §판단 기준(새 쌍 2개가 K177에 못지않은가 · 조건부 U4n) · 시드 하나 8개 표 · 합친 판 표.

    python experiments/14_seed_pairs/analyze14.py --runs <실행 요약 dir> [--summary val_summary.jsonl]
        --precompute <precompute_*.json · merges.json dir> --out experiments/14_seed_pairs/results.md [--json <요약.json>] [--meta <메모.json>]

K는 실험 10 · 11, 실험 13 U4 · U2w는 실험 13 `val_summary.jsonl`(참고). 판단 상수 · 규칙은 analyze10 · analyze11 그대로다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP13 = HERE.parent / "13_seed_merge"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


Y = sys.modules.get("analyze13") or _load("analyze13", EXP13 / "analyze13.py")
Z, B, A = Y.Z, Y.B, Y.A

POOL, BASE, BUDGETS, VAL = Y.POOL, Y.BASE, Y.BUDGETS, Y.VAL
PAIRS = {"U2a": (4, 5), "U2b": (6, 7)}
COND = "U4n"
OLD = ("U4", "U2w")                 # 실험 13(참고)
EXP13_LOG = EXP13 / "run_log"
EXP12_LOG = Z.HERE / "run_log"
Key = Y.Key


def seed_method(k: int) -> str:
    return "PB15" if k == 0 else f"PB15s{k}"


# ---------------------------------------------------------------- 읽기

def load_runs(runs: Path | None, summary: Path | None) -> dict[Key, dict[str, Any]]:
    layers = [("실험 10", B.load_jsonl(Z.EXP10_LOG / "val177_summary.jsonl", (BASE,))),
              ("실험 11", B.load_jsonl(Z.EXP11_LOG / "val_summary.jsonl", (BASE,))),
              ("실험 13", B.load_jsonl(EXP13_LOG / "val_summary.jsonl", OLD))]
    if summary:
        layers.append((summary.name, B.load_jsonl(summary)))
    if runs:
        layers.append((runs.name, B.load_dir(runs)))
    return B.merge_runs(layers)


def load_singles(d: Path | None) -> dict[int, dict[str, Any]]:
    """시드 0~7의 PB15 사전 계산(실험 11 · 12 · 이 실험)."""
    out = {}
    for k in range(8):
        m = seed_method(k)
        for base in (Z.EXP11_LOG, EXP12_LOG, d):
            p = base / f"precompute_{m}.json" if base else None
            if p and p.is_file():
                out[k] = json.loads(p.read_text(encoding="utf-8"))
                break
    return out


def load_merged(d: Path | None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    pre: dict[str, dict[str, Any]] = {}
    obs: list[dict[str, Any]] = []
    if d is None or not d.is_dir():
        return pre, obs
    for m in (*PAIRS, COND):
        p = d / f"precompute_{m}.json"
        if p.is_file():
            pre[m] = json.loads(p.read_text(encoding="utf-8"))
    p = d / "merges.json"
    if p.is_file():
        obs = json.loads(p.read_text(encoding="utf-8"))
    return pre, obs


# ---------------------------------------------------------------- 판단

def single_rows(singles: Mapping[int, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for k, d in sorted(singles.items()):
        t = Z.t_reach(d.get("history", []))
        rows.append({"seed": k, "name": seed_method(k), "final": d["final"]["total"], "t195": t, "core": Z.core_in(d["final"]),
                     "failed": t is None, "new": k >= 4})
    return rows


def judge(T: Mapping[Key, float], singles: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    fail = {r["seed"]: r["failed"] for r in single_rows(singles)}
    per = {}
    for m, (a, b) in PAIRS.items():
        q = Y.judge_k(T, m, "못지않다", "못지않다 아님")
        q["both_failed"] = (fail.get(a), fail.get(b)) == (True, True)
        q["seeds"] = (a, b)
        per[m] = q
    if any(q["ok"] is None for q in per.values()):
        return {"per": per, "n_ok": None, "u4n": None, "text": "판단 불가 — 계정 실행이 모자란다", "next": "새 쌍 계정 실행을 마저 돌린다"}
    n = sum(bool(q["ok"]) for q in per.values())
    if n == 2:
        return {"per": per, "n_ok": n, "u4n": None, "text": "시드 2개 합치기로 충분 — 랭커 없는 기본을 PB15 시드 2개 합치기로 바꾼다",
                "next": "신캐 추가 모사(갱신: 처음부터 다시 대 이어 붙이기)"}
    u = Y.judge_k(T, COND, "못지않다", "못지않다 아님")
    if u["ok"] is None:
        nxt, txt = "조건부 U4n 계정 실행을 마저 돌린다", "시드 2개로는 부족 — U4n 판단 불가"
    elif u["ok"]:
        nxt, txt = "기본 = 시드 4개 합치기, 그 뒤 신캐 추가 모사", "시드 2개로는 부족 — 시드 4개 합치기(U4n)는 못지않다"
    else:
        nxt, txt = "합치기로도 운이 남는다 — PBD 시드 확인 등 강건화", "시드 2개로는 부족 — U4n도 못지않다 아님"
    return {"per": per, "n_ok": n, "u4n": u, "text": txt, "next": nxt}


def obs_counts(obs: Sequence[Mapping[str, Any]]) -> dict[str, tuple[int, int]]:
    out = {}
    for kind in ("U2", "U3", "E2", "E3"):
        xs = [o for o in obs if o["kind"] == kind]
        out[kind] = (sum(bool(o["core"]) for o in xs), len(xs))
    return out


def analyze(runs: Mapping[Key, Mapping[str, Any]], singles: Mapping[int, Mapping[str, Any]],
            pre: Mapping[str, Mapping[str, Any]], obs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    T = Z.totals(runs)
    j = judge(T, singles)
    old = {m: Y.judge_k(T, m, "못지않다", "못지않다 아님") for m in OLD}
    shown = (BASE,) + OLD + tuple(PAIRS) + ((COND,) if j["u4n"] is not None else ())
    by_seed = {s: {m: {b: T.get((s, POOL, m, b)) for b in BUDGETS} for m in shown} for s in VAL}
    need = list(PAIRS) + ([COND] if j["u4n"] is not None else [])
    rows = single_rows(singles)
    return {"singles": rows, "n_failed": sum(r["failed"] for r in rows), "n_core": sum(r["core"] for r in rows),
            "pre": pre, "obs": list(obs), "obs_counts": obs_counts(obs), "judge": j, "old": old,
            "by_seed": by_seed, "shown": shown, "missing": Y.missing_runs(runs, need)}


# ---------------------------------------------------------------- 출력

f, pct, srow, seeds_txt = Y.f, Y.pct, Y.srow, Y.seeds_txt


def render(a: Mapping[str, Any], meta: Mapping[str, Any] | None = None) -> str:
    L = ["# 실험 14 결과 (analyze14.py 생성)", ""]
    if meta:
        L += [f"- {k}: {v}" for k, v in meta.items()] + [""]
    L += ["## 시드 하나 PB15 (사전 계산 계정, 억)", "", "| 시드 | 최종 | T195 | 뼈대 | 비고 |", "|---|---:|---:|:-:|---|"]
    for r in a["singles"]:
        L.append(f"| s{r['seed']} | {f(r['final'])} | {f(r['t195'], 0) if r['t195'] else '미도달'} | {'O' if r['core'] else '—'} | "
                 f"{'새 시드' if r['new'] else '실험 11 · 12'} |")
    L += ["", f"195억 미도달 {a['n_failed']}/{len(a['singles'])} · 뼈대 {a['n_core']}/{len(a['singles'])}", "",
          "## 합친 판 (사전 계산 계정, 억)", "",
          "| 기호 | 시드 | 평가 | 시뮬(출처 합) | 최선 5덱 | 시드 하나 최고 | 뼈대 | 195↑ | 8벌 | 덱별 출처 시드 |",
          "|---|---|---:|---:|---:|---:|:-:|:-:|---|---|"]
    for r in [a["pre"][m] for m in (*PAIRS, COND) if m in a["pre"]] + list(a["obs"]):
        sets = f"{min(r['set_totals']):.1f}~{max(r['set_totals']):.1f}" if r.get("set_totals") else "—"
        cut = "" if r["part"] == 1 else f" (각 앞 1/{r['part']})"
        L.append(f"| {r['name']} | {seeds_txt(r['seeds'])}{cut} | {r['evals']:,} | {r['sims']:,} | {f(r['final']['total'])} | "
                 f"{f(max(r['single'].values()))} | {'O' if r['core'] else '—'} | {'O' if r['ge195'] else '—'} | {sets} | "
                 f"{' '.join(seeds_txt(s) for s in r['squad_seeds'])} |")
    L += ["", "관찰(뼈대 담은 수): " + " · ".join(f"{k} {c}/{n}" for k, (c, n) in a["obs_counts"].items())]
    j = a["judge"]
    L += ["", "## 판단 (K177 대비 H: 중앙 (−3% 밑 개수) [최소 ~ 최대] 판정)", "", "| 기호 | 800 | 2,000 | 비고 |", "|---|---|---|---|"]
    for m, q in a["old"].items():
        L.append(f"| {m} (실험 13) | {srow(q['stats'][800])} | {srow(q['stats'][2000])} | 참고 |")
    for m, q in j["per"].items():
        L.append(f"| **{m}** | {srow(q['stats'][800])} | {srow(q['stats'][2000])} | {seeds_txt(q['seeds'])}"
                 f"{' · 두 시드 모두 195억 미도달' if q['both_failed'] else ''} |")
    if j["u4n"] is not None:
        L.append(f"| **{COND}** (조건부) | {srow(j['u4n']['stats'][800])} | {srow(j['u4n']['stats'][2000])} | s4·s5·s6·s7 |")
    L += ["", f"- **새 쌍 통과 {j['n_ok'] if j['n_ok'] is not None else '—'}/2 → {j['text']}**",
          f"- **다음 방향 (사전 등록 표): {j['next']}**", "", "## 시나리오별 최종 5덱 합(억)", ""]
    cols = a["shown"]
    L += ["| 시나리오 | " + " | ".join(f"{m} {b}" for m in cols for b in BUDGETS) + " |", "|---|" + "---:|" * (2 * len(cols))]
    for s, row in a["by_seed"].items():
        L.append(f"| {s} | " + " | ".join(f(row[m][b]) for m in cols for b in BUDGETS) + " |")
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
    singles = load_singles(args.precompute)
    pre, obs = load_merged(args.precompute)
    a = analyze(runs, singles, pre, obs)
    meta = json.loads(args.meta.read_text(encoding="utf-8")) if args.meta else None
    args.out.write_text(render(a, meta), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(a, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    j = a["judge"]
    print(json.dumps({"n_ok": j["n_ok"], "text": j["text"], "next": j["next"], "failed": a["n_failed"],
                      "obs": a["obs_counts"], "missing": len(a["missing"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
