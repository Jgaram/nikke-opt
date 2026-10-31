"""실험 17 — 고정 조합의 큐브 + 컨트롤 공동 탐색: 대상 고정 · 실행기 · 사전값 (README §평가 문제 · §기법 · §예산과 실행).

    python experiments/17_cube_control/run17.py plan                 → run_log/targets.json(결과를 보기 전에 커밋)
    source .cache/evaluators.env && python experiments/17_cube_control/run17.py run --phase 1 [--workers 4] [--only v1]
        → run_log/jobs/<해시>.json(구성마다 C0 · SQ · J [· REF] 결과) · run_log/logs/<기법>/<해시>.jsonl.gz(평가 기록)
    python experiments/17_cube_control/run17.py prior                → run_log/prior_JT.json(시나리오 하나 빼고 J 기록으로)
    source .cache/evaluators.env && python experiments/17_cube_control/run17.py run --phase 2   → JT

- 대상: 실험 16 targets.json의 S0(시나리오별 틀별 기본 레이어 상위 5 = 지금 후처리 대상), 8개 시나리오 116개.
  REF는 시나리오마다 B 상위 3개(24개).
- 계정 options: 실험 16과 같다(실험 10 `Account10`, P177 · 랭커 없음 · 검증 시나리오 육성). 큐브 보유 = 지원 큐브 전부 Lv15.
- 기법(모두 실험 7 M3:k2 — 좌표 하강 + 키 2개 킥, 출발 = 기본 레이어 + 렐릭 베어):
  C0  컨트롤만, 400평가(앞 200 = 실험 9 · 16 후처리와 같은 시드 · 같은 궤적)
  J   컨트롤 + 큐브(지원 큐브 전부), 400평가
  JT  컨트롤 + 큐브(니케별 사전값 상위 3 + 사전값에 없는 큐브), 400평가
  SQ  C0의 200평가 최선에서 출발해 컨트롤 + 큐브(전부)로 200평가 더(합 400)
  REF 컨트롤 + 큐브(전부), 1,200평가, 다른 시드 — 상한 참조용
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import os
import random
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXP16 = HERE.parent / "16_control_miss"
LOG = HERE / "run_log"
sys.path.insert(0, str(HERE))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R16 = sys.modules.get("run16") or _load("run16", EXP16 / "run16.py")
R10, R9, M = R16.R10, R16.R9, R16.M
import cubes as CB  # noqa: E402

SOURCE_TARGETS = EXP16 / "run_log" / "targets.json"
LAYER = "S0"
N_REF = 3
KICK = 2
BUDGET = 400          # C0 · J · JT
HALF = 200            # 읽는 지점 · SQ의 C0 몫 · 이어서 쓰는 몫
REF_BUDGET = 1200
TOP_K = 3             # JT: 니케별 사전값 상위 큐브 수(출발 큐브 제외)
CAP = 230_000
PHASE1 = ("C0", "SQ", "J")
PHASE2 = ("JT",)
SPEC = {"C0": "M3:k2", "J": "J:M3:k2", "JT": "JT:M3:k2", "SQ": "SQ:M3:k2", "REF": "REF:M3:k2"}


# ---------------------------------------------------------------- 대상

def build_targets(src: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "실험 16 targets.json · S0", "layer": LAYER, "n_ref": N_REF,
                           "inventory": CB.full_inventory(), "start_cube": CB.DEFAULT_CUBE, "scenarios": {}}
    for sid, d in src["scenarios"].items():
        comps = sorted(d["layers"][LAYER], key=lambda e: (-e["B"], e["squad"]))
        out["scenarios"][sid] = {
            "name": d["name"], "run": d["run"],
            "comps": [{"id": comp_id(sid, e["squad"]), "squad": e["squad"], "B": e["B"], "frame": e["frame"],
                       "frame_rank": e["frame_rank"], "ref": i < N_REF} for i, e in enumerate(comps)]}
    return out


def comp_id(sid: str, sq: Sequence[str]) -> str:
    return R9.post_id(sid, sq)   # 실험 9 · 16과 같다 → C0 시드가 같다


def jobs_of(targets: Mapping[str, Any], only: Iterable[str] | None = None) -> list[dict[str, Any]]:
    want = set(only) if only else None
    out = []
    for sid, d in targets["scenarios"].items():
        if want is not None and sid not in want:
            continue
        for c in d["comps"]:
            out.append({**c, "scenario": sid})
    return out


def hname(cid: str) -> str:
    return hashlib.sha256(cid.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- 실행

def m3_from(run: Any, start: tuple[int, ...], *, kick: int = KICK, seed: int = 0) -> None:
    """실험 7 M3:k<n>과 같되 출발점을 받는다."""
    sp = run.space
    rng = random.Random(seed)
    M.descend(run, start)
    stale = 0
    while not run.exhausted and stale < 200:
        before = run.used
        s = list(run.best_sel)
        for k in rng.sample(range(sp.K), min(kick, sp.K)):
            s[k] = rng.choice([o for o in sp.opts[k] + [-1] if o != s[k]])
        M.descend(run, tuple(s))
        stale = stale + 1 if run.used == before else 0


def space_for(method: str, squad: Sequence[str], options: Mapping[str, Any], inventory: Mapping[str, int],
              allowed: Mapping[str, Sequence[str]] | None = None) -> Any:
    if method == "C0":
        return M.Space(list(squad), base=options)
    if method == "JT":
        fn = CB.joint_variants_fn(inventory, allowed=lambda who: (allowed or {}).get(who))
    else:
        fn = CB.joint_variants_fn(inventory)
    return M.Space(list(squad), variants_fn=fn, base=options)


def read_log(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def best_at(rows: Sequence[Mapping[str, Any]], budget: int) -> tuple[int | None, list[str]]:
    """평가 기록(step 순)에서 앞 budget평가까지의 최선 (딜, label)."""
    best, lab = None, []
    for r in rows:
        if r["step"] >= budget:
            break
        d = r["total_damage"]
        if d is not None and (best is None or d > best):
            best, lab = d, r["variants"]
    return best, lab


def run_method(method: str, job: Mapping[str, Any], acct: Any, ev: Any, inventory: Mapping[str, int], *,
               logdir: Path, allowed: Mapping[str, Sequence[str]] | None = None,
               start_labels: Sequence[str] | None = None) -> dict[str, Any]:
    cid = job["id"]
    sp = space_for(method, job["squad"], acct.options, inventory, allowed)
    budget = {"REF": REF_BUDGET, "SQ": HALF}.get(method, BUDGET)
    tmp = logdir / method / f"{hname(cid)}.jsonl"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    comp = {"id": cid, "squad": list(job["squad"])}
    run = M.Run(comp, sp, ev, method=SPEC[method], budget=budget, out=tmp)
    t0 = time.time()
    try:
        seed = M.job_seed(cid, SPEC[method])
        if method == "SQ":
            start = sp.from_labels(start_labels or [])
            if start is None:
                raise ValueError(f"{cid}: C0 최선 label을 합친 공간에 놓을 수 없다: {start_labels}")
            m3_from(run, start, seed=seed)
        else:
            m3_from(run, sp.empty(), seed=seed)
    finally:
        run.close()
    raw = tmp.read_bytes()
    with gzip.open(tmp.with_suffix(".jsonl.gz"), "wb") as f:
        f.write(raw)
    tmp.unlink()
    return {"method": method, "spec": SPEC[method], "evals": run.used, "budget": budget,
            "best_damage": run.best, "base_damage": run.base_damage,
            "best_variants": list(sp.labels(run.best_sel)), "keys": sp.K, "options": sp.nv,
            "exhausted": run.exhausted, "seconds": round(time.time() - t0, 1)}


def run_job(job: Mapping[str, Any], acct: Any, ev: Any, inventory: Mapping[str, int], methods: Sequence[str], *,
            logdir: Path, jobfile: Path, priors: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rec = json.loads(jobfile.read_text(encoding="utf-8")) if jobfile.exists() else \
        {"id": job["id"], "scenario": job["scenario"], "squad": list(job["squad"]), "B_record": job["B"],
         "frame": job["frame"], "ref": job["ref"], "methods": {}}
    for m in methods:
        if m in rec["methods"] or (m == "REF" and not job["ref"]):
            continue
        kw: dict[str, Any] = {}
        if m == "SQ":
            rows = read_log(logdir / "C0" / f"{hname(job['id'])}.jsonl.gz")
            kw["start_labels"] = best_at(rows, HALF)[1]
        if m == "JT":
            kw["allowed"] = (priors or {})[job["scenario"]]["allowed"]
        rec["methods"][m] = run_method(m, job, acct, ev, inventory, logdir=logdir, **kw)
        jobfile.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    return rec


class Gate:
    """시뮬 상한: 작업 시작 전에 (끝난 시뮬 + 진행 중 작업 × 최대 시뮬)이 상한을 넘으면 그 작업과 남은 작업을 뺀다."""

    def __init__(self, ev: Any, cap: int, per_job: int, base: int = 0):
        self.ev, self.cap, self.per_job, self.base = ev, cap, per_job, base
        self.running, self.closed = 0, False
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


def prior_sims(log: Path) -> int:
    if not log.exists():
        return 0
    return sum(json.loads(x).get("sims", 0) for x in log.read_text(encoding="utf-8").splitlines() if x.strip())


def job_max_sims(phase: int, ref: bool) -> int:
    if phase == 2:
        return BUDGET
    return BUDGET * 2 + HALF + (REF_BUDGET if ref else 0)


def cmd_run(a: argparse.Namespace) -> int:
    targets = json.loads((LOG / "targets.json").read_text(encoding="utf-8"))
    inventory = targets["inventory"]
    methods = list(PHASE1) + ["REF"] if a.phase == 1 else list(PHASE2)
    priors = json.loads((LOG / "prior_JT.json").read_text(encoding="utf-8"))["scenarios"] if a.phase == 2 else None
    jobs_dir, logdir = LOG / "jobs", LOG / "logs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    todo = []
    for j in jobs_of(targets, a.only.split(",") if a.only else None):
        f = jobs_dir / f"{hname(j['id'])}.json"
        have = json.loads(f.read_text(encoding="utf-8"))["methods"] if f.exists() else {}
        need = [m for m in methods if m not in have and (m != "REF" or j["ref"])]
        if need:
            todo.append(j)
    if a.limit is not None:
        todo = todo[:a.limit]
    # REF가 있는 작업을 먼저(가장 길다)
    todo.sort(key=lambda j: (not j["ref"], j["scenario"], -j["B"]))
    accts = {s["id"]: R10.Account10(s, pool=177, rankerless=True) for s in R10.scenarios("val")}
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    run_log = LOG / "run_log.jsonl"
    gate = Gate(ev, a.cap, job_max_sims(a.phase, True), base=prior_sims(run_log))
    t0, done, skipped = time.time(), Counter(), []
    lock = threading.Lock()

    def work(j):
        per = job_max_sims(a.phase, j["ref"])
        gate.per_job = max(gate.per_job, per)
        if not gate.enter():
            with lock:
                skipped.append(j["id"])
            return
        try:
            run_job(j, accts[j["scenario"]], ev, inventory, methods, logdir=logdir,
                    jobfile=jobs_dir / f"{hname(j['id'])}.json", priors=priors)
        finally:
            gate.leave()
        with lock:
            done[j["scenario"]] += 1
            n = sum(done.values())
            if n % 5 == 0 or n == len(todo):
                print(json.dumps({"done": n, "of": len(todo), "sims": ev.sim_count, "t": round(time.time() - t0)},
                                 ensure_ascii=False), file=sys.stderr, flush=True)

    with ev:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            for f in [pool.submit(work, j) for j in todo]:
                f.result()
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "phase": a.phase, "jobs": sum(done.values()),
               "by_scenario": dict(done), "skipped": skipped, "sims": ev.sim_count, "cache_hits": ev.cache_hits,
               "seconds": round(time.time() - t0),
               "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}",
               "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items() if k != "func"}}
    with run_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), file=sys.stderr)
    return 0


# ---------------------------------------------------------------- JT 사전값

def cube_deltas(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], list[float]]:
    """한 구성의 평가 기록에서 (니케, 큐브) → log(그 큐브 / 출발 큐브) 목록.
    두 평가의 선택이 그 니케의 큐브 하나만 다르고 한쪽이 출발 큐브(바꾸지 않음)인 쌍만 쓴다."""
    val: dict[frozenset, int] = {}
    for r in rows:
        if r["total_damage"]:
            val.setdefault(frozenset(r["variants"]), r["total_damage"])
    out: dict[tuple[str, str], list[float]] = defaultdict(list)
    for labs, d in val.items():
        for lb in labs:
            who, ax, name = split_label(lb)
            if ax != "cube":
                continue
            b = val.get(labs - {lb})
            if b:
                out[(who, name)].append(math.log(d / b))
    return out


def split_label(lb: str) -> tuple[str, str, str]:
    """`"<니케>:<축>:<이름>"` — 니케 이름에 `" : "`가 들어갈 수 있어 축 이름으로 자른다."""
    for ax in (":cube:", ":click:", ":reload:", ":cover:", ":cancel:", ":burst:", ":camera:", ":tactic:"):
        i = lb.find(ax)
        if i >= 0:
            return lb[:i], ax.strip(":"), lb[i + len(ax):]
    raise ValueError(f"label 형식이 아니다: {lb}")


def build_prior(deltas_by_scn: Mapping[str, Mapping[tuple[str, str], list[float]]], held: str,
                top_k: int = TOP_K, cubes: Sequence[str] | None = None, start: str = CB.DEFAULT_CUBE
                ) -> dict[str, list[str]]:
    """held 시나리오를 뺀 기록으로 니케 → 허용 큐브. 기록에 없는 니케는 넣지 않는다(= 전부).
    기록이 있는 니케: 평균 log 이득 상위 top_k + 그 니케에서 한 번도 관찰하지 않은 큐브(새 큐브 탐색)."""
    cubes = [c for c in (cubes or CB.supported()) if c != start]
    acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for sid, d in deltas_by_scn.items():
        if sid == held:
            continue
        for (who, c), xs in d.items():
            acc[who][c].extend(xs)
    out = {}
    for who, by in acc.items():
        seen = sorted(by, key=lambda c: (-sum(by[c]) / len(by[c]), cubes.index(c) if c in cubes else 99))
        out[who] = sorted(set(seen[:top_k]) | {c for c in cubes if c not in by}, key=cubes.index)
    return out


def cmd_prior(a: argparse.Namespace) -> int:
    targets = json.loads((LOG / "targets.json").read_text(encoding="utf-8"))
    by_scn: dict[str, dict[tuple[str, str], list[float]]] = {}
    for sid, d in targets["scenarios"].items():
        acc: dict[tuple[str, str], list[float]] = defaultdict(list)
        for c in d["comps"]:
            p = LOG / "logs" / "J" / f"{hname(c['id'])}.jsonl.gz"
            if not p.exists():
                raise SystemExit(f"J 기록이 없다: {c['id']} — 1단계를 먼저 끝낸다")
            for k, xs in cube_deltas(read_log(p)).items():
                acc[k].extend(xs)
        by_scn[sid] = acc
    out = {"source": "J 기록(시나리오 하나 빼기)", "top_k": TOP_K, "scenarios": {}}
    for sid in targets["scenarios"]:
        allowed = build_prior(by_scn, sid)
        out["scenarios"][sid] = {"allowed": allowed,
                                 "mean_options": round(sum(len(v) for v in allowed.values()) / max(1, len(allowed)), 2)}
    (LOG / "prior_JT.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({s: v["mean_options"] for s, v in out["scenarios"].items()}, ensure_ascii=False))
    return 0


def cmd_plan(a: argparse.Namespace) -> int:
    src = json.loads(SOURCE_TARGETS.read_text(encoding="utf-8"))
    t = build_targets(src)
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "targets.json").write_text(json.dumps(t, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = sum(len(d["comps"]) for d in t["scenarios"].values())
    nref = sum(c["ref"] for d in t["scenarios"].values() for c in d["comps"])
    print(f"구성 {n}개(REF {nref}개) · 최대 시뮬 {n * (BUDGET * 3 + HALF) + nref * REF_BUDGET:,}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan").set_defaults(func=cmd_plan)
    p = sub.add_parser("run")
    p.add_argument("--phase", type=int, choices=(1, 2), required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--only")
    p.add_argument("--limit", type=int)
    p.add_argument("--cap", type=int, default=CAP)
    p.set_defaults(func=cmd_run)
    sub.add_parser("prior").set_defaults(func=cmd_prior)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
