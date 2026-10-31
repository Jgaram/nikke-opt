"""실험 15 — 신캐 추가 모사 실행기 (README §경우 · §갱신 방법 · §계정 검증).

    source .cache/evaluators.env && python experiments/15_new_nikke/run15.py precompute --case C1 --seed 0
        (구 풀 = 177명 − 새 니케, 실험 12 PB15s<k>와 같은 G+E 15,000, 계정 id `pre-C1-s0`; --seed 0,1,2,3처럼 여럿도 된다)
    python experiments/15_new_nikke/run15.py merge --case C1 [--which O,I1,approx]
        → precompute_O.json(구 풀 시드 4개 합치기) · precompute_I1.json(+ 실험 14 s4 기록) · approx.json(관찰: 걸러 낸 근사)
        (셋은 독립 — 판마다 8벌 뽑기가 약 15분이라 프로세스 3개로 나눠 돌린다)
    source .cache/evaluators.env && python experiments/15_new_nikke/run15.py update --case C1
        → precompute_I2.json · .jsonl.gz(신캐 집중 이어 붙이기 13,200평가, 시작 기록 = O)
    source .cache/evaluators.env && python experiments/15_new_nikke/run15.py search --case C1 --out <runs dir>
        --methods O,I1,I2 [--missing-new --methods O,I1,I2,F4 --budgets 800] [--only v1,v2] [--workers 2]
    python experiments/15_new_nikke/run15.py collect --runs <runs dir> --out experiments/15_new_nikke/cases/C1/run_log --name val

- 기록은 모두 `cases/<경우>/run_log/`에 둔다(`--log`로 바꿀 수 있다). 계정 실행 요약 · 기록은 `--out` 폴더에 쓰고 `collect`로 모은다.
- 사전 계산은 실험 10 `run_method(G+E)`, 8벌 · 계수는 실험 11 `extract`, 계정 탐색은 실험 11 `run_account`(P = 8벌 옮기기 + 177명 L0)와 같다.
- 「출시 전」(O)에는 새 니케가 사전 계산 계정 · 기록 · 8벌 · 계수 어디에도 없다. 계정 탐색은 늘 「출시 뒤」 177명 풀이다.
- 미보유 조건(`--missing-new`)은 같은 시나리오에서 새 니케만 빼고(육성 등급 · 나머지 보유는 그대로) 시나리오 id를 `v<k>n`으로 쓴다.
"""

from __future__ import annotations

import argparse
import gzip
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
from typing import Any, Callable, Iterable, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXP13 = HERE.parent / "13_seed_merge"
EXP14_LOG = HERE.parent / "14_seed_pairs" / "run_log"
EXP13_LOG = EXP13 / "run_log"
CASES_DIR = HERE / "cases"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


U13 = sys.modules.get("run13") or _load("run13", EXP13 / "run13.py")
R12, R11, R10, R9, S4, R2 = U13.R12, U13.R11, U13.R10, U13.R9, U13.S4, U13.R9.R2
BURST = R11.BURST
E8 = R10.E8

