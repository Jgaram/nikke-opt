"""실험 38 — 1단계(시뮬 0): 우리 사전 계산이 랭커 덱을 왜 못 가 보나. README §1단계.

    python -I experiments/38_ranker_miss/an38.py replay --season 40 --seed 0   # ③ 후보 생성 · 대리 모델 재생 → replay/S40_s0.json
    python -I experiments/38_ranker_miss/an38.py visit --season 40               # ① ② ④ → visit/S40.json (analyze가 없으면 만든다)
    python -I experiments/38_ranker_miss/an38.py analyze                       # ① 방문 · ② 합쳐 묶기 · ④ 사전 값 편향 + ③ 모으기
                                                                               #   → analysis.json · results.md

실험 36 기록(평가기 nikke-calc-rs 8bc51a2)만 읽는다. 새 시뮬 없음. 코어 없음만.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP36 = HERE.parent / "36_season_refresh"
sys.path[:0] = [str(EXP36), str(HERE.parent.parent)]
import run36  # noqa: E402
from run36 import run31, R9, R10, R30  # noqa: E402
from nikke_opt import similarity as SIM  # noqa: E402

S4 = R10.S4
SEASONS = run31.SEASONS
FIT_AT = (1000, 3000, 6000, 9000)   # 대리 모델을 다시 맞추는 시점(시드마다 평가 수)
REF_N = 500                         # 비교 대상: 시점 바로 뒤에 처음 평가한 구성 수
OTHER_TOP = 300                     # 비교 대상 2: 다른 시드 기록 중 이 시드가 아직 안 본 값 상위 구성 수
PACK_EVERY = 5                      # 라운드 경계 몇 번마다 최선 5덱을 다시 묶나
PACK_SHARE = int(R9.ROUND * R9.PACK_SHARE)        # 70 — 덱 고치기 몫
NB_SHARE = R9.ROUND - PACK_SHARE                  # 30 — 이웃 몫
CATS = ("V5", "V4s", "V4x", "V3")                 # 방문 범주(아래 visit 참고)
RLOG = HERE / "replay"
VLOG = HERE / "visit"
E8 = 1e8


def jload(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def jdump(p: Path, x: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def med(xs: Sequence[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def wmed(pairs: Sequence[tuple[float, float]]) -> float | None:
    """가중 중앙값 (값, 가중치)."""
    ps = sorted((v, w) for v, w in pairs if v is not None and w > 0)
    if not ps:
        return None
    half, acc = sum(w for _, w in ps) / 2, 0.0
    for v, w in ps:
        acc += w
        if acc >= half:
            return v
    return ps[-1][0]


# ---------------------------------------------------------------- 자료

def recs_of(s: int, seed: int) -> list[dict[str, Any]]:
    return run31.load_recs(run36.sdir(s) / f"B_s{seed}.jsonl.gz")


def burst_of(s: int) -> dict[str, str]:
    return {n: v["burst"] for n, v in run31.account(s, 0).owned.items()}


def ranker_decks(s: int) -> dict[frozenset, dict[str, Any]]:
    """랭커 덱(상위 40 ∪ 대표 5덱 ∪ 1위 5덱) → 값(랭커 순서 사전 값, 순서가 여럿이면 최고) · 사용 수 · 표시."""
    r = run31.season(s)["rankers"]
    rv = jload(run36.sdir(s) / "rankers.json")["squads"]
    out: dict[frozenset, dict[str, Any]] = {}
    for k, e in rv.items():
        v = e.get("nocore")
        if v is None:
            continue
        q = tuple(k.split(","))
        c = frozenset(q)
        x = out.setdefault(c, {"members": sorted(c), "value": v, "order": list(q), "count": 0, "tags": []})
        if v > x["value"]:
            x["value"], x["order"] = v, list(q)
    for q in r["squads"]:
        out[frozenset(q["members"])]["count"] += q["count"]
    for tag in ("top_five", "rank1"):
        for q in r[tag]["squads"]:
            out[frozenset(q)]["tags"].append(tag)
    return out


def same_stage_swap(a: frozenset, b: frozenset, burst: Mapping[str, str]) -> bool:
    """a · b가 같은 단계 니케 한 명만 다르다."""
    if len(a & b) != 4:
        return False
    (x,), (y,) = a - b, b - a
    return burst[x] == burst[y]


class Index:
    """평가한 구성의 니케별 역색인 — 랭커 덱과 가장 많이 겹친 구성 찾기."""

    def __init__(self, comps):
        self.by: dict[str, list[frozenset]] = {}
        for c in comps:
            for n in c:
                self.by.setdefault(n, []).append(c)

    def best_overlap(self, c: frozenset, burst: Mapping[str, str]) -> tuple[int, bool]:
        cnt: Counter = Counter()
        for n in c:
            cnt.update(self.by.get(n, ()))
        if not cnt:
            return 0, False
        k = max(cnt.values())
        ss = k == 4 and any(same_stage_swap(c, d, burst) for d, v in cnt.items() if v == 4)
        return k, ss


def cat_of(k: int, ss: bool) -> str:
    return "V5" if k == 5 else "V4s" if (k == 4 and ss) else "V4x" if k == 4 else "V3"


def phase_cat(ph: str, n_rounds: int) -> str:
    if ph.startswith("탐색"):
        return "탐색 앞" if int(ph.split()[1]) <= n_rounds // 2 else "탐색 뒤"
    return ph


# ---------------------------------------------------------------- ① 방문 · ② 합쳐 묶기

def visit(s: int) -> dict[str, Any]:
    burst = burst_of(s)
    rk = ranker_decks(s)
    recs = {k: recs_of(s, k) for k in run31.SEEDS}
    bk = R30.book_of([r for k in run31.SEEDS for r in recs[k]])
    A = jload(run36.sdir(s) / "maps.json")["nocore|A"]
    idx = Index(bk)
    first: dict[frozenset, tuple[int, str, int]] = {}
    for k in run31.SEEDS:
        nr = max((int(r["phase"].split()[1]) for r in recs[k] if r["phase"].startswith("탐색")), default=1)
        for i, r in enumerate(recs[k]):
            c = frozenset(r["squad"])
            if c in rk and r.get("total_damage") is not None and (c not in first or i < first[c][0]):
                first[c] = (i, phase_cat(r["phase"], nr), k)
    rows = []
    for c, x in rk.items():
        k, ss = idx.best_overlap(c, burst)
        row = dict(x, cat=cat_of(k, ss), overlap=k)
        if c in bk:
            row.update(ours=bk[c][0], gap=x["value"] - bk[c][0], first_eval=first[c][0], first_phase=first[c][1], first_seed=first[c][2])
        rows.append(row)
    w = sum(r["count"] for r in rows)
    share = {cat: sum(r["count"] for r in rows if r["cat"] == cat) / w for cat in CATS}
    # ② 합쳐 묶기: 우리 기록 ∪ 랭커 덱(값이 더 높을 때만 바꿔 넣음)
    add = {c: (x["value"], tuple(x["order"])) for c, x in rk.items() if c not in bk or x["value"] > bk[c][0]}
    catc = {c: r["cat"] for c, r in zip(rk, rows)}
    base = R9.pack_vals(bk)
    merged = R9.pack_vals({**bk, **add})
    marg, only = {}, {}
    for cat in CATS:
        part = {c: v for c, v in add.items() if catc[c] != cat}
        marg[cat] = (merged[0] - R9.pack_vals({**bk, **part})[0]) / base[0]
        solo = {c: v for c, v in add.items() if catc[c] == cat}
        only[cat] = (R9.pack_vals({**bk, **solo})[0] / base[0] - 1) if solo else 0.0
    plan_m = [list(q) for _, q in merged[1]]
    plan_a = [list(q) for _, q in base[1]]
    top = [list(q) for q in run31.season(s)["rankers"]["top_five"]["squads"]]
    chosen = [{"squad": list(q), "value": v, "from": ("ranker:" + catc[frozenset(q)]) if frozenset(q) in add and add[frozenset(q)][1] == tuple(q) else "ours"}
              for v, q in merged[1]]
    return {"season": s, "A_best": A["best"], "pack_ours": base[0], "rows": rows, "share": share,
            "visited_share": share["V5"], "merged": merged[0], "G": merged[0] / base[0] - 1, "marg": marg, "only": only,
            "chosen": chosen, "J_merged_A": SIM.pair_jaccard(plan_m, plan_a), "J_merged_top": SIM.pair_jaccard(plan_m, top),
            "moves_merged_A": SIM.moves(plan_m, plan_a)}


# ---------------------------------------------------------------- ④ 사전 값 편향

def bias(s: int) -> dict[str, Any]:
    d = run36.sdir(s)
    pool: dict[frozenset, dict[str, Any]] = {}
    for x in jload(d / "post.json")["decks"]:
        pool.setdefault(frozenset(x["squad"]), {"squad": x["squad"], "pre": x["pre"], "final": x["final"], "src": "ours"})
    for name, st_ in jload(d / "rpost.json")["sets"].items():
        for x in st_["decks"]:
            pool.setdefault(frozenset(x["squad"]), {"squad": x["squad"], "pre": x["pre"], "final": x["final"], "src": "ranker"})
    by_pre = R9.pack_vals({c: (x["pre"], tuple(x["squad"])) for c, x in pool.items()})
    by_fin = R9.pack_vals({c: (x["final"], tuple(x["squad"])) for c, x in pool.items()})
    fin_of_pre = sum(pool[frozenset(q)]["final"] for _, q in by_pre[1])
    gain = {src: med([x["final"] / x["pre"] for x in pool.values() if x["src"] == src]) for src in ("ours", "ranker")}
    xs = list(pool.values())
    return {"season": s, "decks": len(pool), "loss": 1 - fin_of_pre / by_fin[0], "final_by_pre": fin_of_pre, "final_best": by_fin[0],
            "pre_pick_src": Counter(pool[frozenset(q)]["src"] for _, q in by_pre[1]),
            "post_pick_src": Counter(pool[frozenset(q)]["src"] for _, q in by_fin[1]),
            "gain_ours": gain["ours"], "gain_ranker": gain["ranker"], "spearman": spearman([x["pre"] for x in xs], [x["final"] for x in xs])}


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for k, i in enumerate(o):
            r[i] = float(k)
        return r
    ra, rb = rank(a), rank(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else 0.0


# ---------------------------------------------------------------- ③ 후보 생성 · 대리 모델 재생

def replay(s: int, seed: int) -> dict[str, Any]:
    t0 = time.time()
    acct = run31.account(s, seed)
    owned, names = acct.owned, acct.names
    burst = {n: v["burst"] for n, v in owned.items()}
    rk = ranker_decks(s)
    recs = recs_of(s, seed)
    other = R30.book_of(recs_of(s, 1 - seed))   # 다른 시드가 계산한 구성 — 이 시드의 모델에는 표본 밖이고 이 모델이 고른 것이 아니다
    book: dict[frozenset, tuple[float, tuple]] = {}
    track = {c: {"members": x["members"], "count": x["count"], "value": x["value"], "visited_at": None,
                 "cand_n": 0, "cand_p": 0, "cand_first": None, "fits": []} for c, x in rk.items()}
    order_at = next((i for i in range(len(recs)) if recs[i]["phase"] == "순서"), len(recs))
    bounds = {i for i in range(1, order_at) if recs[i]["phase"] != recs[i - 1]["phase"]}
    fit_at = {t for t in FIT_AT if t < order_at}
    best5: list[frozenset] = []
    n_bound, ref_rows, i = 0, [], 0

    def add(j: int) -> None:
        r = recs[j]
        if r.get("total_damage") is None:
            return
        sq, v = tuple(r["squad"]), r["total_damage"] / E8
        c = frozenset(sq)
        if c not in book or v > book[c][0]:
            book[c] = (v, sq)
        if c in track and track[c]["visited_at"] is None:
            track[c]["visited_at"] = j

    for ev in sorted(bounds | fit_at):
        while i < ev:
            add(i)
            i += 1
        is_bound, is_fit = ev in bounds, ev in fit_at
        parents = [frozenset(q) for _, q in sorted(book.values(), reverse=True)[:R9.PARENTS]]
        if is_bound:
            n_bound += 1
        if is_fit or not best5 or (is_bound and n_bound % PACK_EVERY == 0):
            best5 = [frozenset(q) for _, q in R9.pack_vals(book)[1]]
        open_ = [c for c in track if c not in book]
        cand = {}
        for c in open_:
            nb = [p for p in parents if same_stage_swap(c, p, burst)]
            pk = [d for d in best5 if same_stage_swap(c, d, burst)]
            if is_bound and (nb or pk):
                t = track[c]
                t["cand_n"] += bool(nb)
                t["cand_p"] += bool(pk)
                if t["cand_first"] is None:
                    t["cand_first"] = {"at": ev, "route": "n" if nb else "p"}
            cand[c] = (nb, pk)
        if not is_fit:
            continue
        score = R10.DualFit(SimpleNamespace(best=book), names)
        ref, seen_new = [], set()
        for r in recs[ev:order_at]:
            c = frozenset(r["squad"])
            if c in book or c in seen_new or r.get("total_damage") is None:
                continue
            seen_new.add(c)
            ref.append(score(c) / (r["total_damage"] / E8))
            if len(seen_new) >= REF_N:
                break
        preds = sorted((score(c) for c in book), reverse=True)
        p40 = preds[min(R9.PARENTS, len(preds)) - 1]
        a40 = sorted((v for v, _ in book.values()), reverse=True)[min(R9.PARENTS, len(book)) - 1]
        hi = sorted(((v, c) for c, (v, _) in other.items() if c not in book), key=lambda t: -t[0])[:OTHER_TOP]
        ref_hi = [score(c) / v for v, c in hi]
        q = sorted(ref)
        ref_rows.append({"at": ev, "comps": len(book), "ref_n": len(ref), "ref_ratio_med": med(ref),
                         "ref_ratio_q": [q[len(q) // 4], q[3 * len(q) // 4]] if q else None, "pred_40th": p40, "actual_40th": a40,
                         "other_hi_n": len(hi), "other_hi_ratio_med": med(ref_hi),
                         "other_hi_value_range": [hi[-1][0], hi[0][0]] if hi else None,
                         "other_hi_beat40": (sum(score(c) >= p40 for _, c in hi) / len(hi)) if hi else None})
        ranks = route_ranks(cand, book, owned, score, best5)
        for c in open_:
            p = score(c)
            track[c]["fits"].append({"at": ev, "pred": p, "ratio": p / rk[c]["value"], "beat_40th": p >= p40,
                                     "actual_top40": rk[c]["value"] >= a40, **ranks.get(c, {})})
    while i < len(recs):
        add(i)
        i += 1
    return {"season": s, "seed": seed, "evals": len(recs), "order_at": order_at, "bounds": n_bound, "fits": ref_rows,
            "decks": list(track.values()), "seconds": round(time.time() - t0, 1)}


def route_ranks(cand: Mapping[frozenset, tuple[list, list]], book, owned, score, best5: Sequence[frozenset]) -> dict[frozenset, dict]:
    """후보로 떠오른 랭커 덱의 경로별 순위 — ⓑ 이웃(부모 안 · 전체), ⓐ 덱 고치기(새 구성 누적 순번)."""
    out: dict[frozenset, dict] = {}
    want = {c for c, (nb, pk) in cand.items() if nb or pk}
    if not want:
        return out
    # ⓑ 이웃: 실험 9 local_round와 같은 방식 — 부모마다 아직 안 본 이웃 예측 상위 8, 모아서 예측 순
    parents = sorted(book.values(), reverse=True)[:R9.PARENTS]
    pool_c: list[tuple[float, frozenset]] = []
    in_parent: dict[frozenset, int] = {}
    for _, sq in parents:
        lst = sorted(((score(frozenset(nb)), frozenset(nb)) for nb in S4.neighbors(sq, owned) if frozenset(nb) not in book),
                     key=lambda t: -t[0])
        for j, (v, c) in enumerate(lst):
            if c in want:
                in_parent[c] = min(in_parent.get(c, 10 ** 6), j)
        pool_c += lst[:R9.PER_PARENT]
    pool_c.sort(key=lambda t: -t[0])
    g_rank = {}
    for j, (_, c) in enumerate(pool_c):
        if c in want and c not in g_rank:
            g_rank[c] = j
    # ⓐ 덱 고치기: 예상 이득 순으로 새 구성을 센다
    decks = [tuple(book[c][1]) for c in best5 if c in book]
    p_rank, taken = {}, set()
    for _, new in S4.pack_moves(decks, owned, score):
        for nd in new:
            c = frozenset(nd)
            if c in book or c in taken:
                continue
            taken.add(c)
            if c in want and c not in p_rank:
                p_rank[c] = len(taken) - 1
        if len(taken) > 2000:
            break
    for c in want:
        out[c] = {"nb_parent_rank": in_parent.get(c), "nb_global_rank": g_rank.get(c),
                  "nb_pick": c in g_rank and g_rank[c] < NB_SHARE, "pk_rank": p_rank.get(c),
                  "pk_pick": c in p_rank and p_rank[c] < PACK_SHARE}
    return out


# ---------------------------------------------------------------- 모으기

def deck_status(d: Mapping[str, Any]) -> str:
    """한 시드에서 끝까지 계산 안 한 랭커 덱: pick = 어느 모델 시점에 경로 순위 안(고를 만했음) · cand = 그 시점 후보였지만 순위 밖 ·
    bound = 모델 시점이 아닌 라운드 경계에서만 후보 · never = 후보로 떠오른 적 없음."""
    fs = d["fits"]
    if any(f.get("nb_pick") or f.get("pk_pick") for f in fs):
        return "pick"
    if any(f.get("nb_global_rank") is not None or f.get("pk_rank") is not None or f.get("nb_parent_rank") is not None for f in fs):
        return "cand"
    return "bound" if d["cand_first"] else "never"


STATUS = ("pick", "cand", "bound", "never")


def agg_replay(s: int, rows_visit: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    reps = [jload(RLOG / f"S{s}_s{k}.json") for k in run31.SEEDS]
    if not all(reps):
        return None
    cat = {frozenset(r["members"]): r["cat"] for r in rows_visit}
    w_status: Counter = Counter()
    ratios, beat, tot = [], [], 0
    for rp in reps:
        for d in rp["decks"]:
            c = frozenset(d["members"])
            if cat[c] == "V5" or d["count"] == 0:
                continue
            tot += d["count"]
            w_status[deck_status(d)] += d["count"]
            for f in d["fits"]:
                ratios.append((f["ratio"], d["count"], f["at"]))
                beat.append((1.0 if f["beat_40th"] else 0.0, d["count"]))
    refs = [f["ref_ratio_med"] for rp in reps for f in rp["fits"] if f["ref_ratio_med"] is not None]
    his = [f["other_hi_ratio_med"] for rp in reps for f in rp["fits"] if f.get("other_hi_ratio_med") is not None]
    hib = [f["other_hi_beat40"] for rp in reps for f in rp["fits"] if f.get("other_hi_beat40") is not None]
    top40 = [(1.0 if f["actual_top40"] else 0.0, d["count"]) for rp in reps for d in rp["decks"]
             if cat[frozenset(d["members"])] != "V5" for f in d["fits"]]
    return {"open_weight": tot // len(reps), "status": {k: (w_status[k] / tot if tot else None) for k in STATUS},
            "ratio_ranker": wmed([(r, w) for r, w, _ in ratios]), "ratio_ref": med(refs),
            "ratio_by_fit": {t: wmed([(r, w) for r, w, a in ratios if a == t]) for t in FIT_AT},
            "ref_by_fit": {t: med([f["ref_ratio_med"] for rp in reps for f in rp["fits"] if f["at"] == t]) for t in FIT_AT},
            "beat40": (sum(b * w for b, w in beat) / sum(w for _, w in beat)) if beat else None,
            "ratio_other_hi": med(his), "other_hi_beat40": med(hib),
            "actual_top40": (sum(b * w for b, w in top40) / sum(w for _, w in top40)) if top40 else None,
            "seconds": [rp["seconds"] for rp in reps]}


def analyze() -> dict[str, Any]:
    rows = []
    for s in SEASONS:
        t0 = time.time()
        vf = VLOG / f"S{s}.json"
        if not vf.exists():
            jdump(vf, {"visit": visit(s), "bias": bias(s)})
        vb = jload(vf)
        v, b = vb["visit"], vb["bias"]
        r = agg_replay(s, v["rows"])
        rows.append({"season": s, "visit": v, "bias": b, "replay": r})
        print(f"S{s}: G {v['G']:+.2%} visited {v['visited_share']:.0%} bias loss {b['loss']:.2%} ({time.time() - t0:.0f}s)", flush=True)
    out = {"procedure": "README §1단계", "seasons": rows}
    jdump(HERE / "analysis.json", out)
    (HERE / "results.md").write_text(write_md(rows), encoding="utf-8")
    return out


def pct(x: float | None, d: int = 1) -> str:
    return "—" if x is None else f"{100 * x:.{d}f}%"


def sp(x: float | None, d: int = 1) -> str:
    return "—" if x is None else f"{100 * x:+.{d}f}%"


def write_md(rows: Sequence[Mapping[str, Any]]) -> str:
    L = ["# 실험 38 1단계 결과 표", "", "`an38.py analyze`가 만든다. 코어 없음, 사전 값(레이어 1시뮬 · 장비 옵션 8줄 Lv10), 시뮬 0.", "",
         "## ① 방문 · ② 합쳐 묶기", "",
         "방문 범주(사용 수 가중): V5 = 같은 구성을 계산함, V4s = 같은 단계 한 명 차이까지, V4x = 4명 겹침(다른 단계), V3 = 3명 이하. "
         "G = 우리 기록 ∪ 랭커 덱으로 다시 묶은 값 ÷ 우리 최선 − 1. 그 범주만 = 우리 기록에 그 범주 랭커 덱만 넣고 묶은 값 ÷ 우리 최선 − 1, 한계 = 그 범주를 빼고 묶으면 줄어드는 몫(우리 최선 대비).", "",
         "| 시즌 | V5 | V4s | V4x | V3 | G | 그 범주만 V5 | V4s | V4x | V3 | 한계 V5 | V4s | V4x | V3 | 합친 5덱의 랭커 덱 | J(합친 · 우리) | J(합친 · 랭커 대표) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in rows:
        v = x["visit"]
        sh, mg = v["share"], v["marg"]
        nr = sum(c["from"] != "ours" for c in v["chosen"])
        on = v["only"]
        L.append(f"| S{x['season']} | {pct(sh['V5'], 0)} | {pct(sh['V4s'], 0)} | {pct(sh['V4x'], 0)} | {pct(sh['V3'], 0)} | {sp(v['G'])} | "
                 f"{sp(on['V5'])} | {sp(on['V4s'])} | {sp(on['V4x'])} | {sp(on['V3'])} | "
                 f"{sp(mg['V5'])} | {sp(mg['V4s'])} | {sp(mg['V4x'])} | {sp(mg['V3'])} | {nr}/5 | {v['J_merged_A']:.2f} | {v['J_merged_top']:.2f} |")
    L += ["", "## ③ 후보 생성 · 대리 모델 (시드마다 재생, 끝까지 계산 안 한 랭커 덱 — 사용 수 가중, 두 시드 합)", "",
          "상태: 고를 만함 = 어느 모델 시점(1,000 · 3,000 · 6,000 · 9,000평가)에 덱 고치기 70 · 이웃 30 순위 안, 순위 밖 = 그 시점 후보였지만 밖, "
          "경계만 = 모델 시점이 아닌 라운드 경계에서만 후보(같은 단계 한 명 교체로 닿음), 없음 = 후보로 떠오른 적 없음. "
          "예측÷실제 = 그 시점 모델(가중 중앙), 비교 = 시점 바로 뒤 처음 평가한 구성 500개(탐색이 고른 것)의 예측÷실제 중앙. "
          "비교(다른 시드 상위 300) = 다른 시드가 계산했고 이 시드는 아직 안 본 값 상위 300 구성(이 모델이 고르지 않은 고득점 구성)의 예측÷실제 중앙. "
          "상위 40 예측 = 예측이 기록 상위 40번째 예측 이상인 비율, 실제 값이 상위 40 = 랭커 덱 실제 값이 그 시점 기록 상위 40번째 값 이상인 비율.", "",
          "| 시즌 | 미방문 사용 수 | 고를 만함 | 순위 밖 | 경계만 | 없음 | 예측÷실제 랭커 | 비교(탐색이 고른 것) | 비교(다른 시드 상위 300) | 1,000 | 3,000 | 6,000 | 9,000 | 상위 40 예측 랭커 | 상위 40 예측 다른 시드 | 실제 값이 상위 40 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in rows:
        r = x["replay"]
        if not r:
            L.append(f"| S{x['season']} | (재생 없음) | | | | | | | | | | | |")
            continue
        bf, stt = r["ratio_by_fit"], r["status"]
        L.append(f"| S{x['season']} | {r['open_weight']} | {pct(stt['pick'], 0)} | {pct(stt['cand'], 0)} | {pct(stt['bound'], 0)} | {pct(stt['never'], 0)} | "
                 f"{pct(r['ratio_ranker'], 0)} | {pct(r['ratio_ref'], 0)} | {pct(r['ratio_other_hi'], 0)} | {pct(bf.get(1000), 0)} | {pct(bf.get(3000), 0)} | "
                 f"{pct(bf.get(6000), 0)} | {pct(bf.get(9000), 0)} | {pct(r['beat40'], 0)} | {pct(r['other_hi_beat40'], 0)} | {pct(r['actual_top40'], 0)} |")
    L += ["", "## ④ 사전 값 편향 (실험 36 후처리한 덱 안)", "",
          "손해 = 1 − (사전 값으로 묶은 5덱의 후처리 합 ÷ 후처리 값으로 묶은 5덱의 후처리 합). 이득 = 후처리 ÷ 사전(중앙).", "",
          "| 시즌 | 덱 수 | 손해 | 사전으로 고른 5덱(우리/랭커) | 후처리로 고른 5덱(우리/랭커) | 이득 우리 | 이득 랭커 | 순위 상관 |",
          "|---|---|---|---|---|---|---|---|"]
    for x in rows:
        b = x["bias"]
        L.append(f"| S{x['season']} | {b['decks']} | {pct(b['loss'], 2)} | {b['pre_pick_src'].get('ours', 0)}/{b['pre_pick_src'].get('ranker', 0)} | "
                 f"{b['post_pick_src'].get('ours', 0)}/{b['post_pick_src'].get('ranker', 0)} | {sp(b['gain_ours'] - 1)} | {sp(b['gain_ranker'] - 1)} | {b['spearman']:.2f} |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("replay")
    r.add_argument("--season", type=int, required=True)
    r.add_argument("--seed", type=int, required=True)
    v = sub.add_parser("visit")
    v.add_argument("--season", type=int, required=True)
    sub.add_parser("analyze")
    a = ap.parse_args(argv)
    if a.cmd == "visit":
        jdump(VLOG / f"S{a.season}.json", {"visit": visit(a.season), "bias": bias(a.season)})
        print(f"S{a.season} visit done")
    elif a.cmd == "replay":
        out = replay(a.season, a.seed)
        jdump(RLOG / f"S{a.season}_s{a.seed}.json", out)
        print(f"S{a.season} s{a.seed}: {out['seconds']}s")
    else:
        analyze()
    return 0


if __name__ == "__main__":
    sys.exit(main())
