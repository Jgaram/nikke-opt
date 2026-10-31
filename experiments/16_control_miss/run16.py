"""실험 16 — 기본 레이어 탐색이 컨트롤 의존 조합을 놓치는가: 표본 뽑기 · 컨트롤 탐색 실행기 (README §평가 문제 · §예산과 실행).

    python experiments/16_control_miss/run16.py sample --out experiments/16_control_miss/run_log
        → targets.json(시나리오별 층 · 구성 목록, 컨트롤 결과를 보기 전에 커밋)
    source .cache/evaluators.env && python experiments/16_control_miss/run16.py control --targets <dir>/targets.json
        [--cap 240000] [--only v1,v2] [--layers S0,S0p] [--limit N] [--workers 8]
        → <dir>/jobs/<해시>.json(구성마다 M3:k2 200평가 결과) · <dir>/control_log.jsonl(실행마다 시뮬 수)
    source .cache/evaluators.env && python experiments/16_control_miss/run16.py deckpost --targets <dir>/targets.json
        → <dir>/deckpost.json(관찰: 5덱 구성 후처리 반복, 결과를 본 뒤 추가 · 판단에 쓰지 않음)

- 조합 기록: 실험 13 U4 · 2,000 실행 8개(`val_evals.jsonl.gz`)를 그대로 읽는다(새 시뮬 0).
- S4 출처: 실험 13 U4 합친 판(PB15 시드 s0~s3 기록 합). 계정 B는 컨트롤 탐색의 첫 평가(바꾸지 않음 = 기본 레이어)로 잰다.
- 컨트롤 탐색: 실험 9 `cmd_post`의 작업과 같다 — 실험 7 M3:k2 200평가, 출발 = 기본 레이어(계정 육성 options),
  comp_id = (시나리오, 배치 순서), 시드 `job_seed(comp_id, "M3:k2")`.
- 실행 순서 = 빼는 순서의 반대: S0 → S0′ → S1 → S4 → S2 앞 절반 → S2 뒤 절반 → S3.
  상한에 닿으면 남은 작업(끝에서부터 S3 → S2 뒤 절반)을 빼고 control_log에 적는다.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import random
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXP13 = HERE.parent / "13_seed_merge"
EXP13_LOG = EXP13 / "run_log"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


U13 = sys.modules.get("run13") or _load("run13", EXP13 / "run13.py")
R12, R11, R10, R9, S4 = U13.R12, U13.R11, U13.R10, U13.R9, U13.S4
M, SC = R9.M, R9.sc
BURST = R11.BURST
E8 = R10.E8

SEED = 20261031
SOURCE_METHOD, SOURCE_BUDGET = "U4", 2000
POST_METHOD, POST_BUDGET = R9.POST_METHOD, R9.POST_BUDGET   # M3:k2 · 200
TOP, WIDE = 5, 10            # S0 = 틀별 1~5위, S0′ = 6~10위
NEAR, MID = 0.85, 0.5        # S1 ≥ 0.85m, S2 0.5m ~ 0.85m, S3 < 0.5m
N_S1_HALF, N_S2, N_S3, N_S4 = 32, 16, 8, 16
CAP = 240_000
JOB_SIMS = POST_BUDGET       # 상한 확인에 쓰는 작업 하나의 최대 시뮬 수
LAYERS = ("S0", "S0p", "S1", "S2", "S3", "S4")
# 실행 순서(앞일수록 빼지 않는다). S2는 표본 순서로 앞 · 뒤 절반을 나눈다.
PRIORITY = (("S0", None), ("S0p", None), ("S1", None), ("S4", None), ("S2", 0), ("S2", 1), ("S3", None))


# ---------------------------------------------------------------- 기록

def run_name(sid: str) -> str:
    return R10.run_name(sid, 177, SOURCE_METHOD, SOURCE_BUDGET)


def load_runs(path: Path = EXP13_LOG / "val_evals.jsonl.gz", wanted: Iterable[str] | None = None
              ) -> dict[str, list[dict[str, Any]]]:
    """실행 이름 → 평가 기록(평가 순)."""
    want = set(wanted) if wanted is not None else None
    out: dict[str, list[dict[str, Any]]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if want is None or r["run"] in want:
                out.setdefault(r["run"], []).append(r)
    return out


def load_summaries(path: Path = EXP13_LOG / "val_summary.jsonl") -> dict[str, dict[str, Any]]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            s = json.loads(line)
            out[s["run"]] = s
    return out


def has_test(sq: Iterable[str]) -> bool:
    """평가기 시험용 니케(test_*) — 실험 6 컨트롤 메뉴 정보에 없어 컨트롤을 찾을 수 없다."""
    return any(n.startswith("test_") for n in sq)


def frame_of(sq: Sequence[str]) -> str:
    return SC.skeleton(list(sq), BURST)


def weakest(final: Mapping[str, Any]) -> float:
    return min(v for v, _ in final["squads"])


# ---------------------------------------------------------------- 층 나누기 · 표본

def ranked(best: Mapping[frozenset, tuple[float, tuple]]) -> list[tuple[float, tuple]]:
    """(B, 최선 순서)를 B 내림차순(동률은 순서 tuple 순)."""
    return sorted(best.values(), key=lambda t: (-t[0], t[1]))


def frame_ranks(best: Mapping[frozenset, tuple[float, tuple]]) -> dict[frozenset, int]:
    """구성 → 틀 안 B 순위(1부터). 시험용 니케 구성은 순위에 넣지 않는다."""
    by: dict[str, list[tuple[float, tuple]]] = {}
    for v, sq in best.values():
        if not has_test(sq):
            by.setdefault(frame_of(sq), []).append((v, sq))
    out = {}
    for lst in by.values():
        for i, (_, sq) in enumerate(sorted(lst, key=lambda t: (-t[0], t[1])), 1):
            out[frozenset(sq)] = i
    return out


def layer_of(v: float, rank: int | None, m: float) -> str | None:
    if rank is None:
        return None
    if rank <= TOP:
        return "S0"
    if rank <= WIDE:
        return "S0p"
    if v >= NEAR * m:
        return "S1"
    if v >= MID * m:
        return "S2"
    return "S3"


def entry(v: float, sq: Sequence[str], rank: int | None, **kw: Any) -> dict[str, Any]:
    return {"squad": list(sq), "B": v, "frame": frame_of(sq), "frame_rank": rank, **kw}


def sample_layers(best: Mapping[frozenset, tuple[float, tuple]], m: float, rng_tag: str
                  ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """계정 기록 하나의 층 S0 · S0′ · S1 · S2 · S3 표본. → (층 → 측정할 구성들, 층 크기 · 경계)."""
    ranks = frame_ranks(best)
    pools: dict[str, list[tuple[float, tuple]]] = {k: [] for k in ("S0", "S0p", "S1", "S2", "S3")}
    for v, sq in ranked(best):
        lay = layer_of(v, ranks.get(frozenset(sq)), m)
        if lay is not None:
            pools[lay].append((v, sq))
    n_test = sum(has_test(sq) for _, sq in best.values())
    out: dict[str, list[dict[str, Any]]] = {}
    for k in ("S0", "S0p"):
        out[k] = [entry(v, sq, ranks[frozenset(sq)]) for v, sq in pools[k]]
    s1 = pools["S1"]
    half = (len(s1) + 1) // 2
    upper, lower = s1[:half], s1[half:]
    out["S1"] = []
    for tag, part in (("up", upper), ("lo", lower)):
        rng = random.Random(f"{SEED}-{rng_tag}-S1-{tag}")
        pick = rng.sample(part, min(N_S1_HALF, len(part)))
        out["S1"] += [entry(v, sq, ranks[frozenset(sq)], half=tag) for v, sq in pick]
    for k, n in (("S2", N_S2), ("S3", N_S3)):
        rng = random.Random(f"{SEED}-{rng_tag}-{k}")
        pick = rng.sample(pools[k], min(n, len(pools[k])))
        out[k] = [entry(v, sq, ranks[frozenset(sq)], part=i * 2 // max(len(pick), 1)) for i, (v, sq) in enumerate(pick)]
    sizes = {k: len(v) for k, v in pools.items()}
    sizes.update(S1_up=len(upper), S1_lo=len(lower), test_excluded=n_test, comps=len(best),
                 S1_split=upper[-1][0] if upper else None)
    return out, sizes


def s4_candidates(pre_best: Mapping[frozenset, tuple[float, tuple]], pre_m: float, acct_best: Iterable[frozenset],
                  owned: Iterable[str]) -> list[tuple[float, tuple]]:
    """계정 탐색이 평가하지 않았고, 사전 계산 B ≥ 0.85 × 사전 계산 m이며, 이 계정이 편성할 수 있는 구성."""
    have, seen = set(owned), set(acct_best)
    return [(v, sq) for v, sq in ranked(pre_best)
            if v >= NEAR * pre_m and frozenset(sq) not in seen and set(sq) <= have and not has_test(sq)]


def sample_s4(cands: Sequence[tuple[float, tuple]], rng_tag: str) -> list[dict[str, Any]]:
    rng = random.Random(f"{SEED}-{rng_tag}-S4")
    pick = rng.sample(list(cands), min(N_S4, len(cands)))
    return [entry(None, sq, None, B_pre=v) for v, sq in pick]


def build_targets(runs: Mapping[str, Sequence[Mapping[str, Any]]], summaries: Mapping[str, Mapping[str, Any]],
                  pre_best: Mapping[frozenset, tuple[float, tuple]], pre_m: float,
                  scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"seed": SEED, "source": f"실험 13 {SOURCE_METHOD} · {SOURCE_BUDGET}", "pre_m": pre_m,
                           "scenarios": {}}
    for s in scenarios:
        sid = s["id"]
        name = run_name(sid)
        best = R9.book_of(runs[name])
        summ = summaries[name]
        m = weakest(summ["final"])
        layers, sizes = sample_layers(best, m, sid)
        acct = R10.Account10(s, pool=177, rankerless=True)
        cands = s4_candidates(pre_best, pre_m, best, acct.owned)
        layers["S4"] = sample_s4(cands, sid)
        sizes["S4"] = len(cands)
        out["scenarios"][sid] = {"run": name, "name": s["name"], "m": m, "P0_record": summ["final"]["total"],
                                 "sizes": sizes, "layers": layers}
    return out


def cmd_sample(args: argparse.Namespace) -> int:
    scs = R10.scenarios("val")
    runs = load_runs(wanted=[run_name(s["id"]) for s in scs])
    summaries = load_summaries()
    srcs = U13.load_sources()
    book, _, _ = U13.merged_book(srcs, U13.SEEDS)
    pre = json.loads((EXP13_LOG / "precompute_U4.json").read_text(encoding="utf-8"))
    pre_m = weakest(pre["final"])
    assert abs(R9.pack_vals(book.best)[0] - pre["final"]["total"]) < 1e-6, "U4 합친 판 재현 실패"
    t = build_targets(runs, summaries, book.best, pre_m, scs)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "targets.json").write_text(json.dumps(t, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for sid, d in t["scenarios"].items():
        print(sid, {k: len(v) for k, v in d["layers"].items()}, d["sizes"], flush=True)
    print("측정 구성", sum(len(v) for d in t["scenarios"].values() for v in d["layers"].values()))
    return 0


# ---------------------------------------------------------------- 컨트롤 탐색

def comp_id(sid: str, sq: Sequence[str]) -> str:
    return R9.post_id(sid, sq)


def job_path(jobs: Path, cid: str) -> Path:
    return jobs / (hashlib.sha256(cid.encode()).hexdigest()[:16] + ".json")


def job_list(targets: Mapping[str, Any], only: Iterable[str] | None = None,
             layers: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """실행 순서대로 작업 목록. 같은 (시나리오, 순서)는 한 번만(앞 층)."""
    want = set(only) if only else None
    lays = set(layers) if layers else None
    out, seen = [], set()
    for lay, part in PRIORITY:
        if lays is not None and lay not in lays:
            continue
        for sid, d in targets["scenarios"].items():
            if want is not None and sid not in want:
                continue
            for e in d["layers"][lay]:
                if part is not None and e.get("part") != part:
                    continue
                cid = comp_id(sid, e["squad"])
                if cid in seen:
                    continue
                seen.add(cid)
                out.append({"id": cid, "scenario": sid, "layer": lay, "squad": e["squad"], "B": e["B"]})
    return out


class CapGate:
    """시뮬 상한: 작업을 시작하기 전에 (끝난 시뮬 + 진행 중 작업 × 최대 시뮬)이 상한을 넘으면 그 작업과 남은 작업을 뺀다."""

    def __init__(self, ev: Any, cap: int, per_job: int = JOB_SIMS, base: int = 0):
        self.ev, self.cap, self.per_job, self.base = ev, cap, per_job, base
        self.running = 0
        self.closed = False
        self.lock = threading.Lock()

    def enter(self) -> bool:
        with self.lock:
            if self.closed or self.base + self.ev.sim_count + (self.running + 1) * self.per_job > self.cap:
                self.closed = True
                return False
            self.running += 1
            return True

    def leave(self) -> None:
        with self.lock:
            self.running -= 1


def run_one(job: Mapping[str, Any], accts: Mapping[str, Any], ev: Any) -> dict[str, Any]:
    acct = accts[job["scenario"]]
    space = M.Space(list(job["squad"]), base=acct.options)
    r = M.run_job({"id": job["id"], "squad": list(job["squad"])}, POST_METHOD, ev, budget=POST_BUDGET, out=None,
                  space=space)
    r.update(squad=list(job["squad"]), scenario=job["scenario"], layer=job["layer"], B_record=job["B"])
    return r


def prior_sims(log: Path) -> int:
    if not log.exists():
        return 0
    return sum(json.loads(x).get("sims", 0) for x in log.read_text(encoding="utf-8").splitlines() if x.strip())


def cmd_control(args: argparse.Namespace) -> int:
    targets = json.loads(args.targets.read_text(encoding="utf-8"))
    base_dir = args.targets.parent
    jobs_dir = base_dir / "jobs"
    jobs_dir.mkdir(exist_ok=True)
    log = base_dir / "control_log.jsonl"
    todo = [j for j in job_list(targets, args.only.split(",") if args.only else None,
                                args.layers.split(",") if args.layers else None)
            if not job_path(jobs_dir, j["id"]).exists()]
    if args.limit is not None:
        todo = todo[:args.limit]
    accts = {s["id"]: R10.Account10(s, pool=177, rankerless=True) for s in R10.scenarios("val")}
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    before = prior_sims(log)
    gate = CapGate(ev, args.cap, base=before)
    t0 = time.time()
    done = Counter()
    skipped: list[str] = []
    lock = threading.Lock()

    def work(job):
        if not gate.enter():
            with lock:
                skipped.append(job["id"])
            return
        try:
            r = run_one(job, accts, ev)
        finally:
            gate.leave()
        job_path(jobs_dir, job["id"]).write_text(json.dumps(r, ensure_ascii=False) + "\n", encoding="utf-8")
        with lock:
            done[job["layer"]] += 1
            n = sum(done.values())
            if n % 20 == 0 or n == len(todo):
                print(json.dumps({"done": n, "of": len(todo), "sims": ev.sim_count, "t": round(time.time() - t0)},
                                 ensure_ascii=False), file=sys.stderr, flush=True)

    with ev:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for f in [pool.submit(work, j) for j in todo]:
                f.result()
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "jobs": sum(done.values()), "by_layer": dict(done),
               "skipped": len(skipped), "skipped_by_layer": dict(Counter(j["layer"] for j in todo if j["id"] in set(skipped))),
               "sims": ev.sim_count, "cache_hits": ev.cache_hits, "seconds": round(time.time() - t0),
               "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}",
               "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items() if k != "func"}}
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), file=sys.stderr)
    return 0


# ---------------------------------------------------------------- 관찰: 5덱 구성 후처리 (결과를 본 뒤 추가, 판단에 쓰지 않음)

DECK_ROUNDS = 4
DECK_BASES = {"D0": (), "D5": ("S0",), "Dstar": LAYERS}   # D0 = 5덱 구성만, D5 = S0 + 5덱 구성, D* = 측정한 모든 층 + 5덱 구성


def measured_values(best: Mapping[frozenset, tuple[float, tuple]], results: Iterable[Mapping[str, Any]]
                    ) -> dict[frozenset, tuple[float, tuple]]:
    """기본 레이어 값에 컨트롤 결과(max(B, J))를 반영. 기록에 없는 구성(S4)은 B = base_damage."""
    vals = dict(best)
    for r in results:
        c = frozenset(r["squad"])
        b = vals[c][0] if c in vals else r["base_damage"] / E8
        vals[c] = (max(b, r["best_damage"] / E8), tuple(r["squad"]))
    return vals


def deck_loop(sid: str, best: Mapping[frozenset, tuple[float, tuple]], start: Mapping[str, Mapping[str, Any]],
              run: Any, rounds: int = DECK_ROUNDS) -> dict[str, Any]:
    """5덱을 조립 → 컨트롤을 안 찾은 5덱 구성에 M3:k2 → 다시 조립을 5덱이 모두 측정한 구성이 될 때까지(최대 rounds번).
    start: comp_id → 작업 결과(출발 층). run(list[job]) → comp_id → 결과."""
    have = dict(start)
    hist = []
    for i in range(rounds + 1):
        total, ch = R9.pack_vals(measured_values(best, have.values()))
        todo = [{"id": comp_id(sid, sq), "scenario": sid, "layer": "D", "squad": list(sq),
                 "B": best[frozenset(sq)][0] if frozenset(sq) in best else None}
                for _, sq in ch if comp_id(sid, sq) not in have]
        hist.append({"round": i, "total": total, "new": len(todo), "squads": [[v, list(sq)] for v, sq in ch]})
        if not todo or i == rounds:
            break
        have.update(run(todo))
    return {"total": hist[-1]["total"], "rounds": hist, "extra": sorted(set(have) - set(start)),
            "complete": hist[-1]["new"] == 0}


def cmd_deckpost(args: argparse.Namespace) -> int:
    targets = json.loads(args.targets.read_text(encoding="utf-8"))
    base_dir = args.targets.parent
    jobs_dir = base_dir / "jobs"
    log = base_dir / "control_log.jsonl"
    sids = list(targets["scenarios"])
    runs = load_runs(wanted=[targets["scenarios"][s]["run"] for s in sids])
    accts = {s["id"]: R10.Account10(s, pool=177, rankerless=True) for s in R10.scenarios("val")}
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    gate = CapGate(ev, args.cap, base=prior_sims(log))
    t0 = time.time()
    n_jobs = Counter()

    def run(jobs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        out = {}
        todo = []
        for j in jobs:
            p = job_path(jobs_dir, j["id"])
            if p.exists():
                out[j["id"]] = json.loads(p.read_text(encoding="utf-8"))
            else:
                todo.append(j)

        def one(j):
            if not gate.enter():
                raise RuntimeError("시뮬 상한 — 5덱 구성 후처리 관찰을 멈춘다")
            try:
                r = run_one(j, accts, ev)
            finally:
                gate.leave()
            job_path(jobs_dir, j["id"]).write_text(json.dumps(r, ensure_ascii=False) + "\n", encoding="utf-8")
            return j["id"], r

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for cid, r in pool.map(one, todo):
                out[cid] = r
                n_jobs["new"] += 1
        return out

    res: dict[str, Any] = {}
    with ev:
        for sid in sids:
            t = targets["scenarios"][sid]
            best = R9.book_of(runs[t["run"]])
            res[sid] = {}
            for name, lays in DECK_BASES.items():
                start = {}
                for lay in lays:
                    for e in t["layers"][lay]:
                        cid = comp_id(sid, e["squad"])
                        start[cid] = json.loads(job_path(jobs_dir, cid).read_text(encoding="utf-8"))
                res[sid][name] = deck_loop(sid, best, start, run)
                print(json.dumps({"scenario": sid, "base": name, "total": round(res[sid][name]["total"], 2),
                                  "extra": len(res[sid][name]["extra"]), "sims": ev.sim_count}, ensure_ascii=False),
                      file=sys.stderr, flush=True)
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "what": "deckpost", "jobs": n_jobs["new"], "sims": ev.sim_count,
               "cache_hits": ev.cache_hits, "seconds": round(time.time() - t0),
               "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    (base_dir / "deckpost.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("control")
    c.add_argument("--targets", type=Path, required=True)
    c.add_argument("--cap", type=int, default=CAP)
    c.add_argument("--only")
    c.add_argument("--layers")
    c.add_argument("--limit", type=int)
    c.add_argument("--workers", type=int, default=8)
    d = sub.add_parser("deckpost")
    d.add_argument("--targets", type=Path, required=True)
    d.add_argument("--cap", type=int, default=CAP)
    d.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)
    return {"sample": cmd_sample, "control": cmd_control, "deckpost": cmd_deckpost}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
