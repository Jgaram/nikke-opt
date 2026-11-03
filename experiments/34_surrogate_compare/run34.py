"""실험 34 — 대리 모델 넓게 비교(시뮬 0). README §사전 등록.

    pip install lightgbm scikit-learn scipy torch      # torch는 CPU 판이면 된다
    OPENBLAS_NUM_THREADS=4 python experiments/34_surrogate_compare/run34.py   → results.md · run_log/res34.json

자료 · 나누기 · 지표 · M0 · M2는 실험 33 Q2(`q2_33.py`)의 함수를 그대로 부른다(같은 난수 · 같은 설정 고르기).
단계마다 run_log/partial34.json에 저장하고, 다시 돌리면 끝난 단계는 건너뛴다.
"""

from __future__ import annotations

import gc
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np

HERE = Path(__file__).resolve().parent
EXP33 = HERE.parent / "33_role_vectors"
LOG = HERE / "run_log"


def _load(name, path):
    import importlib.util
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


Q = _load("q2_33", EXP33 / "q2_33.py")
M = Q.M                                   # roles33
G = _load("models34", HERE / "models34.py")

# ---------------------------------------------------------------- 사전 등록한 값(README §사전 등록)
GRID_GBM = [dict(num_leaves=nl, min_data_in_leaf=md) for nl in (31, 255) for md in (20, 100)]
GRID_RF = [dict(max_features=mf, min_samples_leaf=ml) for mf in (0.33, "sqrt") for ml in (1, 5)]
GRID_DS = [dict(d=d, weight_decay=wd) for d in (16, 32) for wd in (0.0, 1e-5)]
GRID_GP = [dict(w_attr=w, noise=nz) for w in (0.0, 0.2, 0.5) for nz in (0.01, 0.1)]
NEW = ("G1", "G2", "G3", "G4")
LABEL = {"M0": "M0 릿지(기준선)", "M2": "M2 역할 벡터", "G1": "G1 LightGBM", "G2": "G2 랜덤 포레스트",
         "G3": "G3 Deep Sets", "G4": "G4 자카드 커널 GP"}
WIN_DELTA = 0.05          # (가) 상위 10% 안 순위 상관 Δ(중앙 차) 문턱 — 임시
WIN_HOLD = 3              # (다) 4명 중
FLAT = -0.02              # 3줄: 신캐 쪽만 낫고 구성 예측은 이 이상
BOOT_B = 1000


