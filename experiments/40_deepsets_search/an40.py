"""실험 40 — 1단계(시뮬 0): Deep Sets 대리 모델이 탐색 안의 자료 크기에서도 릿지보다 나은가. README §1단계.

실험 38 재생(실험 36 S33~S42 기록 순서 그대로)의 모델 시점(1,000 · 3,000 · 6,000 · 9,000평가)마다
그때까지의 기록으로 R0(지금 릿지 `DualFit`) · D1(Deep Sets, 세션 기록만) · D2(실험 33 자료로 미리 학습 → 세션 기록으로 이어 학습)를
맞추고, 다음에 계산한 구성 · 아직 안 본 랭커 덱 · 다른 시드 고득점 구성을 얼마나 맞히는지 잰다.

    python -I experiments/40_deepsets_search/an40.py pretrain                       # D2 미리 학습 → run_log/pre_ds.pt
    python -I experiments/40_deepsets_search/an40.py replay --season 36 --seed 0    # → replay/S36_s0.json
    python -I experiments/40_deepsets_search/an40.py replay --all                   # 안 끝난 것만(RUN40_BUDGET_MIN 분 넘으면 멈춤)
    python -I experiments/40_deepsets_search/an40.py analyze                        # → analysis.json · results.md

평가기 기록은 실험 36(nikke-calc-rs 8bc51a2)과 실험 33(같은 평가기)만 읽는다. 새 시뮬 없음.
"""

from __future__ import annotations

import argparse
import copy
import math
import os
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
RLOG = HERE / "replay"
LOG = HERE / "run_log"
PRE = LOG / "pre_ds.pt"


def _load(name: str, path: Path):
    import importlib.util
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A38 = _load("an38", EXP / "38_ranker_miss" / "an38.py")
Q = _load("q2_33", EXP / "33_role_vectors" / "q2_33.py")
M = Q.M                                   # roles33 — Obs · spearman · top_metrics
G = _load("models34", EXP / "34_surrogate_compare" / "models34.py")

R9, R10, run31 = A38.R9, A38.R10, A38.run31
SEASONS = A38.SEASONS                     # 33 … 42 (실험 38 개발 시즌)
SEEDS = run31.SEEDS
FIT_AT = A38.FIT_AT                       # (1000, 3000, 6000, 9000)
REF_N, OTHER_TOP, E8 = A38.REF_N, A38.OTHER_TOP, A38.E8
MODELS = ("R0", "D1", "D2", "D2_0")       # D2_0 = 미리 학습만(이어 학습 없음, 관찰)

# 사전 등록(README) — 실험 34 G3 고른 설정 그대로, 학습 길이만 세션 기록의 10% 떼어 둔 조기 종료
DS_CFG = dict(d=32, hidden=128, weight_decay=0.0, lr=1e-3, batch=512)
PRE_EPOCHS = 58                           # 실험 34가 고른 G3 에포크(12만 관측)
MAX_EPOCHS, PATIENCE, VALID_FRAC = 400, 15, 0.10
FT_LR = 3e-4                              # D2 이어 학습 학습률

# 판단(README §사전 등록)
GAP_WIN = -0.05                           # 간극(다른 시드 고득점 비 − 랭커 덱 비) 시즌 중앙 차이
RHO_FLAT = -0.02                          # 다음 500 순위 상관 시즌 중앙 차이 하한
RHO_WIN = 0.05
TIE = 0.01


def elem_of(s: int) -> str:
    return run31.season(s)["code"]        # 보스 속성(작열 · 수냉 …) — 실험 33 Obs.element와 같은 뜻


def obs_of(comps: Sequence[frozenset], vals: Sequence[float] | None, el: str) -> list:
    """구성 → Obs(총딜은 원 단위). 값을 모르면 1로 둔다(예측용)."""
    vs = vals if vals is not None else [1.0] * len(comps)
    return [M.Obs(frozenset(c), el, tuple(sorted(c)), float(v), ()) for c, v in zip(comps, vs)]


