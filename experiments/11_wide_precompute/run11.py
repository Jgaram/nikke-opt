"""실험 11 — 넓은 풀에서 랭커 없는 사전 계산 실행기 (README §후보 · §계정 탐색).

    source .cache/evaluators.env && python experiments/11_wide_precompute/run11.py precompute --which PB --out <dir>
    source .cache/evaluators.env && python experiments/11_wide_precompute/run11.py precompute --which PN --out <dir>
    source .cache/evaluators.env && python experiments/11_wide_precompute/run11.py precompute --which PM --out <dir>
    source .cache/evaluators.env && python experiments/11_wide_precompute/run11.py search --set val --out <dir> --pre <dir>
        [--methods PB15,PB30,PN,PM,P,K] [--budgets 800,2000] [--only v1,v2] [--workers 4]

- 사전 계산 계정은 실험 10과 같다(SSR 177명 전원 보유 · 전원 상). 결과는 `<dir>/precompute_<기호>.json`(실험 10 형식 + `stages`).
  - `PB`: 177명 G+E를 예산 15,000 → 30,000 차례로(앞부분이 같아 캐시를 함께 쓴다) → `PB15` · `PB30`.
  - `PN`: 1단계 = 실험 10 P177 사전 계산 기록(재사용), 니케마다 「그 니케가 든 최고 스쿼드 값」 순으로 60명(단계별 최소 인원)
    → 2단계 = 좁힌 60명 G+E 5,000.
  - `PM`: PN 뒤 3단계 = 177명 계정에서 PN 출발 옮기기 + L0 5,000(계정의 P와 같은 절차).
- 계정 탐색은 모두 실험 10의 P(사전 계산 8벌 옮기기 + 177명 L0)이고 사전 계산만 다르다. `P`는 실험 10 P177 사전 계산,
  `K`는 실험 10의 K(랭커 30명 옮기기 + 177명 L0). 요약 형식은 실험 10 SESSIONS.md와 같고 `method`만 위 기호다.
- 대리 모델: 평가한 구성이 6,000개 이하면 실험 10 `DualFit`(같은 해, 실험 10 재현), 넘으면 같은 릿지를 전처리 공액 기울기로 푼다(`CGFit`).
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
EXP10 = HERE.parent / "10_rankerless_start"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R10 = sys.modules.get("run10") or _load("run10", EXP10 / "run10.py")
R9, S4 = R10.R9, R10.S4
E8 = R10.E8
P177 = R10.P177
BURST = R10.BURST_ALL

EXP10_LOG = EXP10 / "run_log"
DUAL_MAX = 6000            # 이 수 이하의 구성은 정확한 쌍대형 풀이(DualFit)
CG_TOL = 1e-10             # 공액 기울기 상대 잔차
PB_BUDGETS = (15000, 30000)
NARROW_M = 60
NARROW_MIN = {"1": 10, "2": 10, "3": 20}
STAGE_BUDGET = 5000        # PN 2단계 · PM 3단계
PRE_SETS = R10.PRE_SETS
METHODS = ("PB15", "PB30", "PN", "PM", "P", "K")
PRE_FILE = {"PB15": "precompute_PB15.json", "PB30": "precompute_PB30.json", "PN": "precompute_PN.json",
            "PM": "precompute_PM.json"}
BUDGETS = (800, 2000)


# ---------------------------------------------------------------- 대리 모델 (큰 표본)

class CGFit:
    """실험 4 `fit`(니케 + 짝 릿지, λ_u · λ_p, 절편 벌점 없음)과 같은 목적을 원형으로 푼다. 특성 = 니케 N + 모든 짝 N(N−1)/2
    (평가한 구성에 없는 짝의 해는 0이라 실험 4와 같다). 절편은 DualFit과 같은 두 번 풀이로 뺀다. 이전 해에서 다시 출발한다(같은 Book)."""

    def __init__(self, book: Any, names: Sequence[str]):
        names = list(names)
        N = len(names)
        self.ni = {n: i for i, n in enumerate(names)}
        self.N = N
        p = N + N * (N - 1) // 2
        comps = list(book.best)
        idx = np.empty((len(comps), 15), dtype=np.int64)
        for r, c in enumerate(comps):
            ii = sorted(self.ni[n] for n in c)
            row = list(ii)
            for a in range(5):
                for b in range(a + 1, 5):
                    row.append(self._pair(ii[a], ii[b]))
            idx[r] = row
        y = np.array([book.best[c][0] for c in comps])
        lam = np.r_[np.full(N, S4.LAM_U), np.full(p - N, S4.LAM_P)]
        flat = idx.ravel()
        diag = np.bincount(flat, minlength=p) + lam

        def A(w):
            return np.bincount(flat, weights=np.repeat(w[idx].sum(1), 15), minlength=p) + lam * w

        def XT(r):
            return np.bincount(flat, weights=np.repeat(r, 15), minlength=p)

        warm = getattr(book, "_cg_warm", None)
        if warm is None or warm[0] != tuple(names):
            warm = (tuple(names), np.zeros(p), np.zeros(p))
        u = _pcg(A, XT(y), diag, warm[1])
        v = _pcg(A, XT(np.ones(len(comps))), diag, warm[2])
        book._cg_warm = (tuple(names), u, v)
        Xu, Xv = u[idx].sum(1), v[idx].sum(1)
        self.b = float((y - Xu).sum() / (len(comps) - Xv.sum()))
        w = u - self.b * v
        self.u = w[:N].copy()
        W = np.zeros((N, N))
        iu = np.triu_indices(N, 1)
        W[iu] = w[N:]
        self.W = W + W.T

    def _pair(self, i: int, j: int) -> int:
        N = self.N
        return N + i * N - i * (i + 1) // 2 + (j - i - 1)

    def __call__(self, c: Iterable[str]) -> float:
        ii = [self.ni[n] for n in c]
        if not ii:
            return self.b
        return float(self.b + self.u[ii].sum() + self.W[np.ix_(ii, ii)].sum() / 2)

    def add_scores(self, cur: Sequence[str], opts: Sequence[str]) -> list[float]:
        base = self(cur)
        ci = [self.ni[n] for n in cur]
        oi = [self.ni[n] for n in opts]
        add = self.u[oi] + (self.W[np.ix_(ci, oi)].sum(0) if ci else 0.0)
        return list(base + add)


def _pcg(A: Callable, rhs: np.ndarray, diag: np.ndarray, x0: np.ndarray, tol: float = CG_TOL,
         maxit: int = 20000) -> np.ndarray:
    """야코비 전처리 공액 기울기."""
    x = x0.copy()
    r = rhs - A(x)
    nb = np.linalg.norm(rhs) or 1.0
    if np.linalg.norm(r) <= tol * nb:
        return x
    z = r / diag
    d = z.copy()
    rz = r @ z
    for _ in range(maxit):
        Ad = A(d)
        a = rz / (d @ Ad)
        x += a * d
        r -= a * Ad
        if np.linalg.norm(r) <= tol * nb:
            break
        z = r / diag
        rz2 = r @ z
        d = z + (rz2 / rz) * d
        rz = rz2
    return x


def fit_big(book: Any, names: Sequence[str]):
    return R10.DualFit(book, names) if len(book.best) <= DUAL_MAX else CGFit(book, names)


# 실험 10 기법이 177명 풀에서 이 모델을 쓰게 한다. 계정 탐색(≤ 2,000평가)은 DualFit 그대로다(실험 10 재현).
R10.fit_for = lambda pool: S4.fit if pool == 60 else fit_big
# 대안 (b)(니케 공유 20명 이하)는 이번 회차에 계산하지 않는다 — 출발 덱이 강해지면 분기 한정이 실행 시간의 90% 넘게 쓴다(README §개발 확인).
R10.pack_alt20 = lambda *a, **k: (0.0, [])


# ---------------------------------------------------------------- 계정

class RosterAccount:
    """사전 계산 계정: 주어진 니케 전원 보유 · 전원 상(랭커 없는 로스터 — 버스트 단계만)."""

    def __init__(self, sid: str, names: Iterable[str], pool: int):
        self.id, self.name, self.pool = sid, f"사전 계산 {sid}(전원 보유 · 상)", pool
        self.missing: list[str] = []
        self.owned = {n: {"burst": BURST[n]} for n in sorted(names)}
        self.names = sorted(self.owned)
        self.tier = {n: "상" for n in self.owned}
        self.options: dict[str, Any] = {}


def pre_account177() -> Any:
    """실험 10 P177 사전 계산과 같은 계정(id · 시드가 같아 앞부분이 재현된다)."""
    return R10.Account10(R10.pre_scenario(), pool=177, rankerless=True)


# ---------------------------------------------------------------- 좁히기

def narrow(best: Mapping[frozenset, tuple[float, tuple]], m: int = NARROW_M,
           mins: Mapping[str, int] = NARROW_MIN) -> list[str]:
    """니케 점수 = 그 니케가 든 평가 구성의 최고 값(동점은 이름). 단계별 최소 인원을 점수 순으로 먼저 채우고 나머지를 점수 순으로."""
    score: dict[str, float] = {}
    for c, (v, _) in best.items():
        for n in c:
            if v > score.get(n, float("-inf")):
                score[n] = v
    order = sorted(score, key=lambda n: (-score[n], n))
    pick: list[str] = []
    for s, q in mins.items():
        pick += [n for n in order if BURST[n] == s][:q]
    for n in order:
        if len(pick) >= m:
            break
        if n not in pick:
            pick.append(n)
    return sorted(pick)


def load_records(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def combined_coef(inner: Mapping[str, float], outer: Mapping[str, float]) -> dict[str, float]:
    """옮기기 대체 순서: 좁힌 니케(2단계 계수 순)가 먼저, 나머지는 그 뒤에 1단계 계수 순."""
    lo = min(inner.values())
    hi = max(outer.values())
    out = dict(inner)
    for n, v in outer.items():
        if n not in inner:
            out[n] = lo - 1.0 - (hi - v)
    return out


# ---------------------------------------------------------------- 사전 계산

def extract(sess: Any, acct: Any, fitf: Callable) -> dict[str, Any]:
    """실험 10 `precompute`의 끝부분: 덱 2개 이하만 공유하는 최선 5덱 8벌 + 마지막 릿지의 니케 계수."""
    sets, totals, avoid = [], [], []
    for _ in range(PRE_SETS):
        v, ch = R9.pack_vals(sess.book.best, avoid=avoid)
        if not ch:
            break
        sets.append([list(sq) for _, sq in ch])
        totals.append(v)
        avoid.append({frozenset(sq) for _, sq in ch})
    score = fitf(sess.book, acct.names)
    base = score(frozenset())
    coef = {n: score(frozenset([n])) - base for n in acct.names}
    return {"sets": sets, "set_totals": totals, "coef": coef}


def stage_rec(what: str, summ: Mapping[str, Any], sims: int) -> dict[str, Any]:
    return {"what": what, "budget": summ["budget"], "evals": summ["evals"], "sims": sims, "seconds": summ["seconds"],
            "best": summ["final"]["total"], "history": summ["history"], "kicks": summ["kicks"]}


def pre_out(name: str, stages: Sequence[Mapping[str, Any]], ext: Mapping[str, Any], summ: Mapping[str, Any],
            **extra: Any) -> dict[str, Any]:
    return {"name": name, "pool": 177, "budget": sum(s["budget"] for s in stages),
            "evals": sum(s["evals"] for s in stages), "sims": sum(s["sims"] for s in stages),
            "seconds": round(sum(s["seconds"] for s in stages), 1), **ext, "final": summ["final"],
            "history": summ["history"], "kicks": summ["kicks"], "stages": list(stages), **extra}


def run_pb(ev: Any, budget: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    acct = pre_account177()
    sims0 = ev.sim_count
    summ, recs, sess = R10.run_method(acct, "G+E", budget, ev, pool=177)
    st = stage_rec(f"177명 G+E {budget}", summ, ev.sim_count - sims0)
    return pre_out(f"PB{budget // 1000}", [st], extract(sess, acct, fit_big), summ), recs


def stage1() -> tuple[dict[str, Any], dict[frozenset, tuple[float, tuple]]]:
    """실험 10 P177 사전 계산(177명 G+E 5,000)의 기록 — 다시 돌리지 않고 비용만 옮긴다."""
    pre = json.loads((EXP10_LOG / "precompute_P177.json").read_text(encoding="utf-8"))
    best = R9.book_of(load_records(EXP10_LOG / "precompute_P177.jsonl.gz"))
    st = {"what": "실험 10 P177 사전 계산(재사용)", "budget": pre["budget"], "evals": pre["evals"], "sims": pre["sims"],
          "seconds": pre["seconds"], "best": pre["final"]["total"], "history": pre["history"], "kicks": pre["kicks"]}
    return dict(st, coef=pre["coef"]), best


def run_pn(ev: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    st1, best1 = stage1()
    coef1 = st1.pop("coef")
    names = narrow(best1)
    acct = RosterAccount("pre-N60", names, pool=60)
    sims0 = ev.sim_count
    summ, recs, sess = R10.run_method(acct, "G+E", STAGE_BUDGET, ev, pool=60)
    st2 = stage_rec("좁힌 60명 G+E 5,000", summ, ev.sim_count - sims0)
    ext = extract(sess, acct, S4.fit)
    ext["coef_inner"] = ext["coef"]
    ext["coef"] = combined_coef(ext["coef_inner"], coef1)
    return pre_out("PN", [st1, st2], ext, summ, narrowed=names), recs


def run_pm(ev: Any, pn: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    acct = pre_account177()
    acct.id = "pre-M"
    sims0 = ev.sim_count
    summ, recs, sess = R10.run_method(acct, "P", STAGE_BUDGET, ev, pre=pn, pool=177)
    st3 = stage_rec("177명 PN 옮기기 + L0 5,000", summ, ev.sim_count - sims0)
    return pre_out("PM", [*pn["stages"], st3], extract(sess, acct, fit_big), summ, narrowed=pn["narrowed"]), recs


def write_pre(out: Path, name: str, data: Mapping[str, Any], recs: Sequence[Mapping[str, Any]], ev: Any) -> None:
    data = dict(data, evaluator=f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}")
    with gzip.open(out / f"precompute_{name}.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / f"precompute_{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"pre": name, "evals": data["evals"], "sims": data["sims"], "s": data["seconds"],
                      "best": round(data["final"]["total"], 2), "sets": [round(t, 1) for t in data["set_totals"]]},
                     ensure_ascii=False), flush=True)


def cmd_precompute(args: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    args.out.mkdir(parents=True, exist_ok=True)
    ev = make_evaluator()
    with ev:
        if args.which == "PB":
            for b in PB_BUDGETS:
                name = f"PB{b // 1000}"
                if not (args.out / PRE_FILE[name]).exists():
                    data, recs = run_pb(ev, b)
                    write_pre(args.out, name, data, recs, ev)
        elif args.which == "PN":
            if not (args.out / PRE_FILE["PN"]).exists():
                data, recs = run_pn(ev)
                write_pre(args.out, "PN", data, recs, ev)
        else:
            pn = json.loads((args.out / PRE_FILE["PN"]).read_text(encoding="utf-8"))
            if not (args.out / PRE_FILE["PM"]).exists():
                data, recs = run_pm(ev, pn)
                write_pre(args.out, "PM", data, recs, ev)
    return 0


# ---------------------------------------------------------------- 계정 탐색

def load_pre(method: str, pre_dir: Path) -> dict[str, Any] | None:
    if method == "K":
        return None
    if method == "P":
        return json.loads((EXP10_LOG / "precompute_P177.json").read_text(encoding="utf-8"))
    return json.loads((pre_dir / PRE_FILE[method]).read_text(encoding="utf-8"))


def run_account(sc_: Mapping[str, Any], method: str, budget: int, ev: Any, pre: Mapping[str, Any] | None):
    acct = R10.Account10(sc_, pool=177, rankerless=method != "K")
    summ, recs, _ = R10.run_method(acct, "K" if method == "K" else "P", budget, ev, pre=pre, pool=177)
    summ["method"] = method
    summ.pop("alt20", None)
    return summ, recs


def cmd_search(args: argparse.Namespace) -> int:
    scs = R10.scenarios(args.set)
    if args.only:
        want = set(args.only.split(","))
        scs = [s for s in scs if s["id"] in want]
    methods = args.methods.split(",")
    assert all(m in METHODS for m in methods), methods
    budgets = [int(b) for b in args.budgets.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    # 대안 (b)(니케 공유 20명 이하)는 이번 회차에 계산하지 않는다 — 출발 덱이 강해지면 분기 한정이 실행 시간의 90% 넘게 쓴다(README).
    R10.pack_alt20 = lambda *a, **k: (0.0, [])
    pres = {m: load_pre(m, args.pre or args.out) for m in methods}
    tasks = [(s, m, b) for b in sorted(budgets, reverse=True) for s in scs for m in methods
             if not (args.out / f"{R10.run_name(s['id'], 177, m, b)}.json").exists()]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()
    lock = threading.Lock()

    def work(task):
        s, m, b = task
        summ, recs = run_account(s, m, b, ev, pres[m])
        name = R10.run_name(s["id"], 177, m, b)
        R10.write_run(args.out, name, summ, recs)
        with lock:
            print(json.dumps({"run": name, "pack": round(summ["final"]["total"], 2), "evals": summ["evals"],
                              "s": summ["seconds"], "t": round(time.time() - t0), "sims": ev.sim_count},
                             ensure_ascii=False), flush=True)

    with ev:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for f in [pool.submit(work, t) for t in tasks]:
                f.result()
        print(f"실행 {len(tasks)}개 · 시뮬 {ev.sim_count}회 · 캐시 {ev.cache_hits}회 · {time.time() - t0:.0f}초 · "
              f"평가기 {ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("precompute")
    p.add_argument("--which", choices=("PB", "PN", "PM"), required=True)
    p.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("search")
    s.add_argument("--set", choices=("dev", "val"), required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--pre", type=Path)
    s.add_argument("--methods", default=",".join(METHODS))
    s.add_argument("--budgets", default=",".join(map(str, BUDGETS)))
    s.add_argument("--only")
    s.add_argument("--workers", type=int, default=4)
    c = sub.add_parser("collect")
    c.add_argument("--runs", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--name", required=True)
    args = ap.parse_args(argv)
    return {"precompute": cmd_precompute, "search": cmd_search, "collect": R10.cmd_collect}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
