"""실험 15 분석 — README §판단 기준(경우별: O · I1 · I2가 F4에 못지않은가, 취합: 기본 갱신 절차).

    python experiments/15_new_nikke/analyze15.py --case C1 [--runs <실행 요약 dir>]
        → cases/C1/results.md · cases/C1/run_log/analysis.json
    python experiments/15_new_nikke/analyze15.py
        → results.md(취합) · run_log/analysis.json — cases/C*/run_log/val_summary.jsonl이 있는 경우를 모두 읽는다

F4 보유 조건 = 실험 13 `val_summary.jsonl`의 U4(기호를 F4로 읽는다), K = 실험 10 · 11(analyze13과 같다).
그 경우의 실행은 `cases/<경우>/run_log/val_summary.jsonl`(+ `--runs`). 「못지않다」 상수 · 규칙은 analyze10 · analyze11 그대로다.
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
W = sys.modules.get("run15") or _load("run15", HERE / "run15.py")

POOL, BUDGETS, VAL = Y.POOL, Y.BUDGETS, tuple(Y.VAL)
K = Y.BASE
BASE = "F4"
UPD = ("O", "I1", "I2")                   # 싼 순서(I1 · I2는 같은 비용, 둘 다면 I1)
VALN = tuple(f"{s}n" for s in VAL)        # 미보유 조건
MISS_BUDGET = 800
MISS_LOSS = 0.01                          # 갱신 판 G 중앙이 O보다 이만큼 넘게 낮으면 「미보유 계정 손해」
Key = Y.Key
CASES_DIR = HERE / "cases"
TEXT = {"O": "갱신 불필요", "I1": "이어 붙이기로 충분(I1 — 새 시드 하나)", "I2": "이어 붙이기로 충분(I2 — 신캐 집중)",
        "F4": "처음부터 다시 필요", None: "판단 불가 — 계정 실행이 모자란다"}


# ---------------------------------------------------------------- 읽기

def f4_runs() -> dict[Key, dict[str, Any]]:
    """실험 13 U4 → F4."""
    out = {}
    for (s, p, m, b), r in B.load_jsonl(EXP13 / "run_log" / "val_summary.jsonl", ("U4",)).items():
        out[(s, p, BASE, b)] = dict(r, method=BASE)
    return out


def load_runs(case_log: Path | None, runs: Path | None = None) -> dict[Key, dict[str, Any]]:
    layers = [("실험 10", B.load_jsonl(Z.EXP10_LOG / "val177_summary.jsonl", (K,))),
              ("실험 11", B.load_jsonl(Z.EXP11_LOG / "val_summary.jsonl", (K,))),
              ("실험 13 U4", f4_runs())]
    if case_log is not None and (case_log / "val_summary.jsonl").is_file():
        layers.append(("val_summary", B.load_jsonl(case_log / "val_summary.jsonl")))
    if runs:
        layers.append((runs.name, B.load_dir(runs)))
    return B.merge_runs(layers)


def load_pres(d: Path) -> dict[str, dict[str, Any]]:
    out = {}
    names = [f"O-s{k}" for k in W.SEEDS] + ["O", "I1", "I2"]
    for nm in names:
        p = d / f"precompute_{nm}.json"
        if p.is_file():
            out[nm] = json.loads(p.read_text(encoding="utf-8"))
    p = d / "approx.json"
    if p.is_file():
        out["approx"] = json.loads(p.read_text(encoding="utf-8"))
    return out


# ---------------------------------------------------------------- 판단

def gstats(T: Mapping[Key, float], m: str, base: str, b: int, scen: Sequence[str] = VAL) -> dict[str, Any]:
    return B.stat(A.rel(T, scen, POOL, m, base, b), len(scen))


def judge_case(T: Mapping[Key, float]) -> dict[str, Any]:
    """보유 조건에서 800 · 2,000 모두 F4에 못지않은 것 중 가장 싼 것. O → I1 → I2, 모두 실패면 F4(처음부터 다시)."""
    st = {m: {b: gstats(T, m, BASE, b) for b in BUDGETS} for m in UPD}
    h = {m: {b: gstats(T, m, K, b) for b in BUDGETS} for m in (*UPD, BASE)}
    ok: dict[str, bool | None] = {}
    for m in UPD:
        ok[m] = all(st[m][b]["noninf"] for b in BUDGETS) if all(st[m][b]["complete"] for b in BUDGETS) else None
    pick: str | None
    if ok["O"] is None:
        pick = None
    elif ok["O"]:
        pick = "O"
    elif ok["I1"]:
        pick = "I1"
    elif ok["I1"] is None:
        pick = None
    elif ok["I2"]:
        pick = "I2"
    elif ok["I2"] is None:
        pick = None
    else:
        pick = "F4"
    return {"stats": st, "h": h, "ok": ok, "pick": pick, "text": TEXT[pick]}


def judge_missing(T: Mapping[Key, float]) -> dict[str, Any]:
    """미보유 조건(관찰): v<k>n × 800에서 G = X / F4 − 1. 갱신 판(I1 · I2) G 중앙이 O보다 1% 넘게 낮으면 손해."""
    st = {m: gstats(T, m, BASE, MISS_BUDGET, VALN) for m in UPD}
    loss = {}
    for m in ("I1", "I2"):
        a, o = st[m]["median"], st["O"]["median"]
        loss[m] = None if a is None or o is None or not (st[m]["complete"] and st["O"]["complete"]) else a < o - MISS_LOSS
    return {"stats": st, "loss": loss}


def final_rows(runs: Mapping[Key, Mapping[str, Any]], new: Sequence[str]) -> list[dict[str, Any]]:
    """최종 5덱의 새 니케 수 · F4와 공유 니케 수(같은 시나리오 · 예산) — 시나리오 중앙."""
    rows = []
    for scen, b_list in ((VAL, BUDGETS), (VALN, (MISS_BUDGET,))):
        for m in (*UPD, BASE):
            for b in b_list:
                nn, sh = [], []
                for s in scen:
                    r = runs.get((s, POOL, m, b))
                    if r is None:
                        continue
                    nn.append(W.new_count(r["final"], new))
                    f = runs.get((s, POOL, BASE, b))
                    if f is not None and m != BASE:
                        sh.append(R10_shared(r["final"], f["final"]))
                if nn:
                    rows.append({"cond": "미보유" if scen is VALN else "보유", "method": m, "budget": b, "n": len(nn),
                                 "new_med": A.med(nn), "shared_f4_med": A.med(sh) if sh else None})
    return rows


def R10_shared(a: Mapping[str, Any], b: Mapping[str, Any]) -> int:
    return W.R10.shared_nikkes([sq for _, sq in a["squads"]], [sq for _, sq in b["squads"]])


def missing_runs(runs: Mapping[Key, Any]) -> list[str]:
    out = [f"{s}_P177_{m}_{b}" for m in UPD for b in BUDGETS for s in VAL if (s, POOL, m, b) not in runs]
    out += [f"{s}_P177_{m}_{MISS_BUDGET}" for m in (*UPD, BASE) for s in VALN if (s, POOL, m, MISS_BUDGET) not in runs]
    return out


def analyze_case(case: str, runs: Mapping[Key, Mapping[str, Any]], pres: Mapping[str, Mapping[str, Any]],
                 meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    new = W.removed(case)
    T = Z.totals(runs)
    by_seed = {s: {m: {b: T.get((s, POOL, m, b)) for b in BUDGETS} for m in (K, BASE, *UPD)} for s in VAL}
    by_seed_n = {s: {m: T.get((s, POOL, m, MISS_BUDGET)) for m in (BASE, *UPD)} for s in VALN}
    return {"case": case, "removed": list(new), "n_new": len(new), "judge": judge_case(T), "missing": judge_missing(T),
            "finals": final_rows(runs, new), "pre": pre_rows(pres), "approx": pres.get("approx", {}).get("vs_O"),
            "i2": (pres.get("I2") or {}).get("update"), "by_seed": by_seed, "by_seed_n": by_seed_n,
            "missing_runs": missing_runs(runs), "meta": dict(meta or {})}


def pre_rows(pres: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for nm, d in pres.items():
        rows.append({"name": nm, "evals": d.get("evals"), "sims": d.get("sims"), "comps": d.get("comps"),
                     "final": d["final"]["total"], "core": d.get("core"), "new_decks": d.get("new_decks"),
                     "t195": d.get("t195"), "sets": [min(d["set_totals"]), max(d["set_totals"])] if d.get("set_totals") else None,
                     "upd_evals": (d.get("update") or {}).get("evals") if nm == "I2" else
                     (13210 if nm == "I1" else 0 if nm == "O" else None)})
    return rows


def aggregate(per: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """취합: 메타를 바꾸는 C1~C4에서 I1 · I2가 각각 통과한 경우 수 → 기본 갱신 절차(README §판단 기준 취합 표)."""
    meta = [c for c in W.META_CASES]
    have = [c for c in meta if c in per]
    ok = {m: {c: per[c]["judge"]["ok"][m] for c in have} for m in UPD}
    if len(have) < len(meta) or any(v is None for m in ("I1", "I2") for v in ok[m].values()):
        rule, text, nxt = None, f"판단 불가 — 경우가 모자란다({len(have)}/{len(meta)} 경우, 판단 불가 포함)", "남은 경우를 마저 돌린다"
    elif all(ok["I1"].values()):
        rule, text, nxt = "I1", "I1(새 시드 하나 이어 붙이기)을 기본 갱신 절차로 채택", "랭커 자료가 있을 때 K 대신 PB15 · 큐브(2단계)"
    elif all(ok["I2"].values()):
        rule, text, nxt = "I2", "I2(신캐 집중 이어 붙이기)를 기본 갱신 절차로 채택", "랭커 자료가 있을 때 K 대신 PB15 · 큐브(2단계)"
    elif not any(ok["I1"].values()) and not any(ok["I2"].values()):
        rule, text, nxt = "F4", "기본 갱신 = 처음부터 다시(F4)", "이어 붙이기 개선(짝 정보 설계)을 다음 회차 후보로"
    else:
        passed = [c for c in have if ok["I1"][c] or ok["I2"][c]]
        failed = [c for c in have if c not in passed]
        bound = ", ".join(f"{c}(n={per[c]['n_new']})" for c in passed) + " 통과 / " + \
            ", ".join(f"{c}(n={per[c]['n_new']})" for c in failed) + " 실패"
        rule, text, nxt = "split", f"일부만 통과 — 경우 종류로 나눈 규칙(경계: {bound})", "경계 근처 경우를 더 확인"
    c5 = per.get("C5")
    c5_note = None
    if c5 is not None and c5["judge"]["ok"]["O"] is not None:
        c5_note = "C5 O 통과 — 메타 밖 신캐는 갱신 불필요(예상대로)" if c5["judge"]["ok"]["O"] else \
            "C5 O 실패 — 메타 밖 신캐도 갱신 필요(예상과 다름)"
    loss = {c: {m: p["missing"]["loss"][m] for m in ("I1", "I2")} for c, p in per.items()}
    return {"cases": list(per), "ok": ok, "rule": rule, "text": text, "next": nxt, "c5": c5_note, "missing_loss": loss,
            "o_all": all(ok["O"].get(c) for c in meta) if len(have) == len(meta) else None}


# ---------------------------------------------------------------- 출력

f, pct, srow = Z.f, Z.pct, Z.srow


def yn(x: Any) -> str:
    return "—" if x is None else ("O" if x else "×")


def render_case(a: Mapping[str, Any]) -> str:
    c = a["case"]
    L = [f"# 실험 15 경우 {c} 결과 (analyze15.py 생성)", "", f"- 새 니케({a['n_new']}명): {' · '.join(a['removed'])}"]
    L += [f"- {k}: {v}" for k, v in a["meta"].items()] + [""]
    L += ["## 사전 계산 (사전 계산 계정, 억)", "",
          "| 판 | 평가 | 시뮬 | 갱신 평가 | 구성 | 최선 5덱 | 뼈대 | 새 니케 든 덱 | T195 | 8벌 |", "|---|---:|---:|---:|---:|---:|:-:|---:|---:|---|"]
    for r in a["pre"]:
        sets = f"{r['sets'][0]:.1f}~{r['sets'][1]:.1f}" if r["sets"] else "—"
        n = lambda x: "—" if x is None else f"{x:,}"  # noqa: E731
        L.append(f"| {r['name']} | {n(r['evals'])} | {n(r['sims'])} | {n(r['upd_evals'])} | {n(r['comps'])} | {f(r['final'])} | "
                 f"{yn(r['core'])} | {n(r['new_decks'])} | {n(r['t195'])} | {sets} |")
    if a["approx"]:
        x = a["approx"]
        L += ["", f"걸러 낸 근사(관찰): O 대비 {x['diff']:+.2f}억 · 공유 니케 {x['shared_nikkes']}명 · 공유 덱 {x['shared_decks']}개"]
    if a["i2"]:
        u = a["i2"]
        L += ["", "I2 단계별 평가: " + " · ".join(f"{s['what'][3:]} {s['evals']:,}" for s in u["stages"])
              + f" (합 {u['evals']:,}, 시뮬 {u['sims']:,}, 킥 {len(u.get('kicks', []))}회)"]
    j = a["judge"]
    L += ["", "## 판단 — 보유 조건 (F4 대비 G: 중앙 (−3% 밑 개수) [최소 ~ 최대] 판정)", "",
          "| 기호 | 800 | 2,000 | 통과 |", "|---|---|---|:-:|"]
    for m in UPD:
        L.append(f"| **{m}** | {srow(j['stats'][m][800])} | {srow(j['stats'][m][2000])} | {yn(j['ok'][m])} |")
    L += ["", "K177 대비 H(보조):", "", "| 기호 | 800 | 2,000 |", "|---|---|---|"]
    for m in (*UPD, BASE):
        L.append(f"| {m} | {srow(j['h'][m][800])} | {srow(j['h'][m][2000])} |")
    L += ["", f"**경우 판단: {j['text']}**", "", "## 미보유 조건 (관찰, v<k>n × 800, F4 대비 G)", "", "| 기호 | 800 |", "|---|---|"]
    ms = a["missing"]
    for m in UPD:
        L.append(f"| {m} | {srow(ms['stats'][m])} |")
    L += ["", "미보유 계정 손해(G 중앙이 O보다 1% 넘게 낮음): " + ", ".join(f"{m} {yn(v)}" for m, v in ms["loss"].items())]
    L += ["", "## 최종 5덱 — 새 니케 수 · F4와 공유 니케 수 (시나리오 중앙)", "", "| 조건 | 기호 | 예산 | n | 새 니케 | F4 공유 |",
          "|---|---|---:|---:|---:|---:|"]
    for r in a["finals"]:
        L.append(f"| {r['cond']} | {r['method']} | {r['budget']:,} | {r['n']} | {f(r['new_med'])} | {f(r['shared_f4_med'])} |")
    cols = (K, BASE, *UPD)
    L += ["", "## 시나리오별 최종 5덱 합(억)", "",
          "| 시나리오 | " + " | ".join(f"{m} {b}" for m in cols for b in BUDGETS) + " |", "|---|" + "---:|" * (2 * len(cols))]
    for s, row in a["by_seed"].items():
        L.append(f"| {s} | " + " | ".join(f(row[m][b]) for m in cols for b in BUDGETS) + " |")
    L += ["", "| 미보유 | " + " | ".join(f"{m} 800" for m in (BASE, *UPD)) + " |", "|---|" + "---:|" * 4]
    for s, row in a["by_seed_n"].items():
        L.append(f"| {s} | " + " | ".join(f(row[m]) for m in (BASE, *UPD)) + " |")
    if a["missing_runs"]:
        mr = a["missing_runs"]
        L += ["", f"빠진 실행 {len(mr)}개: {', '.join(mr[:12])}{' …' if len(mr) > 12 else ''}"]
    return "\n".join(L) + "\n"


def render_all(per: Mapping[str, Mapping[str, Any]], g: Mapping[str, Any]) -> str:
    L = ["# 실험 15 취합 결과 (analyze15.py 생성)", "", "## 경우별 판단 (보유 조건, F4 대비 800 · 2,000 모두 못지않은가)", "",
         "| 경우 | 새 니케 | O | I1 | I2 | 판단 | O G 중앙 800 / 2,000 | I1 | I2 | 미보유 손해 I1 · I2 |",
         "|---|---:|:-:|:-:|:-:|---|---|---|---|---|"]
    for c, a in per.items():
        j = a["judge"]
        g2 = lambda m: f"{pct(j['stats'][m][800]['median'])} / {pct(j['stats'][m][2000]['median'])}"  # noqa: E731
        ls = a["missing"]["loss"]
        L.append(f"| {c} | {a['n_new']} | {yn(j['ok']['O'])} | {yn(j['ok']['I1'])} | {yn(j['ok']['I2'])} | {j['text']} | "
                 f"{g2('O')} | {g2('I1')} | {g2('I2')} | {yn(ls['I1'])} · {yn(ls['I2'])} |")
    L += ["", f"## 취합 (C1~C4): {g['text']}", "", f"- 다음 방향(사전 등록 표): {g['next']}"]
    if g["c5"]:
        L.append(f"- {g['c5']}")
    if g.get("o_all"):
        L.append("- C1~C4 모두 O 통과 — 이 범위의 신캐는 갱신 없이 계정 탐색만으로 편입된다")
    return "\n".join(L) + "\n"


def write_case(case: str, runs_dir: Path | None = None, out: Path | None = None) -> dict[str, Any]:
    d = W.log_dir(case)
    runs = load_runs(d, runs_dir)
    meta_p = d / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.is_file() else None
    a = analyze_case(case, runs, load_pres(d), meta)
    (out or d.parent / "results.md").write_text(render_case(a), encoding="utf-8")
    if d.is_dir():
        (d / "analysis.json").write_text(json.dumps(a, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return a


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--case", choices=tuple(W.CASES))
    ap.add_argument("--runs", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.case:
        a = write_case(args.case, args.runs, args.out)
        print(json.dumps({"case": a["case"], "verdict": a["judge"]["text"], "ok": a["judge"]["ok"],
                          "loss": a["missing"]["loss"], "missing": len(a["missing_runs"])}, ensure_ascii=False))
        return 0
    per = {}
    for c in W.CASES:
        if (W.log_dir(c) / "val_summary.jsonl").is_file():
            per[c] = write_case(c)
    g = aggregate(per)
    (args.out or HERE / "results.md").write_text(render_all(per, g), encoding="utf-8")
    (HERE / "run_log").mkdir(exist_ok=True)
    (HERE / "run_log" / "analysis.json").write_text(json.dumps({"aggregate": g, "cases": {c: a["judge"] for c, a in per.items()}},
                                                               ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"rule": g["rule"], "text": g["text"], "c5": g["c5"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