# README §경우 표 그대로(다시 고르지 않는다). C4 = C3 3명 + 7명.
_C3 = ("스노우 화이트 : 헤비암즈", "브리드 : 사일런트 트랙", "아니스 : 스타")
CASES: dict[str, tuple[str, ...]] = {
    "C1": ("아르카나 : 포츈 메이트",),
    "C2": ("아르카나 : 포츈 메이트", "도로시 : 세렌디피티"),
    "C3": _C3,
    "C4": _C3 + ("나유타", "신데렐라 : 크리스탈 웨이브", "네온 : 비전 아이", "드레이크 : 그레이트 빌런", "리틀 머메이드",
                 "리버렐리오", "마스트 : 로망틱 메이드"),
    "C5": ("엑시아", "신 : 스위프트 바니", "아크레인저 블랙", "베이", "크러스트"),
}
META_CASES = ("C1", "C2", "C3", "C4")      # 메타를 바꾸는 경우(취합 판단). C5는 대조군
SEEDS = (0, 1, 2, 3)                       # 구 풀 사전 계산 시드(F4 = 실험 13 U4와 번호가 같다)
I1_SEED = 4                                # 실험 14 s4(F4에 안 쓴 시드)
PRE_BUDGET = R12.PRE_BUDGET                # 15,000
I2_BUDGET = 13200                          # I1의 s4 평가 수(13,210)와 같은 비용
DESIGN_MIN, DESIGN_PER = 100, 20           # I2 1단계: max(100, 20n)평가
INSERT_TOP, INSERT_SHARE = 2, 0.3          # I2 2단계: 덱 · 새 니케마다 대리 모델 상위 2개, 예산의 30% 이하
METHODS = ("O", "I1", "I2", "F4")
BUDGETS = (800, 2000)
TARGET = 195.0


def removed(case: str) -> tuple[str, ...]:
    if case not in CASES:
        raise ValueError(f"알 수 없는 경우: {case}")
    return CASES[case]


def log_dir(case: str, base: Path | None = None) -> Path:
    return base if base is not None else CASES_DIR / case / "run_log"


def new_count(final: Mapping[str, Any], new: Iterable[str]) -> int:
    """최종 5덱에 든 새 니케 수."""
    new = set(new)
    return sum(n in new for _, sq in final.get("squads", []) for n in sq)


def new_decks(final: Mapping[str, Any], new: Iterable[str]) -> int:
    """새 니케가 하나라도 든 덱 수."""
    new = set(new)
    return sum(bool(new & set(sq)) for _, sq in final.get("squads", []))


# ---------------------------------------------------------------- 계정

def old_account(case: str, seed: int) -> Any:
    """구 풀 사전 계산 계정: 177명 − 새 니케 전원 보유 · 상, id `pre-<경우>-s<k>`(설계 · 구성 · 킥 난수가 이 id로 정해진다)."""
    sc = dict(R10.pre_scenario(), id=f"pre-{case}-s{seed}", missing=list(removed(case)))
    return R10.Account10(sc, pool=177, rankerless=True)


def full_account(sid: str) -> Any:
    """「출시 뒤」 177명 전원 보유 · 상 사전 계산 계정."""
    acct = R11.pre_account177()
    acct.id = sid
    return acct


def val_account(sc: Mapping[str, Any], case: str | None = None) -> Any:
    """검증 계정. case를 주면 새 니케를 모두 미보유로 바꾸고 id를 `v<k>n`으로 쓴다 — 육성 등급은 원래 시나리오 그대로다
    (실험 10 `ext_tiers`는 시나리오 id로 등급 시드를 고르므로 원래 id로 만든 뒤 고친다)."""
    acct = R10.Account10(sc, pool=177, rankerless=True)
    if case is None:
        return acct
    rm = removed(case)
    acct.id = f"{sc['id']}n"
    acct.name = f"{sc['name']} · 신캐 미보유"
    acct.missing = sorted(set(acct.missing) | set(rm))
    for n in rm:
        acct.owned.pop(n, None)
        acct.tier.pop(n, None)
    acct.names = sorted(acct.owned)
    chars = {n: R9.TIERS[t] for n, t in sorted(acct.tier.items()) if t != "상"}
    acct.options = {"profile": {"base": "default", "chars": chars}} if chars else {}
    return acct


# ---------------------------------------------------------------- 기록 읽기 · 쓰기