# ---------------------------------------------------------------- Deep Sets 미리 학습 · 이어 학습

def ds_cfg(**kw) -> Any:
    return G.DSConfig(**{**DS_CFG, **kw})


def pretrain() -> Path:
    import torch
    t0 = time.time()
    p_obs, pr_obs, _ = Q.load_obs()
    names, at = list(Q.R.roster()), Q.R.attrs()
    m = G.DeepSets(names, Q.R.ELEMENTS, at, ds_cfg(epochs=PRE_EPOCHS)).fit(p_obs + pr_obs)
    LOG.mkdir(parents=True, exist_ok=True)
    torch.save({"names": names, "elements": list(Q.R.ELEMENTS), "mu": m.mu, "sd": m.sd,
                "states": [n.state_dict() for n in m.nets], "n_obs": len(p_obs) + len(pr_obs),
                "seconds": round(time.time() - t0, 1)}, PRE)
    print({"pretrain": len(p_obs) + len(pr_obs), "seconds": round(time.time() - t0, 1)}, flush=True)
    return PRE


def load_pre() -> Any:
    import torch
    blob = torch.load(PRE, weights_only=False)
    m = G.DeepSets(blob["names"], blob["elements"], Q.R.attrs(), ds_cfg(epochs=PRE_EPOCHS))
    m.mu, m.sd = blob["mu"], blob["sd"]
    m.nets = []
    for st_ in blob["states"]:
        net = m._net()
        net.load_state_dict(st_)
        net.eval()
        m.nets.append(net)
    return m


def finetune(pre: Any, train: list, valid: list) -> Any:
    """미리 학습한 그물을 세션 기록으로 이어 학습한다. 정규화(mu · sd)는 미리 학습 것을 그대로 쓴다."""
    import torch
    torch.set_num_threads(4)
    m = copy.deepcopy(pre)
    c = m.cfg
    A = [torch.from_numpy(a) for a in G._ds_arrays(train, m.names, m.elements, m.at)]
    Y = torch.from_numpy(((G.log_total(train) - m.mu) / m.sd).astype(np.float32))
    Av = [torch.from_numpy(a) for a in G._ds_arrays(valid, m.names, m.elements, m.at)]
    Yv = torch.from_numpy(((G.log_total(valid) - m.mu) / m.sd).astype(np.float32))
    eps = []
    for net, seed in zip(m.nets, c.seeds):
        g = torch.Generator().manual_seed(seed)
        opt = torch.optim.Adam(net.parameters(), lr=FT_LR, weight_decay=c.weight_decay)
        net.eval()
        with torch.no_grad():
            best = float(((net(*Av) - Yv) ** 2).mean())
        best_ep, best_state, bad = 0, {k: v.clone() for k, v in net.state_dict().items()}, 0
        for ep in range(1, MAX_EPOCHS + 1):
            net.train()
            perm = torch.randperm(len(Y), generator=g)
            for i in range(0, len(Y), c.batch):
                b = perm[i:i + c.batch]
                opt.zero_grad()
                ((net(A[0][b], A[1][b], A[2][b]) - Y[b]) ** 2).mean().backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                vl = float(((net(*Av) - Yv) ** 2).mean())
            if vl < best - 1e-6:
                best, best_ep, bad = vl, ep, 0
                best_state = {k: v.clone() for k, v in net.state_dict().items()}
            else:
                bad += 1
                if bad >= PATIENCE:
                    break
        net.load_state_dict(best_state)
        net.eval()
        eps.append(best_ep)
    m.best_epoch = int(round(sum(eps) / len(eps)))
    return m


def predict_each(m: Any, obs: list) -> np.ndarray:
    """그물마다 log 총딜 예측 [그물, 관측]."""
    import torch
    A = [torch.from_numpy(a) for a in G._ds_arrays(obs, m.names, m.elements, m.at)]
    with torch.no_grad():
        return np.stack([net(*A).numpy() * m.sd + m.mu for net in m.nets])


