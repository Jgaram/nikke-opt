"""실험 33 — 역할 지문 · 역할 벡터(README). Q1: 새 평가기 사전 계산(니케별 딜 포함) → 기준 덱 → 넣어 보기 → 지문.

    python experiments/33_role_vectors/run33.py attrs                         → attrs.json (시뮬 0)
    source .cache/evaluators.env && python experiments/33_role_vectors/run33.py pre --element 전격 --seed 0
        → run_log/pre/<속성>_s<k>.jsonl.gz · <속성>_s<k>.json
    python experiments/33_role_vectors/run33.py refs                          → refs.json (시뮬 0, 사전 계산 10개가 있어야 한다)
    source .cache/evaluators.env && python experiments/33_role_vectors/run33.py probe --set R
        → run_log/probe_<세트>.jsonl.gz (R · R2 · T)
    python experiments/33_role_vectors/run33.py q1                            → q1.md · run_log/q1.json (시뮬 0)

- 사전 계산 = 실험 30 B와 같은 절차(시드 s0 · s1 각 G+E 12,500평가, 전원 보유 · 상, 기본 적 + 보스 속성, 코어 없음, 기본 레이어).
  풀은 SSR 177명(실험 10 `roster_ssr.json`) — 신캐 3명(Q4)은 넣지 않는다(「출시 전」).
- 기록마다 니케별 딜(`members`, 스쿼드 순서)을 함께 남긴다. 사전 계산 코드는 고치지 않고 평가기를 감싸 받는다(`MemberLog`).
- 기준 덱 · 칸 · 넣어 보기 · 지문 정의는 README §Q1 사전 등록 그대로다.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
ROOT = EXPS.parent
LOG = HERE / "run_log"
PRE = LOG / "pre"
ATTRS = HERE / "attrs.json"
REFS = HERE / "refs.json"
sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R30 = sys.modules.get("run30") or _load("run30", EXPS / "30_element_map" / "run30.py")
R10 = R30.R10
ROSTER = EXPS / "10_rankerless_start" / "roster_ssr.json"
E8 = 1e8

# ---------------------------------------------------------------- 사전 등록한 값(README §Q1)
ELEMENTS = R30.ELEMENTS                     # ("전격", "풍압", "철갑", "수냉", "작열")
SEEDS = (0, 1)
SEED_BUDGET = R30.SEED_BUDGET               # 12,500 — 실험 30 B와 같다
NEW_NIKKES = ("홍련 : 신살", "라푼젤 : 생츄어리", "마리안 : 퀸")   # Q4 실제 신캐(풀에 넣지 않는다)
# 게임 규칙: 왼쪽 코드가 오른쪽 속성 보스에 우월 코드(우코)다. 스킬 효과가 아니라 속성 상성이다. Q1에서 시뮬로 맞는지 확인한다.
BEATS = {"작열": "풍압", "풍압": "철갑", "철갑": "전격", "전격": "수냉", "수냉": "작열"}
TOP_PER_ELEMENT = 200                       # 기준 덱 후보: 속성마다 구성 값 상위 200
SHARE_MAX = 2                               # 기준 덱끼리 공유 니케 2명 이하
K_R, K_R2 = 20, 10                          # 기준 덱 수: R(지문) · R2(재현성 — R 밖 후보에서 같은 규칙)
K_T = 10                                    # 토브 확인: R 앞 10개 중 토브가 없는 덱
TOVE, BREAD = "토브", "브리드 : 사일런트 트랙"
TEST_PREFIX = "test_"                       # 계산기 시험용 니케 — 기준 덱 후보 · 순위에서 뺀다(넣어 보기에는 넣는다)


# ---------------------------------------------------------------- 자료
def roster() -> dict[str, str]:
    """SSR 177명 → 버스트 단계("1" · "2" · "3" · "A")."""
    return dict(json.loads(ROSTER.read_text(encoding="utf-8"))["roster"])


def extract_attrs(parsed: Mapping[str, Mapping[str, Any]], names: Iterable[str]) -> dict[str, dict[str, str]]:
    """계산기 공개 자료에서 이름 · 무기 · 코드 · 단계 · 클래스만 뽑는다(스킬 효과는 뽑지 않는다)."""
    out = {}
    for n in names:
        v = parsed[n]
        out[n] = {"weapon": v["weapon_type"], "code": v["element_code"], "stage": str(v["burst_stage"]), "class": v["class"]}
    return out


def attrs() -> dict[str, dict[str, str]]:
    return json.loads(ATTRS.read_text(encoding="utf-8"))["attrs"]


def adv_element(code: str) -> str:
    """이 코드가 우코인 보스 속성."""
    return BEATS[code]


def write_recs(path: Path, recs: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def load_recs(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- 니케별 딜 받기
def member_vec(squad: Sequence[str], members: Sequence[Mapping[str, Any]] | None) -> list[int] | None:
    """평가기 `members`(이름 · damage)를 스쿼드 순서의 정수 목록으로. 이름이 맞지 않으면 None."""
    if not members:
        return None
    d = {m["name"]: m["damage"] for m in members}
    if set(d) != set(squad) or len(members) != len(squad):
        return None
    return [int(d[n]) for n in squad]


class MemberLog:
    """평가기를 감싸 결과의 니케별 딜을 스쿼드 순서로 모은다. 나머지 속성은 원래 평가기로 넘긴다."""

    def __init__(self, ev: Any):
        self.ev = ev
        self.log: dict[tuple, list[int]] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self.ev, name)

    def evaluate(self, reqs: Sequence[Any]) -> list[Any]:
        res = self.ev.evaluate(reqs)
        for q, r in zip(reqs, res):
            v = member_vec(q.squad, (r.raw or {}).get("members"))
            if v is not None:
                self.log[tuple(q.squad)] = v
        return res

    def attach(self, recs: Sequence[dict[str, Any]]) -> int:
        """기록마다 `members`를 붙인다. 붙이지 못한(오류 등) 기록 수를 돌려준다."""
        miss = 0
        for r in recs:
            r["members"] = self.log.get(tuple(r["squad"]))
            miss += r["members"] is None and r.get("total_damage") is not None
        return miss


def pre_path(el: str, k: int, base: Path | None = None) -> Path:
    return (base or PRE) / f"{el}_s{k}.jsonl.gz"


def pre_book(el: str) -> dict[frozenset, tuple[float, tuple]]:
    """속성 하나의 사전 계산 두 시드를 합친 책: 구성 → (최고 딜(억), 그 배치 순서)."""
    return R30.book_of([r for k in SEEDS for r in load_recs(pre_path(el, k))])


# ---------------------------------------------------------------- 기준 덱
def pick_refs(cands: Sequence[tuple[float, tuple]], k: int, share_max: int = SHARE_MAX,
              avoid: Iterable[frozenset] = ()) -> list[tuple]:
    """(점수, 배치 순서) 후보를 점수 내림차순으로 보며 이미 고른 덱 모두와 공유 ≤ share_max면 고른다. avoid 구성은 건너뛴다."""
    avoid = set(avoid)
    out: list[tuple] = []
    for _, sq in sorted(cands, key=lambda x: (-x[0], x[1])):
        c = frozenset(sq)
        if c in avoid:
            continue
        if all(len(c & frozenset(o)) <= share_max for o in out):
            out.append(tuple(sq))
            if len(out) == k:
                break
    return out


def ref_candidates(books: Mapping[str, Mapping[frozenset, tuple[float, tuple]]], top: int = TOP_PER_ELEMENT
                   ) -> list[tuple[float, tuple]]:
    """속성마다 구성 값 상위 top → (그 속성 최선 대비 비율, 배치 순서). 여러 속성에 들면 비율이 가장 높은 속성의 것. 시험용 니케가 든 구성은 뺀다."""
    best: dict[frozenset, tuple[float, tuple]] = {}
    for el in sorted(books):
        b = books[el]
        if not b:
            continue
        top_v = max(v for v, _ in b.values())
        ranked = sorted(b.items(), key=lambda kv: (-kv[1][0], kv[1][1]))[:top]
        for c, (v, sq) in ranked:
            if any(n.startswith(TEST_PREFIX) for n in c):
                continue
            r = v / top_v
            if c not in best or r > best[c][0]:
                best[c] = (r, tuple(sq))
    return list(best.values())


def slot_of(deck: Sequence[str], i: int, stage: str, stages: Mapping[str, str]) -> int | None:
    """덱 i의 단계 칸: 배치 순서에서 그 단계 니케들 중 (i mod 수)번째의 위치. A 단계(레드 후드)는 3단계 칸에 넣는다."""
    s = "3" if stage == "A" else stage
    pos = [j for j, n in enumerate(deck) if stages[n] == s]
    return pos[i % len(pos)] if pos else None


def probe_squads(deck: Sequence[str], i: int, stages: Mapping[str, str]) -> list[tuple[str, str, tuple]]:
    """기준 덱 i의 넣어 보기: (단계, 넣은 니케, 스쿼드). 단계마다 칸 하나에 그 단계의 모든 니케(덱에 없는)를 넣는다. 원래 덱은 ("0", "", 덱)."""
    out = [("0", "", tuple(deck))]
    for st in ("1", "2", "3", "A"):
        j = slot_of(deck, i, st, stages)
        if j is None:
            continue
        for x in sorted(n for n, s in stages.items() if s == st):
            if x in deck:
                continue
            sq = list(deck)
            sq[j] = x
            out.append((st, x, tuple(sq)))
    return out


def tove_squads(deck: Sequence[str], i: int, stages: Mapping[str, str]) -> list[tuple[str, str, tuple]] | None:
    """토브 확인: 덱 i의 1단계 칸을 토브로 바꾼 덱(d_T)에서 2단계 칸에 2단계 니케를 모두 넣는다. 토브가 이미 들면 None."""
    if TOVE in deck:
        return None
    j1 = slot_of(deck, i, "1", stages)
    if j1 is None:
        return None
    dt = list(deck)
    dt[j1] = TOVE
    j2 = slot_of(deck, i, "2", stages)
    out = [("0", "", tuple(dt))]
    for x in sorted(n for n, s in stages.items() if s == "2"):
        if x in dt:
            continue
        sq = list(dt)
        sq[j2] = x
        out.append(("2", x, tuple(sq)))
    return out


# ---------------------------------------------------------------- 지문(시뮬 0)
def _med(xs: Sequence[float]) -> float | None:
    return statistics.median(xs) if xs else None


def _iqr_over_med(xs: Sequence[float]) -> float | None:
    if len(xs) < 4:
        return None
    q = statistics.quantiles(xs, n=4)
    m = statistics.median(xs)
    return (q[2] - q[0]) / m if m else None


def cells(recs: Sequence[Mapping[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """넣어 보기 기록 → 칸((세트, 덱), 단계, 속성)마다 {"base": 원래 덱 총딜, "rows": {니케: (스쿼드, 니케별 딜)}}."""
    base: dict[tuple, float] = {}
    out: dict[tuple, dict[str, Any]] = {}
    for r in recs:
        if r.get("total_damage") is None or r.get("members") is None:
            continue
        if r["stage"] == "0":
            base[(r["set"], r["deck"], r["element"])] = float(r["total_damage"])
    for r in recs:
        if r["stage"] == "0" or r.get("total_damage") is None or r.get("members") is None:
            continue
        b = base.get((r["set"], r["deck"], r["element"]))
        if not b:
            continue
        st = "3" if r["stage"] == "A" else r["stage"]          # 레드 후드는 3단계 칸에 넣었다 — 같은 칸으로 본다
        c = out.setdefault(((r["set"], r["deck"]), st, r["element"]), {"base": b, "rows": {}})
        c["rows"][r["x"]] = (tuple(r["squad"]), [float(v) for v in r["members"]])
    return out


def cell_values(cell: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """칸 하나에서 니케마다 own(본인 딜 / 원래 덱 총딜), own_abs(본인 딜), mate(동료 딜 합 / 원래 덱 총딜 − 칸 중앙),
    동료별 상대 변화((동료 딜 − 칸 중앙) / 칸 중앙). 기준을 중앙으로 두어 강한 버퍼 몇 명에 끌리지 않게 한다."""
    b, rows = cell["base"], cell["rows"]
    if not rows:
        return {}
    pos = {}
    for x, (sq, _) in rows.items():
        pos[x] = sq.index(x)
    mates = {x: (sum(m) - m[pos[x]]) / b for x, (_, m) in rows.items()}
    med_mates = statistics.median(mates.values())
    # 동료 자리별 중앙 딜(칸 안 모든 X) — 동료는 칸 안에서 같은 니케다
    any_sq = next(iter(rows.values()))[0]
    j0 = pos[next(iter(rows))]
    others = [j for j in range(len(any_sq)) if j != j0]
    med_j = {j: statistics.median(m[j] for _, m in rows.values()) for j in others}
    out = {}
    for x, (sq, m) in rows.items():
        out[x] = {"own": m[pos[x]] / b, "own_abs": m[pos[x]], "mate": mates[x] - med_mates,
                  "per_mate": {sq[j]: (m[j] - med_j[j]) / med_j[j] for j in others if med_j[j] > 0}}
    return out


def fingerprints(recs: Sequence[Mapping[str, Any]], at: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, Any]]:
    """README §Q1 지문. 우코 속성 칸은 own_adv · adv_lift에만 쓰고 나머지 성분은 우코가 아닌 속성 칸으로 낸다.
    adv_lift는 덱 총딜이 아니라 본인 딜 절댓값으로 비교한다(같은 코드 동료의 우코가 덱 총딜을 함께 올리므로)."""
    per: dict[str, list[tuple]] = defaultdict(list)          # x → [(deck, element, values)]
    for (deck, _st, el), c in cells(recs).items():
        for x, v in cell_values(c).items():
            per[x].append((deck, el, v))
    out: dict[str, dict[str, Any]] = {}
    for x, rows in per.items():
        adv = adv_element(at[x]["code"])
        non = [v for _, el, v in rows if el != adv]
        own_non = [v["own"] for v in non]
        by_el: dict[str, list[float]] = defaultdict(list)
        own_de: dict[tuple, float] = {}                         # (덱, 속성) → 본인 딜 절댓값 — 같은 덱 · 자리의 속성 비교
        for d, el, v in rows:
            by_el[el].append(v["own"])
            own_de[(d, el)] = v["own_abs"]
        spreads = [s for el, xs in by_el.items() if el != adv for s in [_iqr_over_med(xs)] if s is not None]
        lifts = []
        for d in {d for d, _, _ in rows}:
            o_adv = own_de.get((d, adv))
            o_non = [own_de[(d, el)] for el in ELEMENTS if el != adv and (d, el) in own_de]
            if o_adv is not None and o_non and statistics.median(o_non) > 0:
                lifts.append(o_adv / statistics.median(o_non))
        boost_w: dict[str, list[float]] = defaultdict(list)
        boost_s: dict[str, list[float]] = defaultdict(list)
        for v in non:
            for y, rel in v["per_mate"].items():
                boost_w[at[y]["weapon"]].append(rel)
                boost_s[at[y]["stage"]].append(rel)
        el_med = {el: statistics.median(xs) for el, xs in by_el.items()}
        out[x] = {
            "n_cells": len(rows),
            "dealer": _med(own_non),
            "buffer": _med([v["mate"] for v in non]),
            "spread": _med(spreads),
            "own_adv": _med(by_el.get(adv, [])),
            "adv_lift": _med(lifts),
            "adv_argmax": max(el_med, key=lambda e: (el_med[e], e)) if el_med else None,
            "boost_weapon": {w: statistics.median(xs) for w, xs in sorted(boost_w.items())},
            "boost_stage": {s: statistics.median(xs) for s, xs in sorted(boost_s.items())},
        }
    return out


def tove_lifts(probe: Sequence[Mapping[str, Any]], tove: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """2단계 니케 X마다 median over (덱, 속성) [X 본인 딜(d_T + X) / X 본인 딜(d + X)]."""
    def own(recs):
        m = {}
        for r in recs:
            if r.get("members") is None or r["stage"] != "2":
                continue
            m[(r["deck"], r["element"], r["x"])] = r["members"][list(r["squad"]).index(r["x"])]
        return m
    a, t = own(probe), own(tove)
    lifts: dict[str, list[float]] = defaultdict(list)
    for (d, el, x), v in t.items():
        b = a.get((d, el, x))
        if b:
            lifts[x].append(v / b)
    return {x: statistics.median(v) for x, v in lifts.items()}


def rank_of(vals: Mapping[str, float | None], x: str, names: Iterable[str]) -> tuple[int, int]:
    """names 중 vals 내림차순 x의 순위(1부터)와 대상 수. 값이 없는 니케는 뺀다."""
    pool = [n for n in names if vals.get(n) is not None]
    order = sorted(pool, key=lambda n: (-vals[n], n))
    return order.index(x) + 1, len(order)


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    def ranks(v):
        idx = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            for k in range(i, j + 1):
                r[idx[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    if len(set(ra)) < 2 or len(set(rb)) < 2:
        return None                                     # 한쪽이 모두 같은 값 — 상관을 정할 수 없다
    return statistics.correlation(ra, rb)


# ---------------------------------------------------------------- 명령
def cmd_attrs(a: argparse.Namespace) -> int:
    calc = Path(os.environ.get("NIKKE_CALC_DIR", "/home/user/jgaram/nikke-calc"))
    path = calc / "data" / "parsed_nikke.json"
    raw = path.read_bytes()
    parsed = json.loads(raw)
    names = list(roster()) + list(NEW_NIKKES)
    out = {"meta": {"source": "github.com/Jgaram/nikke-calc data/parsed_nikke.json",
                    "commit": os.popen(f"git -C {calc} rev-parse HEAD").read().strip(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "rule": "SSR 177명(roster_ssr.json) + Q4 신캐 3명 — weapon_type · element_code · burst_stage · class만"},
           "attrs": extract_attrs(parsed, names)}
    ATTRS.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out['attrs'])}명 → {ATTRS}")
    return 0


def cmd_pre(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    el, k = a.element, a.seed
    if el not in ELEMENTS or k not in SEEDS:
        raise ValueError(f"--element {ELEMENTS} · --seed {SEEDS}")
    out_path = pre_path(el, k, Path(a.log) if a.log else None)
    if out_path.exists():
        print(f"있음: {out_path}")
        return 0
    with make_evaluator() as base:
        ev = MemberLog(base)
        sims0, t0 = base.sim_count, time.time()
        s, recs, _ = R10.run_method(R30.account(el, k), "G+E", a.budget, ev, pool=177)
        miss = ev.attach(recs)
        write_recs(out_path, recs)
        summ = {"element": el, "seed": k, "budget": a.budget, "evals": s["evals"], "sims": base.sim_count - sims0,
                "seconds": round(time.time() - t0, 1), "best": s["final"]["total"], "errors": s["errors"],
                "members_missing": miss, "evaluator": base.version}
    out_path.with_suffix("").with_suffix(".json").write_text(json.dumps(summ, ensure_ascii=False, indent=1) + "\n",
                                                             encoding="utf-8")
    print(json.dumps({k: v for k, v in summ.items() if k != "evaluator"}, ensure_ascii=False), flush=True)
    return 0


def cmd_refs(a: argparse.Namespace) -> int:
    books = {el: pre_book(el) for el in ELEMENTS}
    cands = ref_candidates(books)
    r = pick_refs(cands, K_R)
    r2 = pick_refs(cands, K_R2, avoid={frozenset(d) for d in r})
    st = roster()
    t = [i for i, d in enumerate(r[:K_T]) if TOVE not in d]
    out = {"rule": f"속성마다 상위 {TOP_PER_ELEMENT} 구성 · 최선 대비 비율 내림차순 · 공유 ≤ {SHARE_MAX}",
           "R": [list(d) for d in r], "R2": [list(d) for d in r2], "T": t,
           "frames": {"R": [sorted(st[n] for n in d) for d in r]}}
    REFS.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"R {len(r)} · R2 {len(r2)} · T {len(t)} → {REFS}")
    return 0


def probe_plan(set_name: str) -> list[dict[str, Any]]:
    """세트의 요청 목록: {set, deck, stage, x, element, squad}."""
    refs = json.loads(REFS.read_text(encoding="utf-8"))
    st = roster()
    plan = []
    if set_name in ("R", "R2"):
        for i, d in enumerate(refs[set_name]):
            for stage, x, sq in probe_squads(d, i, st):
                for el in ELEMENTS:
                    plan.append({"set": set_name, "deck": i, "stage": stage, "x": x, "element": el, "squad": list(sq)})
    elif set_name == "T":
        for i in refs["T"]:
            for stage, x, sq in tove_squads(refs["R"][i], i, st) or []:
                for el in ELEMENTS:
                    plan.append({"set": "T", "deck": i, "stage": stage, "x": x, "element": el, "squad": list(sq)})
    else:
        raise ValueError(set_name)
    return plan


def cmd_probe(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    path = LOG / f"probe_{a.set}.jsonl.gz"
    if path.exists():
        print(f"있음: {path}")
        return 0
    plan = probe_plan(a.set)
    out: list[dict[str, Any]] = []
    t0 = time.time()
    with make_evaluator() as ev:
        sims0 = ev.sim_count
        step = 2000
        for i in range(0, len(plan), step):
            chunk = plan[i:i + step]
            res = ev.evaluate([EvalRequest(p["squad"], boss=None, options=R30.options(p["element"])) for p in chunk])
            for p, r in zip(chunk, res):
                out.append(dict(p, total_damage=r.total_damage, members=member_vec(p["squad"], r.raw.get("members")),
                                error=r.error))
            print(json.dumps({"set": a.set, "done": len(out), "of": len(plan), "sims": ev.sim_count - sims0,
                              "seconds": round(time.time() - t0, 1)}, ensure_ascii=False), flush=True)
        summ = {"set": a.set, "requests": len(plan), "sims": ev.sim_count - sims0, "seconds": round(time.time() - t0, 1),
                "errors": sum(r["error"] is not None for r in out), "evaluator": ev.version}
    write_recs(path, out)
    (LOG / f"probe_{a.set}.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summ.items() if k != "evaluator"}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("attrs")
    q = sub.add_parser("pre")
    q.add_argument("--element", required=True)
    q.add_argument("--seed", type=int, required=True)
    q.add_argument("--budget", type=int, default=SEED_BUDGET)    # 시운전용(본 실행은 12,500)
    q.add_argument("--log", default=None)                         # 시운전용 출력 폴더
    sub.add_parser("refs")
    q = sub.add_parser("probe")
    q.add_argument("--set", required=True, choices=("R", "R2", "T"))
    sub.add_parser("q1")
    a = p.parse_args(argv)
    if a.cmd == "q1":
        A1 = sys.modules.get("analyze33") or _load("analyze33", HERE / "analyze33.py")
        return A1.cmd_q1()
    return {"attrs": cmd_attrs, "pre": cmd_pre, "refs": cmd_refs, "probe": cmd_probe}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
