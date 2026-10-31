"""실험 13 분석 — README §판단 기준(질문 1 U4 · 질문 2 U2w · 질문 3 합치기 대 고르기) · 합친 판 표.

    python experiments/13_seed_merge/analyze13.py --runs <실행 요약 dir> [--summary val_summary.jsonl]
        --precompute <precompute_U*.json · merges.json dir> --out experiments/13_seed_merge/results.md [--json <요약.json>] [--meta <메모.json>]

K 2,000은 실험 10 `val177_summary.jsonl`, K 800 · PB15(s0)는 실험 11, PB15s1~s3는 실험 12 `val_summary.jsonl`.
같은 실행이 여러 곳에 있으면 실험 10 < 11 < 12 < `--summary` < `--runs` 순으로 덮는다. 판단 상수 · 규칙은 analyze10 · analyze11 그대로다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP12 = HERE.parent / "12_precompute_seeds"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


Z = sys.modules.get("analyze12") or _load("analyze12", EXP12 / "analyze12.py")
B, A = Z.B, Z.A

POOL, BASE, BUDGETS, VAL = Z.POOL, Z.BASE, Z.BUDGETS, Z.VAL
SINGLES = Z.ALL_PB15
MERGED = ("U4", "U2w")
EXP12_LOG = EXP12 / "run_log"
Key = Z.Key


# ---------------------------------------------------------------- 읽기

def load_runs(runs: Path | None, summary: Path | None) -> dict[Key, dict[str, Any]]:
    layers = [("실험 10", B.load_jsonl(Z.EXP10_LOG / "val177_summary.jsonl", (BASE,))),
              ("실험 11", B.load_jsonl(Z.EXP11_LOG / "val_summary.jsonl", (BASE, Z.REF))),
              ("실험 12", B.load_jsonl(EXP12_LOG / "val_summary.jsonl", Z.SEEDS))]
    if summary:
        layers.append((summary.name, B.load_jsonl(summary)))
    if runs:
        layers.append((runs.name, B.load_dir(runs)))
    return B.merge_runs(layers)


def load_merged(d: Path | None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    pre: dict[str, dict[str, Any]] = {}
    obs: list[dict[str, Any]] = []
    if d is None or not d.is_dir():
        return pre, obs
    for m in MERGED:
        p = d / f"precompute_{m}.json"
        if p.is_file():
            pre[m] = json.loads(p.read_text(encoding="utf-8"))
    p = d / "merges.json"
    if p.is_file():
        obs = json.loads(p.read_text(encoding="utf-8"))
    return pre, obs


# ---------------------------------------------------------------- 판단

def hstats(T: Mapping[Key, float], m: str, base: str, b: int) -> dict[str, Any]:
    return B.stat(B.rel(T, m, base, b, VAL), len(VAL))


def both(st: Mapping[int, Mapping[str, Any]], f: str) -> bool:
    return all(st[b][f] for b in BUDGETS)


def complete(st: Mapping[int, Mapping[str, Any]]) -> bool:
    return all(st[b]["complete"] for b in BUDGETS)


def judge_k(T: Mapping[Key, float], m: str, yes: str, no: str) -> dict[str, Any]:
    st = {b: hstats(T, m, BASE, b) for b in BUDGETS}
    if not complete(st):
        return {"stats": st, "ok": None, "text": "판단 불가 — 계정 실행이 모자란다"}
    ok = both(st, "noninf")
    return {"stats": st, "ok": ok, "text": yes if ok else no}


def judge3(T: Mapping[Key, float], m: str, ref: str | None) -> dict[str, Any]:
    if ref is None:
        return {"ref": None, "stats": None, "verdict": None, "text": "판단 불가 — 합친 판이 없다"}
    st = {b: hstats(T, m, ref, b) for b in BUDGETS}
    if not complete(st):
        return {"ref": ref, "stats": st, "verdict": None, "text": "판단 불가 — 계정 실행이 모자란다"}
    if both(st, "noninf") and any(st[b]["better"] for b in BUDGETS):
        v, t = "better", "합치기가 낫다"
    elif both(st, "noninf"):
        v, t = "noninf", "합치기 ≥ 고르기"
    else:
        v, t = "pick", "고르기가 낫다(합치기 쓰지 않음)"
    return {"ref": ref, "stats": st, "verdict": v, "text": t}


def e3_core(obs: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    e3 = [o for o in obs if o["kind"] == "E3"]
    return sum(bool(o["core"]) for o in e3), len(e3)


def next_step(q1: Mapping[str, Any], q2: Mapping[str, Any], q3: Mapping[str, Any], obs: Sequence[Mapping[str, Any]]) -> str:
    if q1["ok"] is None:
        return "판단 불가 — U4 계정 실행을 마저 돌린다"
    if not q1["ok"]:
        return "합치기로는 운을 못 없앤다 — 실험 12 표대로 PBD를 새 시드 3개로 확인"
    if q2["ok"] is None:
        return "U4는 통과 — U2w 계정 실행을 마저 돌린 뒤 정한다"
    if q2["ok"]:
        how = "고르기" if q3["U2w"]["verdict"] == "pick" else "합치기"
        return f"기본을 「PB15 시드 2개({how})」로 바꾸는 후보 — 새 시드 2쌍(s4~s7)으로 확인"
    how = "고르기" if q3["U4"]["verdict"] == "pick" else "합치기"
    k, n = e3_core(obs)
    tail = (f"E3가 {k}/{n}개 뼈대 → 실제 짧은 사전 계산 3개(M3) 확인" if k >= 3
            else f"E3가 {k}/{n}개 뼈대 → 시드 4개 그대로 새 시드로 확인")
    return f"기본을 「PB15 시드 4개({how})」로 바꾸는 후보 — {tail}"


def missing_runs(runs: Mapping[Key, Any], methods: Sequence[str]) -> list[str]:
    return [f"{s}_P177_{m}_{b}" for m in methods for b in BUDGETS for s in VAL if (s, POOL, m, b) not in runs]


def analyze(runs: Mapping[Key, Mapping[str, Any]], pre: Mapping[str, Mapping[str, Any]],
            obs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    T = Z.totals(runs)
    q1 = judge_k(T, "U4", "시드 4개 합치기로 운이 없어진다", "합치기로는 부족")
    q2 = judge_k(T, "U2w", "가장 나쁜 쌍도 된다 — 시드 2개로 충분", "시드 2개로는 부족")
    q3 = {m: judge3(T, m, pre[m]["pick"] if m in pre else None) for m in MERGED}
    singles = {m: {b: hstats(T, m, BASE, b) for b in BUDGETS} for m in SINGLES}
    by_seed = {s: {m: {b: T.get((s, POOL, m, b)) for b in BUDGETS} for m in (BASE,) + SINGLES + MERGED} for s in VAL}
    return {"pre": pre, "obs": list(obs), "q1": q1, "q2": q2, "q3": q3, "singles": singles, "e3": e3_core(obs),
            "next": next_step(q1, q2, q3, obs), "by_seed": by_seed,
            "missing": missing_runs(runs, (BASE,) + SINGLES + MERGED)}


# ---------------------------------------------------------------- 출력

f, pct, srow = Z.f, Z.pct, Z.srow


def seeds_txt(ss: Sequence[int]) -> str:
    return "·".join(f"s{k}" for k in ss)


def render(a: Mapping[str, Any], meta: Mapping[str, Any] | None = None) -> str:
    L = ["# 실험 13 결과 (analyze13.py 생성)", ""]
    if meta:
        L += [f"- {k}: {v}" for k, v in meta.items()] + [""]
    L += ["## 합친 판 (사전 계산 계정, 억)", "",
          "| 기호 | 시드 | 평가 | 시뮬(출처 합) | 구성 | 최선 5덱 | 시드 하나 최고 | 뼈대 | 195↑ | 8벌 | 덱별 출처 시드 |",
          "|---|---|---:|---:|---:|---:|---:|:-:|:-:|---|---|"]
    rows = [a["pre"][m] for m in MERGED if m in a["pre"]] + list(a["obs"])
    for r in rows:
        sets = f"{min(r['set_totals']):.1f}~{max(r['set_totals']):.1f}" if r.get("set_totals") else "—"
        src = " ".join(seeds_txt(s) for s in r["squad_seeds"])
        cut = "" if r["part"] == 1 else f" (각 앞 1/{r['part']})"
        L.append(f"| {r['name']} | {seeds_txt(r['seeds'])}{cut} | "
                 f"{r['evals']:,} | {r['sims']:,} | {r['comps']:,} | {f(r['final']['total'])} | {f(max(r['single'].values()))} | "
                 f"{'O' if r['core'] else '—'} | {'O' if r['ge195'] else '—'} | {sets} | {src} |")
    k, n = a["e3"]
    L += ["", f"같은 비용 판 E3(셋 × 앞 1/3) 뼈대: {k}/{n}"]
    L += ["", "## 판단 (K177 대비 H: 중앙 (−3% 밑 개수) [최소 ~ 최대] 판정)", "", "| 기호 | 800 | 2,000 |", "|---|---|---|"]
    for m in SINGLES:
        L.append(f"| {m} (기록) | {srow(a['singles'][m][800])} | {srow(a['singles'][m][2000])} |")
    for m, q in (("U4", a["q1"]), ("U2w", a["q2"])):
        L.append(f"| **{m}** | {srow(q['stats'][800])} | {srow(q['stats'][2000])} |")
    L += ["", f"- **질문 1 — U4: {a['q1']['text']}**", f"- **질문 2 — U2w: {a['q2']['text']}**"]
    for m in MERGED:
        q = a["q3"][m]
        L.append(f"- **질문 3 — {m} 대 고르기({q['ref']}): {q['text']}**"
                 + ("" if not q["stats"] else f" — R 800 {srow(q['stats'][800])} · 2,000 {srow(q['stats'][2000])}"))
    L += ["", f"## 다음 방향 (사전 등록 표): {a['next']}", "", "## 시나리오별 최종 5덱 합(억)", ""]
    cols = (BASE,) + SINGLES + MERGED
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
    pre, obs = load_merged(args.precompute)
    a = analyze(runs, pre, obs)
    meta = json.loads(args.meta.read_text(encoding="utf-8")) if args.meta else None
    args.out.write_text(render(a, meta), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(a, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"q1": a["q1"]["text"], "q2": a["q2"]["text"], "q3": {m: a["q3"][m]["text"] for m in MERGED},
                      "e3": a["e3"], "next": a["next"], "missing": len(a["missing"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