class DSScore:
    """Deep Sets → 구성의 예측 총딜(억 단위, 릿지 `DualFit`과 같은 단위). 그물 사이 log 예측 표준편차(퍼짐)도 준다."""

    def __init__(self, m: Any, el: str):
        self.m, self.el = m, el

    def many(self, comps: Sequence[frozenset]) -> tuple[np.ndarray, np.ndarray]:
        if not comps:
            return np.zeros(0), np.zeros(0)
        z = predict_each(self.m, obs_of(comps, None, self.el))
        return np.exp(z.mean(0)) / E8, z.std(0)


class RidgeScore:
    def __init__(self, book: Mapping, names: Sequence[str]):
        self.f = R10.DualFit(SimpleNamespace(best=book), names)

    def many(self, comps: Sequence[frozenset]) -> tuple[np.ndarray, None]:
        return np.array([self.f(c) for c in comps]), None


# ---------------------------------------------------------------- 재생

def fit_models(book: Mapping[frozenset, tuple], names: Sequence[str], el: str, tag: str, pre: Any) -> tuple[dict, dict]:
    comps = list(book)
    rng = random.Random(f"exp40-valid-{tag}")
    va = set(rng.sample(range(len(comps)), max(1, int(round(VALID_FRAC * len(comps))))))
    tr_c = [c for i, c in enumerate(comps) if i not in va]
    va_c = [c for i, c in enumerate(comps) if i in va]
    tr = obs_of(tr_c, [book[c][0] * E8 for c in tr_c], el)
    vd = obs_of(va_c, [book[c][0] * E8 for c in va_c], el)
    out, info = {}, {}
    t = time.time()
    out["R0"] = RidgeScore(book, names)
    info["R0"] = {"seconds": round(time.time() - t, 2)}
    t = time.time()
    d1 = G.DeepSets(list(names), Q.R.ELEMENTS, Q.R.attrs(), ds_cfg(max_epochs=MAX_EPOCHS, patience=PATIENCE)).fit(tr, valid=vd)
    out["D1"] = DSScore(d1, el)
    info["D1"] = {"seconds": round(time.time() - t, 2), "best_epoch": d1.best_epoch}
    t = time.time()
    d2 = finetune(pre, tr, vd)
    out["D2"] = DSScore(d2, el)
    info["D2"] = {"seconds": round(time.time() - t, 2), "best_epoch": d2.best_epoch}
    out["D2_0"] = DSScore(pre, el)
    info["D2_0"] = {"seconds": 0.0}
    return out, info