def load_json(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(p: Path, data: Any) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def write_records(p: Path, recs: Sequence[Mapping[str, Any]]) -> None:
    with gzip.open(p, "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


Sources = dict[str, tuple[dict[str, Any], list[dict[str, Any]]]]


def o_sources(case: str, d: Path) -> Sources:
    """구 풀 시드 4개의 사전 계산 (요약, 평가 기록)."""
    out: Sources = {}
    for k in SEEDS:
        nm = f"O-s{k}"
        out[nm] = (load_json(d / f"precompute_{nm}.json"), R11.load_records(d / f"precompute_{nm}.jsonl.gz"))
    return out


def s4_source() -> Sources:
    m = U13.seed_method(I1_SEED)
    return {m: (load_json(EXP14_LOG / f"precompute_{m}.json"), R11.load_records(EXP14_LOG / f"precompute_{m}.jsonl.gz"))}


def f4_sources() -> Sources:
    """F4 = 실험 13 U4의 출처(실험 11 PB15 · 실험 12 PB15s1~s3)."""
    return {U13.seed_method(k): v for k, v in U13.load_sources(SEEDS).items()}


# ---------------------------------------------------------------- 합치기 (O · I1 · 근사)

def build_book(srcs: Sources, drop: Iterable[str] = ()) -> tuple[Any, dict[frozenset, list[str]], int]:
    """출처 기록의 합. drop에 든 니케가 하나라도 있는 구성은 뺀다(걸러 낸 근사). → (Book, 구성 → 든 출처, 쓴 평가 수)."""
    drop = set(drop)
    book = S4.Book()
    where: dict[frozenset, list[str]] = {}
    used = 0
    for lab, (_, recs) in srcs.items():
        for r in recs:
            if r.get("total_damage") is None:
                continue
            if drop and drop & set(r["squad"]):
                continue
            used += 1
            sq = tuple(r["squad"])
            book.add(sq, r["total_damage"] / E8)
            lst = where.setdefault(frozenset(sq), [])
            if lab not in lst:
                lst.append(lab)
    return book, where, used


def merged(srcs: Sources, acct: Any, name: str, case: str, drop: Iterable[str] = ()) -> dict[str, Any]:
    """합친 판(실험 13 `merge(full=True)`와 같은 형식) — 8벌 · 계수는 acct의 니케로만 뽑는다(O는 구 풀이라 새 니케 계수가 없다)."""
    rm = removed(case)
    book, where, _ = build_book(srcs, drop)
    v = R9.pack_vals(book.best)
    final = R10.pack_dict(v)
    ext = R11.extract(type("Merged", (), {"book": book})(), acct, R11.fit_big)
    stages = [{"what": f"{lab} 기록(재사용)", "evals": pj["evals"], "sims": pj["sims"]} for lab, (pj, _) in srcs.items()]
    return {"name": name, "case": case, "removed": list(rm), "sources": list(srcs), "pool": 177,
            "evals": sum(s["evals"] for s in stages), "sims": sum(s["sims"] for s in stages),
            "seconds": round(sum(pj.get("seconds", 0.0) for pj, _ in srcs.values()), 1), "comps": len(book.best),
            "final": final, "core": R12.core_together(final), "ge195": final["total"] >= TARGET - 1e-9,
            "new_in_final": new_count(final, rm), "new_decks": new_decks(final, rm),
            "squad_src": [where[frozenset(sq)] for _, sq in v[1]],
            "single": {lab: pj["final"]["total"] for lab, (pj, _) in srcs.items()}, **ext, "stages": stages}


def approx_obs(case: str, f4: Sources, o: Mapping[str, Any] | None) -> dict[str, Any]:
    """관찰(시뮬 0): F4 기록에서 새 니케가 든 구성을 지운 「근사 구 풀」 — O와 최선 5덱 · 뼈대 · 공유 니케를 견준다."""
    d = merged(f4, old_account(case, 0), "approx", case, drop=removed(case))
    d.pop("coef", None)
    if o is not None:
        a = [sq for _, sq in d["final"]["squads"]]
        b = [sq for _, sq in o["final"]["squads"]]
        d["vs_O"] = {"O_total": o["final"]["total"], "diff": d["final"]["total"] - o["final"]["total"],
                     "shared_nikkes": R10.shared_nikkes(a, b), "shared_decks": len({frozenset(x) for x in a} & {frozenset(x) for x in b}),
                     "core_O": o["core"]}
    return d


def o_final(srcs: Sources) -> dict[str, Any]:
    """O의 최선 5덱 · 뼈대만(8벌 없이) — 근사를 O와 따로 돌릴 때 견줄 값."""
    book, _, _ = build_book(srcs)
    final = R10.pack_dict(R9.pack_vals(book.best))
    return {"final": final, "core": R12.core_together(final)}


def cmd_merge(args: argparse.Namespace) -> int:
    """O · I1 · 근사(approx). 셋은 서로 독립이라 `--which`로 나눠 프로세스 여럿에서 돌릴 수 있다(8벌 뽑기가 판마다 약 15분)."""
    d = log_dir(args.case, args.log)
    which = args.which.split(",")
    if any(w not in ("O", "I1", "approx") for w in which):
        raise ValueError(f"merge --which는 O · I1 · approx만: {which}")
    srcs = o_sources(args.case, d)
    done = []
    if "O" in which:
        o = merged(srcs, old_account(args.case, 0), "O", args.case)
        write_json(d / "precompute_O.json", o)
        done.append(o)
    if "I1" in which:
        i1 = merged({**srcs, **s4_source()}, full_account(f"pre-{args.case}-I1"), "I1", args.case)
        write_json(d / "precompute_I1.json", i1)
        done.append(i1)
    if "approx" in which:
        ap = approx_obs(args.case, f4_sources(), o_final(srcs))
        write_json(d / "approx.json", ap)
        done.append(ap)
    for x in done:
        print(json.dumps({"pre": x["name"], "evals": x["evals"], "comps": x["comps"], "pack": round(x["final"]["total"], 2),
                          "core": x["core"], "new_decks": x["new_decks"],
                          "sets": [round(t, 1) for t in x["set_totals"]]}, ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 구 풀 사전 계산 (O-s<k>)

def run_old(case: str, seed: int, ev: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    acct = old_account(case, seed)
    assert not set(removed(case)) & set(acct.names)
    sims0 = ev.sim_count
    summ, recs, sess = R10.run_method(acct, "G+E", PRE_BUDGET, ev, pool=177)
    sims = ev.sim_count - sims0
    st = R11.stage_rec(f"구 풀 {177 - len(removed(case))}명 G+E {PRE_BUDGET} 시드 s{seed}", summ, sims)
    out = R11.pre_out(f"O-s{seed}", [st], R11.extract(sess, acct, R11.fit_big), summ, seed=seed, kind="PB15",
                      case=case, removed=list(removed(case)), restarts=[], t195=R12.t_reach(summ["history"]),
                      core=R12.core_together(summ["final"]))
    return out, recs


def cmd_precompute(args: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    seeds = [int(s) for s in str(args.seed).split(",")]
    if any(s not in SEEDS for s in seeds):
        raise ValueError(f"구 풀 사전 계산 시드는 {SEEDS}뿐이다: {seeds}")
    removed(args.case)
    d = log_dir(args.case, args.log)
    d.mkdir(parents=True, exist_ok=True)
    ev = make_evaluator()
    with ev:
        for k in seeds:
            if not (d / f"precompute_O-s{k}.json").exists():
                data, recs = run_old(args.case, k, ev)
                R12.write_pre(d, data["name"], data, recs, ev)
    return 0


# ---------------------------------------------------------------- I2 신캐 집중 이어 붙이기

class PackSession(R9.Session):
    """R9.Session과 같고, 최선 5덱 조립(4만 구성에서 한 번 몇 초)을 평가 수가 바뀔 때만 다시 한다 — 결과는 같다."""

    def __init__(self, acct: Any, ev: Any, budget: int):
        super().__init__(acct, ev, budget)
        self._pack: tuple[int, Any] | None = None

    def seed_book(self, recs: Iterable[Mapping[str, Any]]) -> int:
        """이전 기록을 평가 수에 넣지 않고 책에 싣는다(같은 순서 스쿼드는 다시 요청하지 않는다)."""
        n = 0
        for r in recs:
            sq = tuple(r["squad"])
            self.asked.add(sq)
            if r.get("total_damage") is not None:
                self.book.add(sq, r["total_damage"] / E8)
                n += 1
        self._pack = None
        return n

    def pack(self):
        if self._pack is None or self._pack[0] != self.used:
            self._pack = (self.used, R9.pack_vals(self.book.best))
        return self._pack[1]


def squad_with(t: str, avail: Sequence[str], counts: Counter, rng: random.Random,
               burst: Mapping[str, str] = BURST) -> tuple[str, ...] | None:
    """니케 t가 든 균형 무작위 스쿼드: t의 단계 자리가 있는 구조 틀을 균등하게 고르고, 나머지 자리는 실험 10 `struct_squad`처럼
    그 단계에서 지금까지 가장 적게 나온 니케(동점은 무작위). 같은 단계 안의 배치는 무작위."""
    stages = R10.by_stage(avail, burst)
    st = burst[t]
    frames = [f for f in R10.feasible(stages) if f["123A".index(st)] >= 1]
    if not frames:
        return None
    f = rng.choice(frames)
    members: dict[str, list[str]] = {}
    for s, c in zip("123A", f):
        chosen = [t] if s == st else []
        while len(chosen) < c:
            opts = [m for m in stages[s] if m not in chosen]
            lo = min(counts[m] for m in opts)
            chosen.append(rng.choice([m for m in opts if counts[m] == lo]))
        rng.shuffle(chosen)
        members[s] = chosen
    return R10.arrange(members)


def design_new(sess: Any, new: Sequence[str], n: int, rng: random.Random) -> list[tuple[str, ...]]:
    """1단계 설계: 새 니케마다 몫(n을 고르게 나눔)만큼 그 니케가 든 균형 무작위 스쿼드. 새 니케 차례로 번갈아 놓는다."""
    names = sess.acct.names
    quota = [n // len(new) + (1 if i < n % len(new) else 0) for i in range(len(new))]
    per: list[list[tuple]] = [[] for _ in new]
    counts: Counter = Counter()
    seen: set[frozenset] = set()
    for _round in range(max(quota)):
        for i, t in enumerate(new):
            if len(per[i]) >= quota[i]:
                continue
            for _try in range(200):
                sq = squad_with(t, names, counts, rng)
                if sq is None:
                    break
                c = frozenset(sq)
                if c in seen or c in sess.book.best or not sess.fresh(sq):
                    continue
                seen.add(c)
                counts.update(m for m in sq if m != t)
                per[i].append(sq)
                break
    out: list[tuple] = []
    for j in range(max(quota)):
        out += [p[j] for p in per if j < len(p)]
    return out


def insert_new(sess: Any, sets: Sequence[Sequence[Sequence[str]]], new: Sequence[str], fitf: Callable,
               cap: int) -> list[tuple[str, ...]]:
    """2단계 넣기: O 8벌의 덱마다 · 새 니케마다 같은 단계 한 명을 그 니케로 바꾼 이웃 중 대리 모델 상위 INSERT_TOP개.
    합이 cap을 넘으면 대리 모델 값 순으로 자른다(동점은 스쿼드 순)."""
    acct, book = sess.acct, sess.book
    score = fitf(book, acct.names)
    cands: dict[tuple, float] = {}
    for deck in (tuple(d) for s in sets for d in s):
        for t in new:
            if t in deck:
                continue
            nbs = [deck[:j] + (t,) + deck[j + 1:] for j, m in enumerate(deck) if BURST[m] == BURST[t]]
            nbs = [nb for nb in nbs if frozenset(nb) not in book.best and sess.fresh(nb)]
            for nb in sorted(nbs, key=lambda x: (-score(frozenset(x)), x))[:INSERT_TOP]:
                cands.setdefault(nb, score(frozenset(nb)))
    ranked = list(cands)
    if len(ranked) > cap:
        ranked = sorted(ranked, key=lambda x: (-cands[x], x))[:cap]
    return ranked


def ge_search(sess: Any, tag: str, reserve: int, fitf: Callable) -> dict[str, Any]:
    """실험 10 `run_method`의 G+E 국소 탐색 · 순서 다듬기(출발 뒤 부분) 그대로 — 출발은 지금 책의 최선 5덱이다."""
    p0 = sess.pack()
    history = [{"evals": sess.used, "pack": p0[0], "kick": False}]
    lineage: set[frozenset] | None = None
    lin_val = p0[0]
    kicks: list[dict[str, Any]] = []
    stalled = False
    while sess.left > reserve:
        kicked = False
        if stalled:
            stalled = False
            best_now, used0 = sess.pack()[0], sess.used
            lin = R10.do_kick(sess, random.Random(f"exp15-kick-{tag}-{len(kicks) + 1}"), BURST, cap=sess.left - reserve)
            if lin is None:
                break
            kicks.append({"evals": used0, "best": best_now})
            lineage, kicked = lin, True
            lin_val = R10.lineage_pack(sess, lineage)
            if sess.left <= reserve:
                history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": True})
                break
        n = min(R10.ROUND, sess.left - reserve)
        pick = R10.local_round(sess, n, lineage, fitf)
        if not pick or not sess.run(pick, f"탐색 {len(history)}", cap=n):
            if not kicked:
                stalled = True
                continue
            history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": True})
            break
        history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": kicked})
        cur = R10.lineage_pack(sess, lineage)
        if cur <= lin_val + 1e-9:
            stalled = True
        lin_val = cur
    pre_order = {"evals": sess.used, "pack": sess.pack()[0]}
    for i, k in enumerate(kicks):
        nxt = kicks[i + 1]["best"] if i + 1 < len(kicks) else pre_order["pack"]
        k["improved"] = nxt > k["best"] + 1e-9
    best = sess.pack()
    tops = [sq for _, sq in best[1]] + [sq for _, sq in sorted(sess.book.best.values(), reverse=True)[:R9.ORDER_TOP]]
    orders = list(dict.fromkeys(p for sq in dict.fromkeys(tops) for p in R2.distinct_orders(sq, BURST) if sess.fresh(p)))
    sess.run(orders, "순서")
    history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": False})
    return {"history": history, "pre_order": pre_order, "kicks": kicks}


def stage_of(phase: str) -> str:
    if phase in ("신캐 설계", "신캐 넣기", "순서"):
        return phase
    return "국소 탐색"   # 탐색 k · 킥


def run_update(case: str, o_srcs: Sources, o_pre: Mapping[str, Any], ev: Any,
               budget: int = I2_BUDGET) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """I2: O의 합친 기록 위에서 (1) 신캐 설계 (2) 신캐 넣기 (3) G+E 국소 탐색 · 순서 다듬기(예산의 1/8). 평가 수 = 새로 한 것만."""
    new = removed(case)
    acct = full_account(f"pre-{case}-I2")
    fitf = R11.fit_big
    sess = PackSession(acct, ev, budget)
    for _, recs in o_srcs.values():
        sess.seed_book(recs)
    start = sess.pack()
    t0, sims0 = time.time(), ev.sim_count
    reserve = budget // 8
    sims: dict[str, int] = {}
    n1 = max(DESIGN_MIN, DESIGN_PER * len(new))
    s0 = ev.sim_count
    sess.run(design_new(sess, new, n1, random.Random(f"exp15-design-{case}")), "신캐 설계", cap=min(n1, sess.left - reserve))
    sims["신캐 설계"] = ev.sim_count - s0
    n_decks = sum(len(s) for s in o_pre["sets"])
    cap2 = min(INSERT_TOP * n_decks * len(new), int(INSERT_SHARE * budget), sess.left - reserve)
    s0 = ev.sim_count
    sess.run(insert_new(sess, o_pre["sets"], new, fitf, cap2), "신캐 넣기", cap=cap2)
    sims["신캐 넣기"] = ev.sim_count - s0
    after_insert = {"evals": sess.used, "pack": sess.pack()[0]}
    s0 = ev.sim_count
    loop = ge_search(sess, f"{case}-I2", reserve, fitf)
    sims["국소 탐색 · 순서"] = ev.sim_count - s0
    used = Counter(stage_of(r["phase"]) for r in sess.records)
    stages = [{"what": f"I2 {k}", "evals": used.get(k, 0)} for k in ("신캐 설계", "신캐 넣기", "국소 탐색", "순서")]
    upd = {"budget": budget, "evals": sess.used, "sims": ev.sim_count - sims0, "seconds": round(time.time() - t0, 1),
           "errors": sum(r["error"] is not None for r in sess.records), "stages": stages, "stage_sims": sims,
           "design_n": n1, "insert_cap": cap2, "start": {"pack": start[0], "core": R12.core_together(R10.pack_dict(start))},
           "after_insert": after_insert, **loop}
    # 책 = O 기록 + 새 기록. 8벌 · 계수는 「출시 뒤」 177명으로 뽑는다
    v = sess.pack()
    final = R10.pack_dict(v)
    ext = R11.extract(sess, acct, fitf)
    fresh = {frozenset(r["squad"]) for r in sess.records if r.get("total_damage") is not None}
    stages_all = [{"what": f"{lab} 기록(재사용)", "evals": pj["evals"], "sims": pj["sims"]} for lab, (pj, _) in o_srcs.items()]
    stages_all.append({"what": "I2 신캐 집중 탐색", "evals": sess.used, "sims": upd["sims"]})
    out = {"name": "I2", "case": case, "removed": list(new), "sources": [*o_srcs, "I2"], "pool": 177,
           "evals": sum(s["evals"] for s in stages_all), "sims": sum(s["sims"] for s in stages_all),
           "seconds": round(sum(pj.get("seconds", 0.0) for pj, _ in o_srcs.values()) + upd["seconds"], 1),
           "comps": len(sess.book.best), "final": final, "core": R12.core_together(final),
           "ge195": final["total"] >= TARGET - 1e-9, "new_in_final": new_count(final, new), "new_decks": new_decks(final, new),
           "squad_src": [["I2"] if frozenset(sq) in fresh else ["O"] for _, sq in v[1]],
           "single": {lab: pj["final"]["total"] for lab, (pj, _) in o_srcs.items()}, **ext, "stages": stages_all,
           "update": upd, "t195": R12.t_reach(loop["history"])}
    return out, sess.records


def cmd_update(args: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    d = log_dir(args.case, args.log)
    if (d / "precompute_I2.json").exists():
        print(f"이미 있다: {d / 'precompute_I2.json'}", file=sys.stderr)
        return 0
    o_srcs = o_sources(args.case, d)
    o_pre = load_json(d / "precompute_O.json")
    ev = make_evaluator()
    with ev:
        data, recs = run_update(args.case, o_srcs, o_pre, ev, args.budget)
        data["evaluator"] = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
    write_records(d / "precompute_I2.jsonl.gz", recs)
    write_json(d / "precompute_I2.json", data)
    u = data["update"]
    print(json.dumps({"pre": "I2", "evals": u["evals"], "sims": u["sims"], "s": u["seconds"],
                      "stages": {s["what"]: s["evals"] for s in u["stages"]}, "pack": round(data["final"]["total"], 2),
                      "core": data["core"], "new_decks": data["new_decks"],
                      "sets": [round(t, 1) for t in data["set_totals"]]}, ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 계정 탐색

def load_pre(method: str, case: str, d: Path) -> dict[str, Any]:
    if method == "F4":
        return load_json(EXP13_LOG / "precompute_U4.json")
    if method in ("O", "I1", "I2"):
        return load_json(d / f"precompute_{method}.json")
    raise ValueError(f"실험 15 기호는 {METHODS}뿐이다: {method}")


def run_account(sc: Mapping[str, Any], method: str, budget: int, ev: Any, pre: Mapping[str, Any],
                case: str, missing_new: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    acct = val_account(sc, case if missing_new else None)
    summ, recs, _ = R10.run_method(acct, "P", budget, ev, pre=pre, pool=177)
    summ["method"] = method
    summ["case"] = case
    summ["missing_new"] = missing_new
    summ.pop("alt20", None)
    summ["new_in_final"] = new_count(summ["final"], removed(case))
    return summ, recs


def cmd_search(args: argparse.Namespace) -> int:
    rm = removed(args.case)
    d = log_dir(args.case, args.log)
    scs = R10.scenarios("val")
    if args.only:
        want = set(args.only.split(","))
        scs = [s for s in scs if s["id"] in want]
    methods = args.methods.split(",")
    for m in methods:
        if m not in METHODS:
            raise ValueError(f"실험 15 기호는 {METHODS}뿐이다: {m}")
    if "F4" in methods and not args.missing_new:
        raise ValueError("보유 조건 F4는 실험 13 U4 기록을 쓴다 — 새로 돌리지 않는다")
    budgets = [int(b) for b in args.budgets.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    R10.pack_alt20 = lambda *a, **k: (0.0, [])  # 실험 11 · 12와 같이 대안 (b)는 계산하지 않는다
    pres = {m: load_pre(m, args.case, d) for m in methods}
    sid = (lambda s: f"{s}n") if args.missing_new else (lambda s: s)
    tasks = [(s, m, b) for b in sorted(budgets, reverse=True) for s in scs for m in methods
             if not (args.out / f"{R10.run_name(sid(s['id']), 177, m, b)}.json").exists()]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()
    lock = threading.Lock()

    def work(task):
        s, m, b = task
        summ, recs = run_account(s, m, b, ev, pres[m], args.case, args.missing_new)
        name = R10.run_name(summ["scenario"], 177, m, b)
        R10.write_run(args.out, name, summ, recs)
        with lock:
            print(json.dumps({"run": name, "pack": round(summ["final"]["total"], 2), "new": summ["new_in_final"],
                              "evals": summ["evals"], "s": summ["seconds"], "t": round(time.time() - t0),
                              "sims": ev.sim_count}, ensure_ascii=False), flush=True)

    with ev:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for f in [pool.submit(work, t) for t in tasks]:
                f.result()
        print(f"{args.case} 새 니케 {len(rm)}명 · 실행 {len(tasks)}개 · 시뮬 {ev.sim_count}회 · 캐시 {ev.cache_hits}회 · "
              f"{time.time() - t0:.0f}초 · 평가기 {ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_case(p):
        p.add_argument("--case", required=True, choices=tuple(CASES))
        p.add_argument("--log", type=Path, help="기록 폴더(기본 cases/<경우>/run_log)")
        return p

    p = with_case(sub.add_parser("precompute"))
    p.add_argument("--seed", default="0")
    g = with_case(sub.add_parser("merge"))
    g.add_argument("--which", default="O,I1,approx")
    u = with_case(sub.add_parser("update"))
    u.add_argument("--budget", type=int, default=I2_BUDGET)
    s = with_case(sub.add_parser("search"))
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--methods", required=True)
    s.add_argument("--budgets", default=",".join(map(str, BUDGETS)))
    s.add_argument("--missing-new", action="store_true")
    s.add_argument("--only")
    s.add_argument("--workers", type=int, default=2)
    c = sub.add_parser("collect")
    c.add_argument("--runs", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--name", required=True)
    args = ap.parse_args(argv)
    return {"precompute": cmd_precompute, "merge": cmd_merge, "update": cmd_update, "search": cmd_search,
            "collect": R10.cmd_collect}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