# ---------------------------------------------------------------- 저장
def _partial() -> dict[str, Any]:
    p = LOG / "partial34.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(part: Mapping[str, Any]) -> None:
    LOG.mkdir(parents=True, exist_ok=True)
    tmp = LOG / "partial34.json.tmp"
    tmp.write_text(json.dumps(part, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    tmp.replace(LOG / "partial34.json")


def _jsonable(cfg) -> dict:
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in cfg.__dict__.items()}


# ---------------------------------------------------------------- 모델 맞추기
def build(key: str, names, at, cfg):
    els = list(Q.R.ELEMENTS)
    return {"G1": G.GBM, "G2": G.RF, "G3": G.DeepSets, "G4": G.JaccardGP}[key](names, els, at, cfg)


def cfg_of(key: str, d: Mapping[str, Any]):
    cls = {"G1": G.GBMConfig, "G2": G.RFConfig, "G3": G.DSConfig, "G4": G.GPConfig, "M2": M.RoleConfig}[key]
    d = dict(d)
    if "seeds" in d:
        d["seeds"] = tuple(d["seeds"])
    return cls(**d)


def choose(key: str, inner_tr, inner_te, names, at, log: list) -> dict:
    """안쪽 나누기의 상위 10% 안 순위 상관(속성 중앙)으로 고른다. 같으면 앞의 것(작은 모델)."""
    grid = {"G1": GRID_GBM, "G2": GRID_RF, "G3": GRID_DS, "G4": GRID_GP}[key]
    best, best_cfg = None, None
    for g in grid:
        cfg = cfg_of(key, g)
        t0 = time.time()
        mdl = build(key, names, at, cfg)
        if key in ("G1", "G3"):
            mdl.fit(inner_tr, valid=inner_te)       # 반복 수 · 에포크를 안쪽 시험으로 멈춘다
        else:
            mdl.fit(inner_tr)
        m = Q.per_element(inner_te, mdl.predict_total(inner_te))["median"]["rho_top"]
        if key == "G1":
            cfg.rounds = mdl.best_iter
        if key == "G3":
            cfg.epochs = mdl.best_epoch
        log.append({**g, "inner_rho_top": m, "seconds": round(time.time() - t0, 1),
                    **({"rounds": cfg.rounds} if key == "G1" else {}), **({"epochs": cfg.epochs} if key == "G3" else {})})
        print(json.dumps({key: log[-1]}, ensure_ascii=False, default=str), flush=True)
        if best is None or (m is not None and m > best):
            best, best_cfg = m, cfg
        del mdl
        gc.collect()
    return _jsonable(best_cfg)


def fit_predict_all(train, test, names, at, cfgs, gp_var: bool = False) -> tuple[dict, dict]:
    """M0 · M2 · G1~G4를 train에 맞추고 test 총딜 예측. (예측, 걸린 시간). gp_var면 preds["G4_sd"]에 log 예측 표준편차."""
    preds, secs = {}, {}
    t = time.time()
    preds["M0"] = Q.predict_m0(Q.fit_m0(train, names), test)
    secs["M0"] = round(time.time() - t, 1)
    gc.collect()
    t = time.time()
    m2 = Q.fit_m2(train, names, at, cfg_of("M2", cfgs["M2"]))
    preds["M2"] = m2.predict_total(test)
    secs["M2"] = round(time.time() - t, 1)
    del m2
    gc.collect()
    for key in NEW:
        t = time.time()
        mdl = build(key, names, at, cfg_of(key, cfgs[key])).fit(train)
        if key == "G4" and gp_var:
            mu, sd = mdl.predict(test, var=True)
            preds[key], preds["G4_sd"] = np.exp(mu), sd
        else:
            preds[key] = mdl.predict_total(test)
        secs[key] = round(time.time() - t, 1)
        print(json.dumps({"fit": key, "seconds": secs[key]}), flush=True)
        del mdl
        gc.collect()
    return preds, secs


def rank_blend(obs, a, b) -> np.ndarray:
    """속성마다 두 예측의 순위 백분위 평균(관찰용 혼합)."""
    out = np.zeros(len(obs))
    for el in Q.R.ELEMENTS:
        idx = [i for i, o in enumerate(obs) if o.element == el]
        if not idx:
            continue
        ra = M._ranks([a[i] for i in idx]) / max(len(idx) - 1, 1)
        rb = M._ranks([b[i] for i in idx]) / max(len(idx) - 1, 1)
        out[idx] = (ra + rb) / 2
    return out


# ---------------------------------------------------------------- 판단
def verdict(res: Mapping[str, Any]) -> dict[str, Any]:
    a = res["random"]["all"]
    r0 = a["M0"]["median"]["rho_top"] or 0
    out = {}
    for key in ("M2",) + NEW:
        d = (a[key]["median"]["rho_top"] or 0) - r0
        lo = res["random"]["boot"][key]["p5"]
        wins = 0
        for x, h in res["nikke"].items():
            m, m0 = h[key]["median"], h["M0"]["median"]
            wins += (m["rho_top"] or -9) >= (m0["rho_top"] or -9) and m["hit_k"][0] >= m0["hit_k"][0]
        a_ok = d >= WIN_DELTA and lo > 0
        if a_ok and wins >= WIN_HOLD:
            line, text = 1, "후보 — 다음 회차에 계정 탐색의 대리 모델로 붙여 시뮬로 비교"
        elif a_ok:
            line, text = 2, "구성 예측만 후보 — 신캐(니케 가리기)는 릿지보다 못함"
        elif wins >= WIN_HOLD and d >= FLAT:
            line, text = 3, "신캐 쪽만 후보 — 구성 예측은 릿지와 비슷"
        else:
            line, text = 4, "기각(이 자료 · 지표 범위)"
        out[key] = {"line": line, "text": text, "delta_rho_top": d, "boot_p5": lo, "holdout_wins": int(wins)}
    cands = [k for k in NEW if out[k]["line"] in (1, 2, 3)]
    out["summary"] = ("새 모델 후보: " + ", ".join(f"{LABEL[k]}({out[k]['line']}줄)" for k in cands)) if cands \
        else "새 모델 넷 모두 기각 — 지금 릿지 유지(이 자료 범위)"
    return out


# ---------------------------------------------------------------- 실행

def _out_of_time(t0: float) -> bool:
    """RUN34_BUDGET_MIN(분)이 지났으면 새 단계를 시작하지 않는다(실행 시간 제한 대비). 다시 돌리면 이어서 한다."""
    budget = os.environ.get("RUN34_BUDGET_MIN")
    if budget and time.time() - t0 > float(budget) * 60:
        print(json.dumps({"stop": "budget", "minutes": round((time.time() - t0) / 60, 1)}), flush=True)
        return True
    return False


def main() -> int:
    t_all = time.time()
    part = _partial()
    at = Q.R.attrs()
    names = list(Q.R.roster())
    p_obs, pr_obs, probe = Q.load_obs()
    print(json.dumps({"P_obs": len(p_obs), "probe_obs": len(pr_obs)}), flush=True)
    tr_p, te_p = M.split_random(p_obs, Q.TEST_FRAC, Q.SPLIT_SEED)
    inner_tr, inner_te = M.split_random(tr_p, Q.INNER_FRAC, Q.INNER_SEED)
    inner_tr = inner_tr + pr_obs

    # 1. 설정 고르기(안쪽 나누기만)
    part.setdefault("chosen", {})
    part.setdefault("log", {})
    if "M2" not in part["chosen"]:
        lg: list = []
        part["chosen"]["M2"] = _jsonable(Q.choose_m2(tr_p, pr_obs, names, at, lg))
        part["log"]["M2"] = lg
        _save(part)
    for key in NEW:
        if key not in part["chosen"]:
            lg = []
            part["chosen"][key] = choose(key, inner_tr, inner_te, names, at, lg)
            part["log"][key] = lg
            _save(part)
    cfgs = part["chosen"]

    # 2. (가) 무작위 20%
    train = tr_p + pr_obs
    if "random" not in part:
        preds, secs = fit_predict_all(train, te_p, names, at, cfgs, gp_var=True)
        y = np.log([o.total for o in te_p])
        cover = float(np.mean(np.abs(y - np.log(preds["G4"])) <= 1.645 * preds.pop("G4_sd")))
        far = [i for i, s in enumerate(M.max_shared(te_p, train)) if s <= 3]
        res_r = {"all": {k: Q.per_element(te_p, v) for k, v in preds.items()},
                 "far": {k: Q.per_element([te_p[i] for i in far], [v[i] for i in far]) for k, v in preds.items()},
                 "blend": {k: Q.per_element(te_p, rank_blend(te_p, preds["M0"], preds[k])) for k in ("M2",) + NEW},
                 "boot": {k: G.bootstrap_delta(te_p, preds[k], preds["M0"], M.top_metrics, Q.R.ELEMENTS, BOOT_B)
                          for k in ("M2",) + NEW},
                 "gp_cover90": cover, "seconds": secs, "n_test": len(te_p), "n_far": len(far)}
        part["random"] = res_r
        _save(part)
        print(json.dumps({"random": {k: v["median"] for k, v in res_r["all"].items()}}, ensure_ascii=False), flush=True)

    # 3. (다) 니케 가리기(판정에 쓰여 먼저 돈다) — 그 니케의 넣어 보기(R 세트)만 학습에
    part.setdefault("nikke", {})
    for x in Q.HOLD_NIKKES:
        if x in part["nikke"]:
            continue
        if _out_of_time(t_all):
            return 3
        keep = M.observations([r for r in probe if r["set"] == "R" and r["x"] == x])
        tr, _ = M.split_nikke(p_obs + pr_obs, x, keep)
        te = [o for o in p_obs if x in o.comp]
        preds, secs = fit_predict_all(tr, te, names, at, cfgs)
        part["nikke"][x] = {"n_keep": len(keep), "n_test": len(te), **{k: Q.per_element(te, v) for k, v in preds.items()}}
        _save(part)
        print(json.dumps({"nikke": x, "n_keep": len(keep), "n_test": len(te)}, ensure_ascii=False), flush=True)

    # 4. (나) 짝 가리기 — 관찰
    pairs = list(Q.PAIRS_FIXED) + Q.freq_pairs(p_obs, Q.PAIRS_FREQ, Q.PAIRS_FIXED)
    part.setdefault("pair", {})
    for a, b in pairs:
        tag = f"{a} + {b}"
        if tag in part["pair"]:
            continue
        if _out_of_time(t_all):
            return 3
        tr, _ = M.split_pair(p_obs + pr_obs, a, b)
        te = [o for o in p_obs if a in o.comp and b in o.comp]
        if not te:
            part["pair"][tag] = {"n_test": 0}
        else:
            preds, secs = fit_predict_all(tr, te, names, at, cfgs)
            part["pair"][tag] = {"n_test": len(te), **{k: Q.per_element(te, v) for k, v in preds.items()}}
        _save(part)
        print(json.dumps({"pair": tag, "n": len(te)}, ensure_ascii=False), flush=True)

    res = dict(part)
    res["n"] = {"P": len(p_obs), "probe": len(pr_obs)}
    res["verdict"] = verdict(res)
    res["seconds_this_run"] = round(time.time() - t_all, 1)
    (LOG / "res34.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    (HERE / "results.md").write_text(report(res), encoding="utf-8")
    print(json.dumps(res["verdict"], ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- 보고
def _f(v, d=3):
    return "—" if v is None else f"{v:.{d}f}"


def _row(key, met, extra=""):
    m = met["median"]
    return f"| {LABEL.get(key, key)} | {_f(m['rho'])} | {_f(m['rho_top'])} | {m['hit_k'][0]}/{m['hit_k'][1]} |{extra}"


HEAD = "| 모델 | 순위 상관 | 상위 10% 안 | 상위 10 적중 |"


def report(res) -> str:
    v = res["verdict"]
    r = res["random"]
    L = ["# 실험 34 결과 — 대리 모델 넓게 비교", "",
         "`run34.py` 생성. 판단은 README §사전 등록 그대로다. 값은 속성 5개의 중앙(상위 10 적중은 합). 시뮬 0회.", "",
         f"P 관측 {res['n']['P']} · 넣어 보기 관측 {res['n']['probe']}", "",
         f"## 판단 — {v['summary']}", "",
         "| 모델 | Δ 상위 10% 안(대 M0) | 부트스트랩 5% | 니케 가리기 M0 이상 | 줄 |", "|---|---:|---:|---:|---|"]
    for k in ("M2",) + NEW:
        x = v[k]
        L.append(f"| {LABEL[k]} | {x['delta_rho_top']:+.3f} | {x['boot_p5']:+.3f} | {x['holdout_wins']}/4 | {x['line']} — {x['text']} |")
    L += ["", "M2의 채택 여부는 실험 33 Q2 판단을 따른다(여기 줄은 같은 문턱으로 본 참고).", "",
          f"## (가) 무작위 20% — 시험 {r['n_test']}", "", HEAD + " 맞추기 + 예측 초 |", "|---|---:|---:|---:|---:|"]
    L += [_row(k, x, f" {r['seconds'].get(k, '—')} |") for k, x in r["all"].items()]
    L += ["", f"G4 GP의 90% 예측 구간(log 총딜)이 실제를 담은 비율: {_f(r['gp_cover90'])} (명목 0.90).", "",
          f"한 명만 다른 이웃이 학습에 없는 시험 구성 {r['n_far']}개(관찰):", "", HEAD, "|---|---:|---:|---:|"]
    L += [_row(k, x) for k, x in r["far"].items()]
    L += ["", "M0와 순위 평균(관찰):", "", HEAD, "|---|---:|---:|---:|"]
    L += [_row(k, x).replace(LABEL[k], "M0 + " + LABEL[k]) for k, x in r["blend"].items()]
    L += ["", "## 설정 고르기(안쪽 나누기)", ""]
    for k, c in res["chosen"].items():
        L.append(f"- {LABEL[k]}: `{json.dumps(c, ensure_ascii=False, default=str)}`")
    L += ["", "## (나) 짝 가리기(관찰)", ""]
    for p, x in res["pair"].items():
        L += [f"**{p}** — 시험 {x['n_test']}", ""]
        if x["n_test"]:
            L += [HEAD, "|---|---:|---:|---:|"] + [_row(k, x[k]) for k in ("M0", "M2") + NEW] + [""]
    L += ["## (다) 니케 가리기(신캐 모사 — 넣어 보기만 학습에)", ""]
    for nk, x in res["nikke"].items():
        L += [f"**{nk}** — 넣어 보기 {x['n_keep']} · 시험 {x['n_test']}", "", HEAD, "|---|---:|---:|---:|"]
        L += [_row(k, x[k]) for k in ("M0", "M2") + NEW] + [""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
