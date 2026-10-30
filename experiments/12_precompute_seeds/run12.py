"""실험 12 — 사전 계산의 시드 강건성과 정체 줄이기 실행기 (README §후보).

    source .cache/evaluators.env && python experiments/12_precompute_seeds/run12.py precompute --which PB15s1 --out <dir>
        (기호: PB15s<k> · PBD · PBS · PBDs<k> · PBSs<k>, 쉼표로 여럿)
    python experiments/12_precompute_seeds/run12.py truncate --which PBD --at 10000 --pre <dir>   # → precompute_PBD10k.json
    source .cache/evaluators.env && python experiments/12_precompute_seeds/run12.py search --set val --out <dir> --pre <dir>
        --methods PB15s1,PB15s2,PB15s3 [--budgets 800,2000] [--only v1,v2] [--workers 4]
    python experiments/12_precompute_seeds/run12.py collect --runs <dir> --out <dir> --name val

- 사전 계산은 실험 11 PB15와 같은 계정(177명 전원 보유 · 상) · 예산 15,000이다. 시드는 계정 id(`pre` · `pre-s<k>`)로 바뀐다.
  - `PB15s<k>`: 실험 10 `run_method(G+E)` 그대로, 시드만 다르다. `PB15`(s0)는 실험 11 기록.
  - `PBD`: 정체 3라운드 · 킥 뒤 계보 반 + 전체 최선 반. `PBS`: 킥 없이 라운드마다 L0 70% + 등반자 3개 30%.
- 계정 탐색은 실험 11 `run_account`(사전 계산 8벌 옮기기 + 177명 L0) 그대로다. 요약 형식은 실험 10 SESSIONS.md와 같고 `method`만 위 기호다.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import random
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXP11 = HERE.parent / "11_wide_precompute"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R11 = sys.modules.get("run11") or _load("run11", EXP11 / "run11.py")
R10, R9, S4, R2 = R11.R10, R11.R9, R11.S4, R11.R9.R2
BURST = R11.BURST

EXP11_LOG = EXP11 / "run_log"
PRE_BUDGET = 15000
STALL = 3              # PBD · PBS 공통: 전체 최선이 이 라운드 수 연속 오르지 않으면 정체
CLIMB_N = 3            # PBS 등반자 수
CLIMB_K = 8            # 한 걸음에 평가하는 이웃 수
CLIMB_SHARE = 0.3      # 라운드 중 등반 몫
TARGET = 195.0         # T195(억, 임시 기준)
BUDGETS = (800, 2000)
NAME_RE = re.compile(r"^(PB15|PBD|PBS)(?:s(\d+))?(10k)?$")


def parse_name(name: str) -> tuple[str, int, bool]:
    """기호 → (기법 PB15 · PBD · PBS, 시드, 10k 판 여부). `PB15`는 s0(실험 11), `PBD` · `PBS`도 s0."""
    m = NAME_RE.match(name)
    if not m:
        raise ValueError(f"알 수 없는 기호: {name}")
    return m.group(1), int(m.group(2) or 0), bool(m.group(3))


def pre_account(seed: int) -> Any:
    """실험 11 PB15와 같은 사전 계산 계정. 시드 k ≥ 1이면 id = `pre-s<k>`(설계 · 구성 · 킥 난수가 바뀐다)."""
    acct = R11.pre_account177()
    if seed:
        acct.id = f"pre-s{seed}"
    return acct


# ---------------------------------------------------------------- 사전 계산 변형

def _run(sess: Any, squads: Sequence[tuple], phase: str, cap: int) -> int:
    return sess.run(squads, phase, cap=cap) if squads and cap > 0 else 0


def start_g(sess: Any, acct: Any, reserve: int, fitf: Callable) -> None:
    """실험 10 G 출발(균형 무작위 설계 + 구성 라운드) — 시드 문자열도 같아 s0이면 PB15와 같은 출발이다."""
    tag = f"{acct.id}-P177"
    sess.run(R10.design(acct.names, BURST, random.Random(f"exp10-design-{tag}")), "설계", cap=sess.budget - reserve)
    R10.construct(sess, reserve, fitf, BURST, random.Random(f"exp10-construct-{tag}"))


def loop_d(sess: Any, acct: Any, reserve: int, fitf: Callable, history: list, kicks: list) -> None:
    """PBD: 전체 최선이 STALL 라운드 정체 그리고 (계보가 없거나 계보도 STALL 라운드 정체)이면 킥. 킥 뒤 라운드는 계보 반 · 전체 반."""
    tag = f"{acct.id}-P177"
    g_best, g_stall = sess.pack()[0], 0
    lineage: set | None = None
    l_val, l_stall = 0.0, 0
    while sess.left > reserve:
        kicked = False
        if g_stall >= STALL and (lineage is None or l_stall >= STALL):
            best_now, used0 = sess.pack()[0], sess.used
            lin = R10.do_kick(sess, random.Random(f"exp12-kickD-{tag}-{len(kicks) + 1}"), BURST, cap=sess.left - reserve)
            if lin is None:
                break
            kicks.append({"evals": used0, "best": best_now})
            lineage, kicked = lin, True
            l_val, l_stall = R10.lineage_pack(sess, lineage), 0
            if sess.left <= reserve:
                history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": True})
                break
        n = min(R10.ROUND, sess.left - reserve)
        r = len(history)
        if lineage is None:
            got = _run(sess, R10.local_round(sess, n, None, fitf), f"탐색 {r}", n)
        else:
            n1 = n // 2
            got = _run(sess, R10.local_round(sess, n1, lineage, fitf), f"탐색 {r} 계보", n1)
            n2 = min(n - got, sess.left - reserve)
            got += _run(sess, R10.local_round(sess, n2, None, fitf), f"탐색 {r} 전체", n2) if n2 > 0 else 0
        if not got:
            if kicked:
                history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": True})
                break
            g_stall = l_stall = STALL  # 고칠 수가 없으면 바로 킥
            continue
        history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": kicked})
        g = sess.pack()[0]
        if g > g_best + 1e-9:
            g_best, g_stall = g, 0
        else:
            g_stall += 1
        if lineage is not None:
            lv = R10.lineage_pack(sess, lineage)
            l_stall = 0 if lv > l_val + 1e-9 else l_stall + 1
            l_val = max(l_val, lv)
    for i, k in enumerate(kicks):
        nxt = kicks[i + 1]["best"] if i + 1 < len(kicks) else sess.pack()[0]
        k["improved"] = nxt > k["best"] + 1e-9


def new_climber(sess: Any, avail: Sequence[str], counts: Counter, rng: random.Random) -> tuple | None:
    """구조 틀 균형 무작위 스쿼드(자리마다 평가 구성에 가장 적게 든 니케) — 아직 평가하지 않은 구성."""
    for _ in range(200):
        sq = R10.struct_squad(avail, counts, rng, BURST)
        if sq is None:
            return None
        if frozenset(sq) not in sess.book.best and sess.fresh(sq):
            return sq
    return None


def climb_round(sess: Any, climbers: list[dict], cap: int, fitf: Callable, rng: random.Random,
                restarts: list[dict]) -> int:
    """등반자 채우기 → 등반자마다 한 걸음. 교체해 넣는 니케 = 전체 최선 5덱 · 다른 등반자가 쓰지 않는 니케. 평가 수를 돌려준다."""
    acct, book = sess.acct, sess.book
    best_used = {n for _, sq in sess.pack()[1] for n in sq}
    used = 0
    counts: Counter = Counter(n for c in book.best for n in c)
    while len(climbers) < CLIMB_N and used < cap:
        taken = best_used | {n for c in climbers for n in c["sq"]}
        sq = new_climber(sess, [n for n in acct.names if n not in taken], counts, rng)
        if sq is None:
            break
        got = _run(sess, [sq], "재시작", 1)
        used += got
        if not got:
            break
        if frozenset(sq) not in book.best:  # 평가 오류
            continue
        v = book.best[frozenset(sq)][0]
        climbers.append({"sq": sq, "val": v, "start_evals": sess.used, "start_val": v, "steps": 0})
    if used >= cap or not climbers:
        return used
    score = fitf(book, acct.names)
    for c in list(climbers):
        k = min(CLIMB_K, cap - used)
        if k <= 0:
            break
        excl = best_used | {n for o in climbers if o is not c for n in o["sq"]}
        nbs = [nb for nb in S4.neighbors(c["sq"], acct.owned)
               if frozenset(nb) not in book.best and sess.fresh(nb) and not any(m in excl for m in nb if m not in c["sq"])]
        ranked = sorted(nbs, key=lambda nb: (-score(frozenset(nb)), nb))[:k]
        got = _run(sess, ranked, "등반", k)
        used += got
        vals = [(book.best[frozenset(nb)][0], nb) for nb in ranked[:got] if frozenset(nb) in book.best]
        bv, bsq = max(vals) if vals else (float("-inf"), None)
        if bsq is not None and bv > c["val"] + 1e-9:
            c.update(sq=bsq, val=bv, steps=c["steps"] + 1)
        else:
            climbers.remove(c)
            restarts.append({"start_evals": c["start_evals"], "start_val": c["start_val"], "end_evals": sess.used,
                             "end_val": c["val"], "steps": c["steps"], "squad": list(c["sq"])})
    return used


def loop_s(sess: Any, acct: Any, reserve: int, fitf: Callable, history: list, restarts: list) -> None:
    """PBS: 킥 없이 라운드마다 L0 70% + 등반 30%(등반이 다 못 쓰면 남은 몫은 버린다)."""
    rng = random.Random(f"exp12-climb-{acct.id}-P177")
    climbers: list[dict] = []
    while sess.left > reserve:
        n = min(R10.ROUND, sess.left - reserve)
        nc = round(n * CLIMB_SHARE)
        ng = n - nc
        r = len(history)
        got = _run(sess, R10.local_round(sess, ng, None, fitf), f"탐색 {r}", ng)
        got += climb_round(sess, climbers, min(nc, sess.left - reserve), fitf, rng, restarts)
        if not got:
            break
        history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": False})
    for c in climbers:
        restarts.append({"start_evals": c["start_evals"], "start_val": c["start_val"], "end_evals": None,
                         "end_val": c["val"], "steps": c["steps"], "squad": list(c["sq"])})


def run_variant(acct: Any, kind: str, budget: int, ev: Any) -> tuple[dict[str, Any], list[dict[str, Any]], Any]:
    """PBD · PBS 사전 계산 — 출발 · 순서 다듬기 · 요약은 실험 10 `run_method`(G+E)와 같다."""
    fitf = R10.fit_for(177)
    sess = R9.Session(acct, ev, budget)
    t0, sims0 = time.time(), ev.sim_count
    reserve = budget // 8
    start_g(sess, acct, reserve, fitf)
    p0 = sess.pack()
    history = [{"evals": sess.used, "pack": p0[0], "kick": False}]
    kicks: list[dict[str, Any]] = []
    restarts: list[dict[str, Any]] = []
    if kind == "PBD":
        loop_d(sess, acct, reserve, fitf, history, kicks)
    elif kind == "PBS":
        loop_s(sess, acct, reserve, fitf, history, restarts)
    else:
        raise ValueError(kind)
    pre_order = {"evals": sess.used, "pack": sess.pack()[0]}
    best = sess.pack()
    tops = [sq for _, sq in best[1]] + [sq for _, sq in sorted(sess.book.best.values(), reverse=True)[:R9.ORDER_TOP]]
    orders = list(dict.fromkeys(p for sq in dict.fromkeys(tops) for p in R2.distinct_orders(sq, BURST) if sess.fresh(p)))
    sess.run(orders, "순서")
    final = sess.pack()
    history.append({"evals": sess.used, "pack": final[0], "kick": False})
    summ = {"scenario": acct.id, "name": acct.name, "pool": 177, "method": kind, "budget": budget, "evals": sess.used,
            "errors": sum(r["error"] is not None for r in sess.records), "start": {"evals": history[0]["evals"], "pack": p0[0]},
            "history": history, "pre_order": pre_order, "kicks": kicks, "restarts": restarts,
            "final": R10.pack_dict(final), "sims_during": ev.sim_count - sims0, "seconds": round(time.time() - t0, 1)}
    return summ, sess.records, sess


def t_reach(history: Sequence[Mapping[str, Any]], target: float = TARGET) -> int | None:
    for h in history or []:
        if h["pack"] >= target - 1e-9:
            return h["evals"]
    return None


def core_together(final: Mapping[str, Any]) -> bool:
    core = {"토브", "아르카나 : 포츈 메이트", "도로시 : 세렌디피티", "드레이크"}
    return any(core <= set(sq) for _, sq in final.get("squads", []))


def run_pre(name: str, ev: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    kind, seed, cut = parse_name(name)
    if cut:
        raise ValueError("10k 판은 truncate로 만든다")
    acct = pre_account(seed)
    sims0 = ev.sim_count
    if kind == "PB15":
        summ, recs, sess = R10.run_method(acct, "G+E", PRE_BUDGET, ev, pool=177)
        summ["restarts"] = []
    else:
        summ, recs, sess = run_variant(acct, kind, PRE_BUDGET, ev)
    sims = ev.sim_count - sims0
    st = R11.stage_rec(f"177명 {kind} {PRE_BUDGET} 시드 s{seed}", summ, sims)
    out = R11.pre_out(name, [st], R11.extract(sess, acct, R11.fit_big), summ, seed=seed, kind=kind,
                      restarts=summ["restarts"], t195=t_reach(summ["history"]), core=core_together(summ["final"]))
    return out, recs


def truncate(pre: Mapping[str, Any], recs: Sequence[Mapping[str, Any]], at: int) -> dict[str, Any]:
    """앞 `at`평가만으로 8벌 · 계수를 뽑는다(순서 다듬기 없음). 비용은 `at`평가 · 그 안의 시뮬로 적는다(시뮬은 비례 추정)."""
    _, seed, _ = parse_name(pre["name"])
    acct = pre_account(seed)
    book = S4.Book()
    for r in recs[:at]:
        if r.get("total_damage") is not None:
            book.add(tuple(r["squad"]), r["total_damage"] / R10.E8)
    sess = type("Cut", (), {"book": book})()
    ext = R11.extract(sess, acct, R11.fit_big)
    hist = [h for h in pre["history"] if h["evals"] <= at]
    v = R9.pack_vals(book.best)
    final = R10.pack_dict(v)
    sims = round(pre["sims"] * at / max(pre["evals"], 1))
    return {"name": f"{pre['name']}10k" if at == 10000 else f"{pre['name']}@{at}", "pool": 177, "budget": at, "evals": at,
            "sims": sims, "seconds": round(pre["seconds"] * at / max(pre["evals"], 1), 1), **ext, "final": final,
            "history": hist, "kicks": [k for k in pre.get("kicks", []) if k["evals"] < at],
            "stages": [{"what": f"{pre['name']} 앞 {at}평가", "budget": at, "evals": at, "sims": sims}],
            "seed": seed, "kind": pre.get("kind"), "t195": t_reach(hist), "core": core_together(final), "cut_from": pre["name"]}


def write_pre(out: Path, name: str, data: Mapping[str, Any], recs: Sequence[Mapping[str, Any]] | None, ev: Any = None) -> None:
    data = dict(data)
    if ev is not None:
        data["evaluator"] = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
    if recs is not None:
        with gzip.open(out / f"precompute_{name}.jsonl.gz", "wt", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / f"precompute_{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"pre": name, "evals": data["evals"], "sims": data["sims"], "s": data["seconds"],
                      "best": round(data["final"]["total"], 2), "t195": data.get("t195"), "core": data.get("core"),
                      "sets": [round(t, 1) for t in data["set_totals"]]}, ensure_ascii=False), flush=True)


def cmd_precompute(args: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    args.out.mkdir(parents=True, exist_ok=True)
    names = args.which.split(",")
    for nm in names:
        parse_name(nm)
    ev = make_evaluator()
    with ev:
        for nm in names:
            if not (args.out / f"precompute_{nm}.json").exists():
                data, recs = run_pre(nm, ev)
                write_pre(args.out, nm, data, recs, ev)
    return 0


def cmd_truncate(args: argparse.Namespace) -> int:
    pre = json.loads((args.pre / f"precompute_{args.which}.json").read_text(encoding="utf-8"))
    recs = R11.load_records(args.pre / f"precompute_{args.which}.jsonl.gz")
    data = truncate(pre, recs, args.at)
    write_pre(args.pre, data["name"], data, None)
    return 0


# ---------------------------------------------------------------- 계정 탐색

def load_pre(method: str, pre_dir: Path) -> dict[str, Any] | None:
    if method == "K":
        return None
    if method == "PB15":
        return json.loads((EXP11_LOG / "precompute_PB15.json").read_text(encoding="utf-8"))
    parse_name(method)
    return json.loads((pre_dir / f"precompute_{method}.json").read_text(encoding="utf-8"))


def cmd_search(args: argparse.Namespace) -> int:
    scs = R10.scenarios(args.set)
    if args.only:
        want = set(args.only.split(","))
        scs = [s for s in scs if s["id"] in want]
    methods = args.methods.split(",")
    budgets = [int(b) for b in args.budgets.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    R10.pack_alt20 = lambda *a, **k: (0.0, [])  # 실험 11과 같이 대안 (b)는 계산하지 않는다
    pres = {m: load_pre(m, args.pre or args.out) for m in methods}
    tasks = [(s, m, b) for b in sorted(budgets, reverse=True) for s in scs for m in methods
             if not (args.out / f"{R10.run_name(s['id'], 177, m, b)}.json").exists()]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()
    lock = threading.Lock()

    def work(task):
        s, m, b = task
        summ, recs = R11.run_account(s, m, b, ev, pres[m])
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
    p.add_argument("--which", required=True)
    p.add_argument("--out", type=Path, required=True)
    t = sub.add_parser("truncate")
    t.add_argument("--which", required=True)
    t.add_argument("--at", type=int, default=10000)
    t.add_argument("--pre", type=Path, required=True)
    s = sub.add_parser("search")
    s.add_argument("--set", choices=("dev", "val"), required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--pre", type=Path)
    s.add_argument("--methods", required=True)
    s.add_argument("--budgets", default=",".join(map(str, BUDGETS)))
    s.add_argument("--only")
    s.add_argument("--workers", type=int, default=4)
    c = sub.add_parser("collect")
    c.add_argument("--runs", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--name", required=True)
    args = ap.parse_args(argv)
    return {"precompute": cmd_precompute, "truncate": cmd_truncate, "search": cmd_search,
            "collect": R10.cmd_collect}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
