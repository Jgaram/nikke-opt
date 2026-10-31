"""실험 18 — 5덱 기준 운용 후처리: 정책 실행기 (README §정책 · §예산과 실행).

    source .cache/evaluators.env && python experiments/18_deck_post/run18.py run [--workers 6] [--only v1]
        → run_log/ops/<기법>/<해시>.json(구성마다 운용 탐색 결과) · run_log/policies.jsonl(시나리오 × 정책 × 기법 결과)

- 조합 기록: 실험 13 U4 · 2,000 계정 실행 8개(실험 16 · 17과 같다, 새 시뮬 0). 5덱 조립은 실험 9 `repack_post`.
- 운용 탐색 기법(구성 하나): C = 컨트롤만 M3:k2 200(지금 기본) · J = 컨트롤 + 큐브 M3:k2 400(실험 17 기본) ·
  S = C의 최선에서 컨트롤 + 큐브 200 더(실험 17 SQ, 합 400) · T = 컨트롤 + 큐브(니케별 사전값 상위 3) M3:k2 400
  (실험 17 최종 판단 「운용 탐색 기본 = JT · 400」, 사전값은 실험 17 prior_JT.json — 그 시나리오를 뺀 J 기록).
  같은 구성 · 같은 기법은 한 번만 돌고 정책끼리 결과를 나눠 쓴다.
  실험 16 jobs(C)와 실험 17 기록(C0 · J · SQ · JT)에 같은 구성이 있으면 그 값을 쓴다(같은 시드 · 같은 평가기라 다시 돌린 값과 같다).
- 정책(후처리 대상을 고르는 규칙):
  PS  틀별 기본 레이어 상위 5(실험 9 기본 = 실험 16 S0)
  PF  고정점: 5덱을 짜고 → 그 덱 중 아직 운용을 찾지 않은 덱에 운용 탐색 → 다시 짜기를 새 덱이 없을 때까지
  PF2 PF의 고정점에서 대안 5덱(최선과 덱 2개 이하만 공유)도 같은 고정점에 넣는다 — 대안 안의 운용까지 찾는다
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
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

HERE = Path(__file__).resolve().parent
EXP16 = HERE.parent / "16_control_miss"
EXP17 = HERE.parent / "17_cube_control"
LOG = HERE / "run_log"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(EXP17))
R17 = sys.modules.get("run17") or _load("run17", EXP17 / "run17.py")
R16, R10, R9, M, CB = R17.R16, R17.R10, R17.R9, R17.M, R17.CB
E8 = R16.E8

METHODS = ("C", "J", "S", "T")
POLICIES = ("PS", "PF", "PF2")
BUDGET = {"C": 200, "J": 400, "S": 400, "T": 400}     # 구성 하나의 평가 수(S = C 200 + 이어서 200)
MAX_ROUNDS = 12
TOP = 5


# ---------------------------------------------------------------- 운용 탐색 값(구성 하나)

def hname(cid: str) -> str:
    return hashlib.sha256(cid.encode()).hexdigest()[:16]


class Ops:
    """(기법, 구성) → {"value", "labels", "evals", "source"}. 실험 16 · 17 기록을 먼저 보고, 없으면 돌린다."""

    def __init__(self, ev: Any | None, accts: Mapping[str, Any], inventory: Mapping[str, int],
                 out: Path = LOG / "ops", reuse: bool = True):
        self.ev, self.accts, self.inv, self.out = ev, accts, inventory, out
        self.lock = threading.Lock()
        self.memo: dict[tuple[str, str], dict[str, Any]] = {}
        self.inflight: dict[tuple[str, str], threading.Event] = {}
        self.ran = {m: 0 for m in METHODS}
        self.reused = {m: 0 for m in METHODS}
        self.e16 = load_exp16_jobs() if reuse else {}
        pj = EXP17 / "run_log" / "prior_JT.json"
        self.priors = json.loads(pj.read_text(encoding="utf-8"))["scenarios"] if pj.exists() else {}
        self.reuse = reuse

    def path(self, m: str, cid: str) -> Path:
        return self.out / m / f"{hname(cid)}.json"

    def from_records(self, m: str, cid: str) -> dict[str, Any] | None:
        if not self.reuse:
            return None
        h = hname(cid)
        if m == "C":
            j = self.e16.get(cid)
            if j is not None:
                return {"value": j["best_damage"], "labels": j["best_variants"], "evals": j["evals"], "source": "exp16"}
            p = EXP17 / "run_log" / "logs" / "C0" / f"{h}.jsonl.gz"
            if p.exists():
                d, lab = R17.best_at(R17.read_log(p), 200)
                return {"value": d, "labels": lab, "evals": 200, "source": "exp17"}
        if m == "J":
            p = EXP17 / "run_log" / "logs" / "J" / f"{h}.jsonl.gz"
            if p.exists():
                d, lab = R17.best_at(R17.read_log(p), 400)
                return {"value": d, "labels": lab, "evals": 400, "source": "exp17"}
        if m == "T":
            p = EXP17 / "run_log" / "logs" / "JT" / f"{h}.jsonl.gz"
            if p.exists():
                d, lab = R17.best_at(R17.read_log(p), 400)
                return {"value": d, "labels": lab, "evals": 400, "source": "exp17"}
        if m == "S":
            p = EXP17 / "run_log" / "logs" / "SQ" / f"{h}.jsonl.gz"
            c = self.get_cached("C", cid)
            if p.exists() and c is not None:
                d, lab = R17.best_at(R17.read_log(p), 200)
                if d is None or c["value"] > d:
                    d, lab = c["value"], c["labels"]
                return {"value": d, "labels": lab, "evals": 400, "source": "exp17"}
        return None

    def get_cached(self, m: str, cid: str) -> dict[str, Any] | None:
        k = (m, cid)
        if k in self.memo:
            return self.memo[k]
        p = self.path(m, cid)
        r = json.loads(p.read_text(encoding="utf-8")) if p.exists() else self.from_records(m, cid)
        if r is not None:
            self.memo[k] = r
        return r

    def get(self, m: str, sid: str, squad: Sequence[str]) -> dict[str, Any]:
        cid = R17.comp_id(sid, squad)
        k = (m, cid)
        while True:
            with self.lock:
                r = self.get_cached(m, cid)
                if r is not None:
                    if r.get("source") in ("exp16", "exp17") and not r.get("_counted"):
                        r["_counted"] = True
                        self.reused[m] += 1
                    return r
                ev_ = self.inflight.get(k)
                if ev_ is None:
                    ev_ = self.inflight[k] = threading.Event()
                    break
            ev_.wait()
        try:
            r = self.run(m, sid, cid, squad)
            with self.lock:
                self.memo[k] = r
                self.ran[m] += 1
        finally:
            with self.lock:
                self.inflight.pop(k).set()
        return r

    def run(self, m: str, sid: str, cid: str, squad: Sequence[str]) -> dict[str, Any]:
        if self.ev is None:
            raise RuntimeError(f"평가기 없이 새 운용 탐색이 필요하다: {m} {cid}")
        acct = self.accts[sid]
        job = {"id": cid, "squad": list(squad)}
        logdir = self.out / "logs"
        if m == "C":
            sp = M.Space(list(squad), base=acct.options)
            run = M.Run(job, sp, self.ev, method="M3:k2", budget=BUDGET["C"], out=None)
            R17.m3_from(run, sp.empty(), seed=M.job_seed(cid, "M3:k2"))
            r = {"value": run.best, "labels": list(sp.labels(run.best_sel)), "evals": run.used, "source": "run"}
        elif m in ("J", "T"):
            kw = {"allowed": self.priors[sid]["allowed"]} if m == "T" else {}
            res = R17.run_method("J" if m == "J" else "JT", {"id": cid, "squad": list(squad)}, acct, self.ev, self.inv,
                                 logdir=logdir, **kw)
            r = {"value": res["best_damage"], "labels": res["best_variants"], "evals": res["evals"], "source": "run"}
        else:
            c = self.get("C", sid, squad)
            res = R17.run_method("SQ", {"id": cid, "squad": list(squad)}, acct, self.ev, self.inv, logdir=logdir,
                                 start_labels=c["labels"])
            v, lab = res["best_damage"], res["best_variants"]
            if v is None or c["value"] > v:
                v, lab = c["value"], c["labels"]
            r = {"value": v, "labels": lab, "evals": BUDGET["S"], "source": "run"}
        p = self.path(m, cid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({**r, "id": cid, "squad": list(squad)}, ensure_ascii=False) + "\n", encoding="utf-8")
        return r


def load_exp16_jobs() -> dict[str, dict[str, Any]]:
    out = {}
    d = EXP16 / "run_log" / "jobs"
    if d.exists():
        for p in d.glob("*.json"):
            j = json.loads(p.read_text(encoding="utf-8"))
            if j.get("method") == "M3:k2" and j.get("evals", 0) >= 200 and j.get("best_damage"):
                out[j["comp_id"]] = j
    return out


# ---------------------------------------------------------------- 정책

def top_per_frame(best: Mapping[frozenset, tuple[float, tuple]], top: int = TOP) -> list[tuple]:
    """틀별 B 상위 top(실험 16 S0와 같은 순위 — 177명 풀 버스트 표, 시험용 니케 구성 제외)."""
    rk = R16.frame_ranks(best)
    return sorted((best[c][1] for c, r in rk.items() if r <= top), key=lambda sq: (-best[frozenset(sq)][0], sq))


def pack(best: Mapping[frozenset, tuple[float, tuple]], post: Mapping[tuple, float], **kw: Any
         ) -> tuple[float, list[tuple[float, tuple]]]:
    vals = {c: (max(v, post.get(sq, v)), sq) for c, (v, sq) in best.items()}
    return R9.pack_vals(vals, **kw)


def alternative(best: Mapping[frozenset, tuple[float, tuple]], post: Mapping[tuple, float],
                decks: Sequence[tuple[float, tuple]]) -> tuple[float, list[tuple[float, tuple]]]:
    """최선 5덱과 덱(구성)을 2개 이하만 그대로 공유하는 최선 5덱(실험 9 대안 5덱)."""
    avoid = [{frozenset(sq) for _, sq in decks}]
    return pack(best, post, avoid=avoid, max_share=R9.MAX_SHARE)


def run_policy(policy: str, best: Mapping[frozenset, tuple[float, tuple]],
               value: Callable[[Sequence[tuple]], Mapping[tuple, float]]) -> dict[str, Any]:
    """value(구성 목록) → {구성: 운용 값(억)}. 돌린 구성과 라운드 수, 최종 5덱을 돌려준다."""
    post: dict[tuple, float] = {}
    skipped: set[tuple] = set()
    rounds = 0
    if policy == "PS":
        post.update(value(top_per_frame(best)))
        rounds = 1
    else:
        while rounds < MAX_ROUNDS:
            tot, decks = pack(best, post)
            need = [sq for _, sq in decks if sq not in post and sq not in skipped]
            if policy == "PF2":
                _, alt = alternative(best, post, decks)
                need += [sq for _, sq in alt if sq not in post and sq not in need and sq not in skipped]
            # 시험용 니케(test_*)가 든 구성은 컨트롤 메뉴 정보가 없어 운용을 찾지 않는다(B 그대로, 실험 16과 같다)
            skipped.update(sq for sq in need if R16.has_test(sq))
            need = [sq for sq in need if not R16.has_test(sq)]
            if not need:
                break
            post.update(value(need))
            rounds += 1
    tot, decks = pack(best, post)
    out = {"total": tot, "decks": [[v, list(sq)] for v, sq in decks], "post": len(post), "rounds": rounds,
           "skipped_test": len(skipped),
           "in_5deck_processed": sum(1 for _, sq in decks if sq in post)}
    if policy == "PF2":
        at, alt = alternative(best, post, decks)
        out["alt_total"] = at
        out["alt_decks"] = [[v, list(sq)] for v, sq in alt]
    return out


def cmd_run(a: argparse.Namespace) -> int:
    t17 = json.loads((EXP17 / "run_log" / "targets.json").read_text(encoding="utf-8"))
    sids = [s for s in t17["scenarios"] if not a.only or s in a.only.split(",")]
    runs = R16.load_runs(wanted=[t17["scenarios"][s]["run"] for s in sids])
    books = {s: R9.book_of(runs[t17["scenarios"][s]["run"]]) for s in sids}
    accts = {s["id"]: R10.Account10(s, pool=177, rankerless=True) for s in R10.scenarios("val")}
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    ops = Ops(ev, accts, t17["inventory"])
    LOG.mkdir(parents=True, exist_ok=True)
    out_path = LOG / "policies.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["scenario"], r["policy"], r["method"]))
    pool = ThreadPoolExecutor(max_workers=a.workers)
    t0 = time.time()
    lock = threading.Lock()

    def value_fn(m: str, sid: str):
        def f(squads: Sequence[tuple]) -> dict[tuple, float]:
            futs = {sq: pool.submit(ops.get, m, sid, sq) for sq in squads}
            return {sq: fu.result()["value"] / E8 for sq, fu in futs.items()}
        return f

    def one(sid: str, pol: str, m: str) -> None:
        if (sid, pol, m) in done:
            return
        r = run_policy(pol, books[sid], value_fn(m, sid))
        # 이 정책이 운용을 찾은 구성들의 평가 수 합(같은 구성을 다른 정책이 먼저 돌렸어도 이 정책의 비용으로 센다)
        rec = {"scenario": sid, "policy": pol, "method": m, **r,
               "evals": r["post"] * BUDGET[m], "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with lock:
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(json.dumps({k: rec[k] for k in ("scenario", "policy", "method", "total", "post", "rounds")},
                             ensure_ascii=False), file=sys.stderr, flush=True)

    with ev:
        # 정책 하나는 라운드마다 기다리므로 정책들을 따로 스레드로 돌린다(운용 탐색은 공용 pool)
        outer = ThreadPoolExecutor(max_workers=len(sids) * len(POLICIES) * len(METHODS))
        futs = [outer.submit(one, s, p, m) for s in sids for p in POLICIES for m in METHODS]
        for f in futs:
            f.result()
        outer.shutdown()
        pool.shutdown()
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sims": ev.sim_count, "cache_hits": ev.cache_hits,
               "ran": ops.ran, "reused": ops.reused, "seconds": round(time.time() - t0),
               "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    with (LOG / "run_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--only")
    p.set_defaults(func=cmd_run)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