def replay(s: int, seed: int, pre: Any) -> dict[str, Any]:
    t0 = time.time()
    acct = run31.account(s, seed)
    names, el = acct.names, elem_of(s)
    rk = A38.ranker_decks(s)
    recs = A38.recs_of(s, seed)
    other = A38.R30.book_of(A38.recs_of(s, 1 - seed))
    order_at = next((i for i in range(len(recs)) if recs[i]["phase"] == "순서"), len(recs))
    book: dict[frozenset, tuple[float, tuple]] = {}
    i, fits, decks = 0, [], {c: {"members": x["members"], "count": x["count"], "value": x["value"], "fits": []} for c, x in rk.items()}

    def add(j: int) -> None:
        r = recs[j]
        if r.get("total_damage") is None:
            return
        sq, v = tuple(r["squad"]), r["total_damage"] / E8
        c = frozenset(sq)
        if c not in book or v > book[c][0]:
            book[c] = (v, sq)

    for ev in sorted(t for t in FIT_AT if t < order_at):
        while i < ev:
            add(i)
            i += 1
        # 비교 대상: 다음에 처음 계산한 구성 500개 · 다른 시드가 계산한 이 시드 미방문 고득점 300개 · 아직 안 본 랭커 덱
        nxt, seen_new = [], set()
        for r in recs[ev:order_at]:
            c = frozenset(r["squad"])
            if c in book or c in seen_new or r.get("total_damage") is None:
                continue
            seen_new.add(c)
            nxt.append((c, r["total_damage"] / E8))
            if len(nxt) >= REF_N:
                break
        hi = sorted(((v, c) for c, (v, _) in other.items() if c not in book), key=lambda t: -t[0])[:OTHER_TOP]
        open_ = [c for c in rk if c not in book]
        models, info = fit_models(book, names, el, f"S{s}-s{seed}-{ev}", pre)
        row = {"at": ev, "comps": len(book), "next_n": len(nxt), "hi_n": len(hi), "fit": info, "m": {}}
        bk = list(book)
        a_next = [v for _, v in nxt]
        a_hi = [v for v, _ in hi]
        for key, sc in models.items():
            p_bk, _ = sc.many(bk)
            p40 = float(np.sort(p_bk)[::-1][min(R9.PARENTS, len(p_bk)) - 1])
            p_nx, sd_nx = sc.many([c for c, _ in nxt])
            p_hi, _ = sc.many([c for _, c in hi])
            p_rk, _ = sc.many(open_)
            tm = M.top_metrics(a_next, p_nx)
            r_nx = p_nx / np.array(a_next)
            m = {"next_rho": tm["rho"], "next_rho_top": tm.get("rho_top"), "next_hit": tm["hit_k"],
                 "next_ratio_med": float(np.median(r_nx)),
                 "hi_ratio_med": float(np.median(p_hi / np.array(a_hi))) if hi else None,
                 "hi_rho": M.spearman(a_hi, p_hi) if len(hi) >= 3 else None,
                 "hi_beat40": float(np.mean(p_hi >= p40)) if hi else None, "pred_40th": p40}
            if sd_nx is not None:   # 퍼짐 ↔ 실제 log 잔차 크기(관찰)
                m["spread_resid_rho"] = M.spearman(list(sd_nx), list(np.abs(np.log(r_nx))))
            row["m"][key] = m
            for c, p in zip(open_, p_rk):
                decks[c]["fits"].append({"at": ev, "model": key, "ratio": float(p) / rk[c]["value"], "beat_40th": bool(p >= p40)})
        fits.append(row)
        print({"season": s, "seed": seed, "at": ev, **{k: round(v["next_rho"] or 0, 3) for k, v in row["m"].items()},
               "sec": {k: v["seconds"] for k, v in info.items()}}, flush=True)
    return {"season": s, "seed": seed, "element": el, "evals": len(recs), "order_at": order_at, "fits": fits,
            "decks": [d for d in decks.values() if d["fits"]], "seconds": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- 모으기 · 판단

def visit_cat(s: int) -> dict[frozenset, str]:
    v = A38.jload(A38.VLOG / f"S{s}.json")
    return {frozenset(r["members"]): r["cat"] for r in v["visit"]["rows"]}


def agg_season(s: int) -> dict[str, Any] | None:
    reps = [A38.jload(RLOG / f"S{s}_s{k}.json") for k in SEEDS]
    if not all(reps):
        return None
    cat = visit_cat(s)
    out: dict[str, Any] = {}
    for key in MODELS:
        ratios, beat = [], []
        for rp in reps:
            for d in rp["decks"]:
                if cat[frozenset(d["members"])] == "V5" or d["count"] == 0:
                    continue
                for f in d["fits"]:
                    if f["model"] == key:
                        ratios.append((f["ratio"], d["count"]))
                        beat.append((1.0 if f["beat_40th"] else 0.0, d["count"]))
        cells = [f["m"][key] for rp in reps for f in rp["fits"]]
        rk_r = A38.wmed(ratios)
        hi_r = A38.med([c["hi_ratio_med"] for c in cells])
        out[key] = {"ratio_ranker": rk_r, "ratio_other_hi": hi_r,
                    "gap": (hi_r - rk_r) if (hi_r is not None and rk_r is not None) else None,
                    "beat40": (sum(b * w for b, w in beat) / sum(w for _, w in beat)) if beat else None,
                    "next_rho": A38.med([c["next_rho"] for c in cells]),
                    "next_rho_top": A38.med([c["next_rho_top"] for c in cells]),
                    "next_hit": [sum(c["next_hit"][0] for c in cells), sum(c["next_hit"][1] for c in cells)],
                    "next_ratio": A38.med([c["next_ratio_med"] for c in cells]),
                    "hi_rho": A38.med([c["hi_rho"] for c in cells]),
                    "hi_beat40": A38.med([c["hi_beat40"] for c in cells]),
                    "spread_resid_rho": A38.med([c.get("spread_resid_rho") for c in cells]),
                    "fit_seconds": A38.med([f["fit"][key]["seconds"] for rp in reps for f in rp["fits"]])}
        out[key]["by_fit"] = {t: A38.med([f["m"][key]["next_rho"] for rp in reps for f in rp["fits"] if f["at"] == t]) for t in FIT_AT}
    out["comps_at"] = {t: A38.med([f["comps"] for rp in reps for f in rp["fits"] if f["at"] == t]) for t in FIT_AT}
    return out


def verdict(rows: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("D1", "D2"):
        dg = [r[key]["gap"] - r["R0"]["gap"] for r in rows.values() if r[key]["gap"] is not None and r["R0"]["gap"] is not None]
        dr = [r[key]["next_rho"] - r["R0"]["next_rho"] for r in rows.values()]
        g, rho = A38.med(dg), A38.med(dr)
        if g is not None and g <= GAP_WIN and rho >= RHO_FLAT:
            line, text = 1, "2단계(시뮬) 후보 — 실험 39 틀에 판으로 끼워 S23~S32에서 base와 비교"
        elif rho >= RHO_WIN:
            line, text = 2, "일반 예측만 나음(랭커 덱 간극 그대로) — 시뮬로 갈지 사용자 판단"
        elif g is not None and g <= GAP_WIN:
            line, text = 3, "랭커 덱 간극만 줄임(일반 예측은 나빠짐) — 사용자 판단"
        else:
            line, text = 4, "중단 — 탐색 안 자료 크기에서는 릿지와 같거나 못함"
        out[key] = {"line": line, "text": text, "d_gap_med": g, "d_rho_med": rho,
                    "seasons_gap_better": sum(x < 0 for x in dg), "seasons_rho_better": sum(x > 0 for x in dr), "n": len(dr)}
    ones = [k for k in ("D1", "D2") if out[k]["line"] == 1]
    if len(ones) == 2:
        a, b = out["D1"]["d_gap_med"], out["D2"]["d_gap_med"]
        pick = "D2" if b < a - TIE else "D1"
    else:
        pick = ones[0] if ones else None
    out["stage2"] = pick
    return out


def analyze() -> dict[str, Any]:
    rows = {s: r for s in SEASONS if (r := agg_season(s)) is not None}
    if len(rows) < len(SEASONS):
        print(f"재생 {len(rows)}/{len(SEASONS)}시즌 — 판단은 10시즌이 다 있을 때만", flush=True)
    ref38 = {r["season"]: r["replay"] for r in A38.jload(A38.HERE / "analysis.json")["seasons"]}
    repro = {s: {"ranker": (rows[s]["R0"]["ratio_ranker"], ref38[s]["ratio_ranker"]),
                 "other_hi": (rows[s]["R0"]["ratio_other_hi"], ref38[s]["ratio_other_hi"])} for s in rows}
    out = {"procedure": "README §1단계", "seasons": rows, "repro38": repro,
           "verdict": verdict(rows) if len(rows) == len(SEASONS) else None}
    A38.jdump(HERE / "analysis.json", out)
    (HERE / "results.md").write_text(write_md(out), encoding="utf-8")
    return out


def pct(x, d=1):
    return "—" if x is None else f"{100 * x:.{d}f}%"


def f3(x):
    return "—" if x is None else f"{x:.3f}"


LABEL = {"R0": "R0 릿지(지금)", "D1": "D1 Deep Sets(세션 기록만)", "D2": "D2 미리 학습 + 이어 학습", "D2_0": "D2_0 미리 학습만(관찰)"}


def write_md(out: Mapping[str, Any]) -> str:
    rows, v = out["seasons"], out["verdict"]
    L = ["# 실험 40 1단계 결과 표", "", "`an40.py analyze`가 만든다. 실험 36 S33~S42 기록 재생, 코어 없음, 사전 값, 시뮬 0.", ""]
    if v:
        L += ["## 판단", "", "| 모델 | 간극 차이(시즌 중앙, 대 R0) | 다음 500 순위 상관 차이 | 간극 준 시즌 | 상관 오른 시즌 | 줄 |", "|---|---:|---:|---:|---:|---|"]
        for k in ("D1", "D2"):
            x = v[k]
            L.append(f"| {LABEL[k]} | {100 * x['d_gap_med']:+.1f}%p | {x['d_rho_med']:+.3f} | {x['seasons_gap_better']}/{x['n']} | "
                     f"{x['seasons_rho_better']}/{x['n']} | {x['line']} — {x['text']} |")
        L += ["", f"2단계 모델: **{v['stage2'] or '없음'}**", ""]
    L += ["## 시즌별", "", "간극 = 다른 시드 고득점 예측÷실제 − 아직 안 본 랭커 덱 예측÷실제(사용 수 가중). 작을수록 랭커 덱을 덜 낮게 본다.", ""]
    for key in MODELS:
        L += [f"### {LABEL[key]}", "", "| 시즌 | 랭커 덱 비 | 고득점 비 | 간극 | 랭커 덱 상위 40 예측 | 다음 500 상관 | 다음 500 상위 10% 안 | 다음 500 상위 10 적중 | 고득점 300 상관 | 퍼짐↔잔차 | 맞추기 초 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for s, r in rows.items():
            x = r[key]
            L.append(f"| S{s} | {pct(x['ratio_ranker'], 0)} | {pct(x['ratio_other_hi'], 0)} | {pct(x['gap'], 0)} | {pct(x['beat40'], 0)} | "
                     f"{f3(x['next_rho'])} | {f3(x['next_rho_top'])} | {x['next_hit'][0]}/{x['next_hit'][1]} | {f3(x['hi_rho'])} | "
                     f"{f3(x['spread_resid_rho'])} | {x['fit_seconds']} |")
        L.append("")
    L += ["## 재현 확인(R0 대 실험 38)", "", "| 시즌 | 랭커 덱 비(이번 · 38) | 고득점 비(이번 · 38) |", "|---|---|---|"]
    for s, x in out["repro38"].items():
        L.append(f"| S{s} | {pct(x['ranker'][0])} · {pct(x['ranker'][1])} | {pct(x['other_hi'][0])} · {pct(x['other_hi'][1])} |")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("pretrain", "replay", "analyze"))
    ap.add_argument("--season", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.cmd == "pretrain":
        pretrain()
        return 0
    if a.cmd == "analyze":
        out = analyze()
        print(out["verdict"])
        return 0
    if not PRE.exists():
        pretrain()
    pre = load_pre()
    jobs = [(s, k) for s in SEASONS for k in SEEDS] if a.all else [(a.season, a.seed)]
    t0, budget = time.time(), os.environ.get("RUN40_BUDGET_MIN")
    for s, k in jobs:
        f = RLOG / f"S{s}_s{k}.json"
        if a.all and f.exists():
            continue
        if budget and time.time() - t0 > float(budget) * 60:
            print({"stop": "budget", "minutes": round((time.time() - t0) / 60, 1)}, flush=True)
            return 3
        A38.jdump(f, replay(s, k, pre))
    return 0


if __name__ == "__main__":
    sys.exit(main())
