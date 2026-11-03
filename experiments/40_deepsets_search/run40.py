"""실험 40 — 2단계(시뮬): D2(미리 학습 + 이어 학습 Deep Sets)를 실험 39 틀에 판 d로 끼워 검증 시즌 S23~S32에서 base와 비교. README §2단계.

    source .cache/evaluators.env && python -I experiments/40_deepsets_search/run40.py run --season 23 --part B_s0,B_s1
      시즌 · 부분을 쉼표로 여럿. 끝난 부분은 건너뛴다. RUN40_BUDGET_MIN(분)이 지나면 새 부분을 시작하지 않는다.
    source .cache/evaluators.env && python -I experiments/40_deepsets_search/run40.py dev --season 36 --budget 2000
      개발 시즌(S33~S42) 짧은 시운전 — dev/에 쓴다. 판정에 쓰지 않는다.
    source .cache/evaluators.env && python -I experiments/40_deepsets_search/run40.py check --n 60
      base · d 기록을 부분마다 60덱씩 지금 평가기로 다시 계산해 값이 같은지 → run_log/eval_check.json (analyze 전에)
    python -I experiments/40_deepsets_search/run40.py analyze     # 시뮬 0 → analysis2.json · results2.md (base = 실험 39 기록)

- 판 d는 실험 10 `run_method` G+E에서 **라운드 고르기(`local_round`)의 대리 모델만** 릿지 → D2로 바꾼다. 고르는 규칙(ⓐ 덱 고치기 70 · ⓑ 이웃 30) ·
  설계 · 구성(릿지 그대로) · 킥 · 순서 다듬기 · 예산 · 난수 시드는 base와 같다.
- 구현: base `local_round`를 한 번 「기록용 점수(전부 0)」로 돌려 물어볼 구성을 모으고(계보는 복사본), D2로 한꺼번에 예측한 뒤
  같은 함수를 D2 점수로 다시 돈다 — 물어보는 구성이 점수와 무관해서 고르는 규칙이 base와 글자 그대로 같다.
- D2는 미리 학습 가중치(`run_log/pre_ds.pt`)에서 출발해 세션 기록이 `REFIT`개 늘 때마다 다시 이어 학습한다(1단계와 같은 90 · 10 조기 종료).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics as st
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent


def _load(name: str, path: Path):
    import importlib.util
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R39 = _load("run39", EXPS / "39_bundle_explore" / "run39.py")
A40 = _load("an40", HERE / "an40.py")
run31, R10, R9, R30 = R39.run31, R39.R10, R39.R9, R39.R30
BASE_ROUND = R10.local_round              # 바꿔 끼우기 전 원본

# ---------------------------------------------------------------- 정한 값(README §2단계 사전 등록)
SEASONS, SEEDS, SEED_BUDGET = R39.SEASONS, R39.SEEDS, R39.SEED_BUDGET
DEV_SEASONS = R39.DEV_SEASONS
REFIT = 500                               # 세션 기록이 이만큼 늘면 다시 이어 학습(1단계 「다음 500」과 같은 창)
ARM = "d"
LOG = HERE / "run_log" / ARM
DEV = HERE / "dev"
CHECK = HERE / "run_log" / "eval_check.json"     # run40.py check — 평가기 이름이 다른 기록끼리 값 대조
PARAMS = {"model": "D2", "refit_every": REFIT, "pretrain": "실험 33 P + 넣어 보기 121,373관측(an40.py pretrain)",
          "finetune": {"lr": A40.FT_LR, "max_epochs": A40.MAX_EPOCHS, "patience": A40.PATIENCE, "valid_frac": A40.VALID_FRAC},
          "construct": "릿지 그대로(base와 같음)"}


class Recorder:
    """기록용 점수: 물어본 구성만 모으고 0을 돌려준다."""

    def __init__(self):
        self.asked: set[frozenset] = set()

    def __call__(self, c) -> float:
        self.asked.add(frozenset(c))
        return 0.0


class D2State:
    """한 시드 실행 동안의 D2 — 기록이 REFIT개 늘 때마다 미리 학습 가중치에서 다시 이어 학습하고, 모델이 바뀌기 전까지 예측을 캐시한다."""

    def __init__(self, pre: Any, element: str, tag: str):
        self.pre, self.el, self.tag = pre, element, tag
        self.model, self.n_fit, self.cache = None, -REFIT, {}
        self.refits, self.train_s, self.pred_s, self.predicted = 0, 0.0, 0.0, 0

    def refresh(self, book: Mapping[frozenset, tuple]) -> None:
        if self.model is not None and len(book) - self.n_fit < REFIT:
            return
        t = time.time()
        comps = list(book)
        rng = random.Random(f"exp40-s2-{self.tag}-{len(comps)}")
        va = set(rng.sample(range(len(comps)), max(1, int(round(A40.VALID_FRAC * len(comps))))))
        tr_c = [c for i, c in enumerate(comps) if i not in va]
        va_c = [c for i, c in enumerate(comps) if i in va]
        tr = A40.obs_of(tr_c, [book[c][0] * A40.E8 for c in tr_c], self.el)
        vd = A40.obs_of(va_c, [book[c][0] * A40.E8 for c in va_c], self.el)
        self.model = A40.DSScore(A40.finetune(self.pre, tr, vd), self.el)
        self.n_fit, self.cache = len(comps), {}
        self.refits += 1
        self.train_s += time.time() - t

    def prefill(self, comps) -> None:
        todo = [c for c in comps if c not in self.cache]
        if not todo:
            return
        t = time.time()
        p, _ = self.model.many(todo)
        self.cache.update(zip(todo, (float(x) for x in p)))
        self.pred_s += time.time() - t
        self.predicted += len(todo)

    def __call__(self, c) -> float:
        c = frozenset(c)
        if c not in self.cache:
            self.prefill([c])
        return self.cache[c]


def make_round(state: D2State):
    def local_round(sess: Any, n: int, lineage: set | None, fitf: Any) -> list[tuple]:
        rec = Recorder()
        BASE_ROUND(sess, n, None if lineage is None else set(lineage), lambda book, names: rec)
        state.refresh(sess.book.best)
        state.prefill(rec.asked)
        return BASE_ROUND(sess, n, lineage, lambda book, names: state)
    return local_round


def run_arm(s: int, k: int, budget: int, ev: Any, pre: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    acct = run31.account(s, k)
    state = D2State(pre, run31.season(s)["code"], f"S{s}-s{k}")
    R10.local_round = make_round(state)
    try:
        r, recs, _ = R10.run_method(acct, "G+E", budget, ev, pool=177)
    finally:
        R10.local_round = BASE_ROUND
    out = {"arm": ARM, "params": PARAMS, "season": s, "seed": k, "budget": budget, "evals": r["evals"],
           "seconds": r["seconds"], "best": r["final"]["total"], "errors": r["errors"], "kicks": len(r["kicks"]),
           "history": r["history"], "d2": {"refits": state.refits, "train_s": round(state.train_s, 1),
                                           "pred_s": round(state.pred_s, 1), "predicted": state.predicted}}
    return out, recs


def sdir(s: int) -> Path:
    return LOG / f"S{int(s):02d}"


def cmd_run(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    pre = A40.load_pre()
    t_all, budget = time.time(), os.environ.get("RUN40_BUDGET_MIN")
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        ver = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        for s in [int(x) for x in str(a.season).split(",")]:
            if s not in SEASONS:
                raise SystemExit(f"S{s}는 검증 시즌이 아니다({SEASONS[0]}~{SEASONS[-1]}) — 개발은 dev 명령으로")
            for part in a.part.split(","):
                k = int(part.removeprefix("B_s"))
                pf = sdir(s) / f"part_{part}.json"
                if pf.exists():
                    continue
                if budget and time.time() - t_all > float(budget) * 60:
                    print(json.dumps({"stop": "budget", "minutes": round((time.time() - t_all) / 60, 1)}), flush=True)
                    return 3
                n0, t0 = ev.sim_count, time.time()
                out, recs = run_arm(s, k, SEED_BUDGET, ev, pre)
                run31.write_recs(sdir(s) / f"{part}.jsonl.gz", recs)
                out.update(season=s, part=part, evaluator=ver, sims=ev.sim_count - n0, wall=round(time.time() - t0, 1))
                R39.jdump(pf, out)
                print(json.dumps({k2: v for k2, v in out.items() if k2 not in ("history", "params")}, ensure_ascii=False), flush=True)
    return 0


def cmd_dev(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    if a.season not in DEV_SEASONS:
        raise SystemExit(f"dev는 S{DEV_SEASONS[0]}~S{DEV_SEASONS[-1]}만 — 검증 시즌은 run으로")
    pre = A40.load_pre()
    tag = f"S{a.season}_s{a.seed}_b{a.budget}"
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        n0 = ev.sim_count
        out, recs = run_arm(a.season, a.seed, a.budget, ev, pre)
        out["sims"] = ev.sim_count - n0
    run31.write_recs(DEV / f"{tag}.jsonl.gz", recs)
    out.update(R39.summarize(a.season, R30.book_of(recs)))
    R39.jdump(DEV / f"{tag}.json", out)
    print(json.dumps({k: v for k, v in out.items() if k not in ("history", "params")}, ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 요약(시뮬 0)

def rows_of(root: Path) -> dict[int, dict[str, Any]]:
    out = {}
    for s in SEASONS:
        d = root / f"S{s:02d}"
        parts = {k: R39.jload(d / f"part_B_s{k}.json") for k in SEEDS}
        if any(p is None for p in parts.values()):
            continue
        recs = {k: run31.load_recs(d / f"B_s{k}.jsonl.gz") for k in SEEDS}
        row = {"season": s, **R39.summarize(s, R30.book_of([r for k in SEEDS for r in recs[k]]))}
        row["seed"] = {k: R39.summarize(s, R30.book_of(recs[k])) for k in SEEDS}
        row["sims"] = sum(p["sims"] for p in parts.values())
        row["evaluator"] = sorted({p["evaluator"] for p in parts.values()})
        row["d2"] = {k: parts[k].get("d2") for k in SEEDS}
        out[s] = row
    return out


def analyze() -> dict[str, Any]:
    base = rows_of(R39.LOG / "base")
    arm = rows_of(LOG)
    pair = [(arm[s], base[s]) for s in SEASONS if s in arm and s in base]
    rs = [r["pack"] / b["pack"] - 1 for r, b in pair]
    per_seed = [r["seed"][k]["pack"] / b["seed"][k]["pack"] - 1 for r, b in pair for k in SEEDS]
    noise = [abs(b["seed"][1]["pack"] / b["seed"][0]["pack"] - 1) for b in base.values()]
    names = {"base": sorted({v for _, b in pair for v in b["evaluator"]}), "d": sorted({v for r, _ in pair for v in r["evaluator"]})}
    chk = R39.jload(CHECK)
    out = {"seasons": list(SEASONS), "base": base, "d": arm, "ratio": dict(zip([r["season"] for r, _ in pair], rs)),
           "median": R39.med(rs), "drops": sum(x < R39.DROP for x in rs), "per_seed_median": R39.med(per_seed),
           "G_base": R39.med([b["G"] for _, b in pair]), "G_d": R39.med([r["G"] for r, _ in pair]),
           "visit_base": R39.med([b["visit"] for _, b in pair]), "visit_d": R39.med([r["visit"] for r, _ in pair]),
           "seed_noise_median": R39.med(noise), "evaluator_names": names,
           "value_check": None if chk is None else {k: chk[k] for k in ("evaluator", "parts", "decks", "diff")},
           "verdict": R39.verdict(rs) if len(pair) == len(SEASONS) else f"진행 중 {len(pair)}/{len(SEASONS)}"}
    return out


def write_md(an: Mapping[str, Any]) -> str:
    pct = R39.pct
    L = ["# 실험 40 2단계 결과 표", "", "`run40.py analyze`가 만든다. 값 = 코어 없음 최선 5덱 합(억, 두 시드 기록 합쳐 묶기, 사전 값). base = 실험 39 기준선 기록.", "",
         "| 시즌 | base | d | d/base | 시드 0 · 1 | G base → d | 방문 base → d | D2 다시 학습 · 학습 초(시드 합) |", "|---|---|---|---|---|---|---|---|"]
    for s in an["seasons"]:
        b, r = an["base"].get(s), an["d"].get(s)
        if not (b and r):
            L.append(f"| S{s} | {b['pack']:.1f} |" + " — |" * 6 if b else f"| S{s} |" + " — |" * 7)
            continue
        ps = " · ".join(pct(r["seed"][k]["pack"] / b["seed"][k]["pack"] - 1) for k in SEEDS)
        d2 = [x for x in r["d2"].values() if x]
        L.append(f"| S{s} | {b['pack']:.1f} | {r['pack']:.1f} | {pct(r['pack'] / b['pack'] - 1)} | {ps} | {pct(b['G'])} → {pct(r['G'])} | "
                 f"{pct(b['visit'], 1, False)} → {pct(r['visit'], 1, False)} | {sum(x['refits'] for x in d2)} · {sum(x['train_s'] for x in d2):.0f} |")
    L += ["", f"- 판정(실험 39와 같은 표): **{an['verdict']}** — 시즌 중앙 {pct(an['median'])} · −1% 밑 {an['drops']}시즌 · 시드별 중앙 {pct(an['per_seed_median'])}",
          f"- G 중앙 {pct(an['G_base'])} → {pct(an['G_d'])} · 방문 중앙 {pct(an['visit_base'], 1, False)} → {pct(an['visit_d'], 1, False)}",
          f"- 시드 잡음(base s1 ÷ s0 − 1 절댓값, 시즌 중앙): {pct(an['seed_noise_median'], sign=False)}",
          f"- 평가기 이름: base {', '.join(an['evaluator_names']['base'])} · d {', '.join(an['evaluator_names']['d'])}"]
    vc = an["value_check"]
    L.append("- 값 대조: 안 함(`run40.py check`)" if vc is None else
             f"- 값 대조(`run40.py check`, 평가기 {vc['evaluator']}로 기록을 다시 계산): 부분 {vc['parts']}개 · {vc['decks']}덱 중 다른 값 **{vc['diff']}**")
    return "\n".join(L) + "\n"


def cmd_check(a: argparse.Namespace) -> int:
    """평가기 이름이 섞인 기록(실험 39 base 재개 뒤 · 판 d)이 같은 값인지 — 부분마다 a.n덱을 지금 평가기로 다시 계산해 대조한다.

    카메라 재장전 규칙(`sim.camera_reload_cancel`, nikke-calc-rs 83a6d54)은 요청에 주지 않으면 꺼진다. 이 실험은 주지 않는다.
    """
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    rng = random.Random(f"exp40-check-{a.n}")
    rows = []
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        ver = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        for arm, root in (("base", R39.LOG / "base"), (ARM, LOG)):
            for s in SEASONS:
                for k in SEEDS:
                    d = root / f"S{s:02d}"
                    part = R39.jload(d / f"part_B_s{k}.json")
                    if part is None:
                        continue
                    recs = [r for r in run31.load_recs(d / f"B_s{k}.jsonl.gz") if not r.get("error")]
                    pick = rng.sample(recs, min(a.n, len(recs)))
                    res = ev.evaluate([EvalRequest(list(r["squad"]), boss=None, options=run31.options(s, 0)) for r in pick])
                    bad = [[r["squad"], r["total_damage"], x.total_damage] for r, x in zip(pick, res) if x.total_damage != r["total_damage"]]
                    rows.append({"arm": arm, "season": s, "seed": k, "recorded": part.get("evaluator"), "n": len(pick), "diff": len(bad), "examples": bad[:3]})
                    print(json.dumps({x: rows[-1][x] for x in ("arm", "season", "seed", "recorded", "n", "diff")}, ensure_ascii=False), flush=True)
    out = {"evaluator": ver, "per_part": a.n, "parts": len(rows), "decks": sum(r["n"] for r in rows), "diff": sum(r["diff"] for r in rows), "rows": rows}
    R39.jdump(CHECK, out)
    print(json.dumps({k: out[k] for k in ("evaluator", "parts", "decks", "diff")}, ensure_ascii=False))
    return 0 if out["diff"] == 0 else 1


def cmd_analyze(a: argparse.Namespace) -> int:
    an = analyze()
    R39.jdump(HERE / "analysis2.json", an)
    md = write_md(an)
    (HERE / "results2.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--season", required=True)
    r.add_argument("--part", default="B_s0,B_s1")
    r.add_argument("--jobs", type=int, default=None)
    d = sub.add_parser("dev")
    d.add_argument("--season", type=int, required=True)
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--budget", type=int, default=2000)
    d.add_argument("--jobs", type=int, default=None)
    sub.add_parser("analyze")
    c = sub.add_parser("check")
    c.add_argument("--n", type=int, default=60)
    c.add_argument("--jobs", type=int, default=None)
    a = p.parse_args(argv)
    return {"run": cmd_run, "dev": cmd_dev, "analyze": cmd_analyze, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
