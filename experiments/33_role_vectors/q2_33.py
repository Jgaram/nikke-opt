"""실험 33 Q2 — 예측력 비교(시뮬 0). README §Q2 사전 등록.

    OPENBLAS_NUM_THREADS=4 python experiments/33_role_vectors/q2_33.py     → q2.md · run_log/q2.json

- 자료: 사전 계산 P(속성 5개 × 시드 2) + 넣어 보기(R · R2 · T). 시험은 P 관측에서만 뽑는다(넣어 보기와 같은 (구성, 속성)은 빼고).
- 모델: M0 실험 10 DualFit(속성마다) · M1 M0 + 지문 특징 · M2 역할 벡터 · M3 M2 + 지문 시작값(니케 가리기에서만).
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent


def _load(name, path):
    import importlib.util
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load("run33", HERE / "run33.py")
M = _load("roles33", HERE / "roles33.py")
S4 = R.R10.S4

# ---------------------------------------------------------------- 사전 등록한 값(README §Q2)
SPLIT_SEED, INNER_SEED = "exp33-q2-split", "exp33-q2-inner"
TEST_FRAC, INNER_FRAC = 0.20, 0.10
PAIRS_FIXED = ((R.BREAD, R.TOVE), ("아르카나 : 포츈 메이트", "도로시 : 세렌디피티"))
PAIRS_FREQ = 2                     # + P 속성별 상위 1% 구성에서 가장 자주 함께 나오는 짝 2개(위 둘 제외)
HOLD_NIKKES = ("아르카나 : 포츈 메이트", "스노우 화이트 : 헤비암즈", R.BREAD, "아니스 : 스타")
GRID_M2 = [(k, lu) for k in (4, 8, 16) for lu in (1e-3, 1e-2)]   # (차원, u · v 벌점), lam_r = 0.1
GRID_R = (1e-2, 1.0)                # 위 최선에서 lam_r 바꿔 보기
GRID_F = (0.1, 1.0, 10.0)           # M1 지문 특징 벌점
LAM_PRIOR = 1.0                     # M3 끌어당김
WIN_TOP = 0.10                      # 판단: M2(또는 M3) − M0 상위 10% 안 순위 상관 ≥ +0.10
WIN_M1 = 0.05
FP_KEYS = ("dealer", "buffer", "own_adv")


# ---------------------------------------------------------------- 자료
def load_obs() -> tuple[list, list, list]:
    """(P 관측, 넣어 보기 관측, 넣어 보기 기록)."""
    precs = []
    for el in R.ELEMENTS:
        for k in R.SEEDS:
            for r in R.load_recs(R.pre_path(el, k)):
                r["element"] = el
                precs.append(r)
    probe = [r for s in ("R", "R2", "T") for r in R.load_recs(R.LOG / f"probe_{s}.jsonl.gz")]
    p_obs = M.observations(precs)
    pr_obs = M.observations(probe)
    seen = {(o.comp, o.element) for o in pr_obs}
    p_obs = [o for o in p_obs if (o.comp, o.element) not in seen]
    return p_obs, pr_obs, probe


def freq_pairs(p_obs: Sequence, n: int, exclude) -> list[tuple[str, str]]:
    cnt: Counter = Counter()
    for el in R.ELEMENTS:
        xs = sorted((o for o in p_obs if o.element == el), key=lambda o: -o.total)
        for o in xs[:max(1, len(xs) // 100)]:
            cnt.update(tuple(sorted(p)) for p in combinations(o.comp, 2))
    ex = {tuple(sorted(p)) for p in exclude}
    return [p for p, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])) if p not in ex][:n]


# ---------------------------------------------------------------- M1: DualFit + 지문 특징
def fp_features(comp_squad: Sequence[str], element: str, fp: Mapping[str, Mapping], at) -> list[float]:
    """[Σ dealer, Σ buffer, Σ 우코 · own_adv, Σ_X Σ_Y boost_weapon(Y)[무기 X] · dealer(X), Σ_X Σ_Y boost_stage(Y)[단계 X] · dealer(X)]."""
    def g(x, k):
        v = fp.get(x, {}).get(k)
        return 0.0 if v is None else float(v)
    f = [0.0] * 5
    for x in comp_squad:
        f[0] += g(x, "dealer")
        f[1] += g(x, "buffer")
        if R.adv_element(at[x]["code"]) == element:
            f[2] += g(x, "own_adv")
        for y in comp_squad:
            if y == x:
                continue
            bw = fp.get(y, {}).get("boost_weapon", {}).get(at[x]["weapon"])
            bs = fp.get(y, {}).get("boost_stage", {}).get(at[x]["stage"])
            f[3] += (bw or 0.0) * g(x, "dealer")
            f[4] += (bs or 0.0) * g(x, "dealer")
    return f


class DualFP:
    """실험 10 DualFit과 같은 니케 + 짝 커널(같은 해 — 테스트로 확인)에 지문 특징 커널 F Fᵀ / lam_f를 더한다.
    F가 None이면 M0(DualFit과 같다). 특징은 학습 구성으로 표준화한다. 메모리를 아끼려고 커널을 제자리에서 만든다."""

    def __init__(self, obs: Sequence, names: Sequence[str], F: np.ndarray | None = None, lam_f: float = 1.0):
        self.ni = {n: i for i, n in enumerate(names)}
        self.M = self._onehot(obs)
        self.lam_f = lam_f
        if F is not None:
            self.mu, self.sd = F.mean(0), F.std(0) + 1e-12
            self.F = (F - self.mu) / self.sd / math.sqrt(lam_f)
        else:
            self.F = None
        y = np.array([o.total / 1e8 for o in obs])
        K = self.M @ self.M.T
        T = K - 1.0
        T *= K
        T /= 2 * S4.LAM_P
        K /= S4.LAM_U
        K += T
        del T
        if self.F is not None:
            K += self.F @ self.F.T
        K[np.diag_indices_from(K)] += 1.0
        uv = np.linalg.solve(K, np.c_[y, np.ones(len(obs))])
        del K
        self.b = float(uv[:, 0].sum() / uv[:, 1].sum())
        self.alpha = uv[:, 0] - self.b * uv[:, 1]

    def _onehot(self, obs):
        X = np.zeros((len(obs), len(self.ni)))
        for r, o in enumerate(obs):
            for n in o.comp:
                X[r, self.ni[n]] = 1.0
        return X

    def predict(self, obs: Sequence, F: np.ndarray | None = None) -> np.ndarray:
        out = np.empty(len(obs))
        for i in range(0, len(obs), 4000):
            part = obs[i:i + 4000]
            s = self._onehot(part) @ self.M.T
            k = s / S4.LAM_U + s * (s - 1) / 2 / S4.LAM_P
            if self.F is not None:
                k += ((F[i:i + 4000] - self.mu) / self.sd / math.sqrt(self.lam_f)) @ self.F.T
            out[i:i + 4000] = (self.b + k @ self.alpha) * 1e8
        return out


def fit_m0(train, names):
    return {el: DualFP([o for o in train if o.element == el], names) for el in sorted({o.element for o in train})}


def predict_m0(models, obs):
    out = np.zeros(len(obs))
    for el, mdl in models.items():
        idx = [i for i, o in enumerate(obs) if o.element == el]
        if idx:
            out[idx] = mdl.predict([obs[i] for i in idx])
    return out


def fit_m1(train, names, fp, at, lam_f):
    out = {}
    for el in sorted({o.element for o in train}):
        tr = [o for o in train if o.element == el]
        F = np.array([fp_features(o.squad, el, fp, at) for o in tr])
        out[el] = DualFP(tr, names, F, lam_f)
    return out


def predict_m1(models, obs, fp, at):
    out = np.zeros(len(obs))
    for el, mdl in models.items():
        idx = [i for i, o in enumerate(obs) if o.element == el]
        if idx:
            F = np.array([fp_features(obs[i].squad, el, fp, at) for i in idx])
            out[idx] = mdl.predict([obs[i] for i in idx], F)
    return out


# ---------------------------------------------------------------- M3: 지문 → 매개변수 사상
def feat_vec(x: str, fp, at) -> list[float]:
    f = fp.get(x, {})
    v = [float(f.get(k) or 0.0) for k in FP_KEYS] + [float(f.get("adv_lift") or 1.0)]
    for w in ("AR", "SMG", "SG", "SR", "RL", "MG"):
        v.append(float(f.get("boost_weapon", {}).get(w) or 0.0))
    for w in ("AR", "SMG", "SG", "SR", "RL", "MG"):
        v.append(1.0 if at[x]["weapon"] == w else 0.0)
    for s in ("1", "2", "3", "A"):
        v.append(1.0 if at[x]["stage"] == s else 0.0)
    return v


def prior_from(mod: Any, names_fit: Sequence[str], targets: Sequence[str], fp, at, lam: float = 1.0) -> dict[str, dict]:
    """M2에서 맞춘 니케들의 (a, c, u, v)를 지문 · 속성 특징으로 릿지 회귀해 targets의 시작값을 낸다."""
    X = np.array([feat_vec(n, fp, at) for n in names_fit])
    mu, sd = X.mean(0), X.std(0) + 1e-12
    Xs = np.c_[np.ones(len(X)), (X - mu) / sd]
    Y = np.array([[mod.a[mod.ni[n]], mod.c[mod.ni[n]], *mod.u[mod.ni[n]], *mod.v[mod.ni[n]]] for n in names_fit])
    pen = np.r_[0.0, np.full(Xs.shape[1] - 1, lam)]
    W = np.linalg.solve(Xs.T @ Xs + np.diag(pen), Xs.T @ Y)
    k = mod.cfg.k
    out = {}
    for t in targets:
        z = np.r_[1.0, (np.array(feat_vec(t, fp, at)) - mu) / sd] @ W
        out[t] = {"a": float(z[0]), "c": float(z[1]), "u": z[2:2 + k].tolist(), "v": z[2 + k:2 + 2 * k].tolist()}
    return out


# ---------------------------------------------------------------- 평가
def per_element(obs: Sequence, pred: Sequence[float]) -> dict[str, Any]:
    """속성마다 지표, 그리고 속성 5개의 중앙."""
    out: dict[str, Any] = {}
    for el in R.ELEMENTS:
        idx = [i for i, o in enumerate(obs) if o.element == el]
        if len(idx) >= 3:
            out[el] = M.top_metrics([obs[i].total for i in idx], [pred[i] for i in idx])
    vals = lambda key: [v[key] for v in out.values() if isinstance(v, dict) and v.get(key) is not None]
    out["median"] = {"rho": statistics.median(vals("rho")) if vals("rho") else None,
                     "rho_top": statistics.median(vals("rho_top")) if vals("rho_top") else None,
                     "hit_k": [sum(v["hit_k"][0] for v in out.values() if isinstance(v, dict) and "hit_k" in v),
                               sum(v["hit_k"][1] for v in out.values() if isinstance(v, dict) and "hit_k" in v)]}
    return out


def fit_m2(train, names, at, cfg) -> Any:
    adv = {n: R.adv_element(at[n]["code"]) for n in names}
    return M.RoleModel(list(names), list(R.ELEMENTS), adv, cfg).fit(train)


def choose_m2(train_p, probe_obs, names, at, log) -> M.RoleConfig:
    """안쪽 나누기(학습 P 구성 10%)의 상위 10% 안 순위 상관(속성 중앙)으로 고른다. 같으면 작은 차원."""
    inner_tr, inner_te = M.split_random(train_p, INNER_FRAC, INNER_SEED)
    best, best_cfg = None, None
    for k, lu in GRID_M2:
        cfg = M.RoleConfig(k=k, lam_uv=lu, lam_r=0.1)
        t0 = time.time()
        mod = fit_m2(inner_tr + probe_obs, names, at, cfg)
        m = per_element(inner_te, mod.predict_total(inner_te))["median"]["rho_top"]
        log.append({"k": k, "lam_uv": lu, "lam_r": 0.1, "inner_rho_top": m, "seconds": round(time.time() - t0, 1)})
        print(json.dumps(log[-1]), flush=True)
        if best is None or (m is not None and m > best):
            best, best_cfg = m, cfg
    for lr_ in GRID_R:
        cfg = M.RoleConfig(k=best_cfg.k, lam_uv=best_cfg.lam_uv, lam_r=lr_)
        mod = fit_m2(inner_tr + probe_obs, names, at, cfg)
        m = per_element(inner_te, mod.predict_total(inner_te))["median"]["rho_top"]
        log.append({"k": cfg.k, "lam_uv": cfg.lam_uv, "lam_r": lr_, "inner_rho_top": m})
        print(json.dumps(log[-1]), flush=True)
        if m is not None and m > best:
            best, best_cfg = m, cfg
    return best_cfg


def choose_m1(train_p, probe_obs, names, fp, at, log) -> float:
    inner_tr, inner_te = M.split_random(train_p, INNER_FRAC, INNER_SEED)
    best, best_l = None, None
    for lf in GRID_F:
        mdl = fit_m1(inner_tr + probe_obs, names, fp, at, lf)
        m = per_element(inner_te, predict_m1(mdl, inner_te, fp, at))["median"]["rho_top"]
        log.append({"lam_f": lf, "inner_rho_top": m})
        print(json.dumps(log[-1]), flush=True)
        if best is None or (m is not None and m > best):
            best, best_l = m, lf
    return best_l


# ---------------------------------------------------------------- 실행
def member_ratio(mod, test, x: str) -> float | None:
    """시험 관측에서 x 본인 딜의 실제 / 예측 중앙(M2)."""
    if not test:
        return None
    pm = mod.predict_members(test)
    rs = [o.members[o.squad.index(x)] / pm[j][o.squad.index(x)] for j, o in enumerate(test) if pm[j][o.squad.index(x)] > 0]
    return statistics.median(rs) if rs else None


def verdict(res: Mapping[str, Any]) -> dict[str, Any]:
    """README §Q2 판단 표."""
    a = res["random"]["all"]
    d2 = (a["M2"]["median"]["rho_top"] or 0) - (a["M0"]["median"]["rho_top"] or 0)
    d1 = (a["M1"]["median"]["rho_top"] or 0) - (a["M0"]["median"]["rho_top"] or 0)
    wins = 0
    for x, h in res["nikke"].items():
        m0 = h["M0"]["median"]
        better = []
        for key in ("M2", "M3"):
            m = h[key]["median"]
            better.append((m["rho_top"] or -9) >= (m0["rho_top"] or -9) and m["hit_k"][0] >= m0["hit_k"][0])
        wins += any(better)
    a_ok, c_ok = d2 >= WIN_TOP, wins >= 3
    if a_ok and c_ok:
        line, text = 1, "채택 — 역할 벡터를 다음 단계(Q4 · 탐색에 붙이기)로"
    elif a_ok:
        line, text = 2, "구성 예측은 낫다, 신캐(니케 가리기)는 미달 — Q4 전에 신캐 쪽 보강"
    elif d1 >= WIN_M1:
        line, text = 3, "역할 벡터는 미달, 지문을 릿지 특징(M1)으로만 쓴다"
    else:
        line, text = 4, "중단 — 지금 릿지 유지, 원인 정리"
    return {"line": line, "text": text, "d_rho_top_M2": d2, "d_rho_top_M1": d1, "holdout_wins": wins}


def main() -> int:
    t_all = time.time()
    at = R.attrs()
    names = list(R.roster())
    q1 = json.loads((R.LOG / "q1.json").read_text(encoding="utf-8"))
    fp_key = "R" if q1["checks"]["repro"]["stable"] else "R+R2"
    fp = q1["fp"][fp_key]
    p_obs, pr_obs, probe = load_obs()
    print(json.dumps({"P_obs": len(p_obs), "probe_obs": len(pr_obs), "fp": fp_key}), flush=True)
    res: dict[str, Any] = {"fp_source": fp_key, "n": {"P": len(p_obs), "probe": len(pr_obs)}, "log": {"m2": [], "m1": []}}

    # (가) 무작위 — 하이퍼파라미터도 여기 학습 쪽에서만 고른다
    tr_p, te_p = M.split_random(p_obs, TEST_FRAC, SPLIT_SEED)
    cfg = choose_m2(tr_p, pr_obs, names, at, res["log"]["m2"])
    lam_f = choose_m1(tr_p, pr_obs, names, fp, at, res["log"]["m1"])
    res["chosen"] = {"m2": cfg.__dict__, "m1_lam_f": lam_f}
    train = tr_p + pr_obs
    preds = {"M0": predict_m0(fit_m0(train, names), te_p),
             "M1": predict_m1(fit_m1(train, names, fp, at, lam_f), te_p, fp, at)}
    m2 = fit_m2(train, names, at, cfg)
    preds["M2"] = m2.predict_total(te_p)
    far = [i for i, s in enumerate(M.max_shared(te_p, train)) if s <= 3]
    res["random"] = {"all": {k: per_element(te_p, v) for k, v in preds.items()},
                     "far": {k: per_element([te_p[i] for i in far], [v[i] for i in far]) for k, v in preds.items()},
                     "n_test": len(te_p), "n_far": len(far)}
    res["roles"] = {x: m2.params_of(x) for x in names}
    print(json.dumps({"random": {k: v["median"] for k, v in res["random"]["all"].items()}}, ensure_ascii=False), flush=True)

    # (나) 짝 가리기
    pairs = list(PAIRS_FIXED) + freq_pairs(p_obs, PAIRS_FREQ, PAIRS_FIXED)
    res["pair"] = {}
    for a, b in pairs:
        tr, _ = M.split_pair(p_obs + pr_obs, a, b)
        te = [o for o in p_obs if a in o.comp and b in o.comp]
        if not te:
            res["pair"][f"{a} + {b}"] = {"n_test": 0}
            continue
        mdl = fit_m2(tr, names, at, cfg)
        pr = {"M0": predict_m0(fit_m0(tr, names), te), "M1": predict_m1(fit_m1(tr, names, fp, at, lam_f), te, fp, at),
              "M2": mdl.predict_total(te)}
        res["pair"][f"{a} + {b}"] = {"n_test": len(te), **{k: per_element(te, v) for k, v in pr.items()},
                                     "member_ratio_" + a: member_ratio(mdl, te, a), "member_ratio_" + b: member_ratio(mdl, te, b)}
        print(json.dumps({"pair": f"{a} + {b}", "n": len(te)}, ensure_ascii=False), flush=True)

    # (다) 니케 가리기 — 그 니케의 넣어 보기(R 세트, 그 니케를 넣은 칸)만 학습에 남긴다
    res["nikke"] = {}
    for x in HOLD_NIKKES:
        keep = M.observations([r for r in probe if r["set"] == "R" and r["x"] == x])
        tr, _ = M.split_nikke(p_obs + pr_obs, x, keep)
        te = [o for o in p_obs if x in o.comp]
        mdl = fit_m2(tr, names, at, cfg)
        others = [n for n in names if n != x and n in fp]
        prior = prior_from(mdl, others, [x], fp, at)
        m3 = M.RoleModel(list(names), list(R.ELEMENTS), {n: R.adv_element(at[n]["code"]) for n in names}, cfg,
                         prior=prior, lam_prior=LAM_PRIOR).fit(tr)
        pr = {"M0": predict_m0(fit_m0(tr, names), te), "M1": predict_m1(fit_m1(tr, names, fp, at, lam_f), te, fp, at),
              "M2": mdl.predict_total(te), "M3": m3.predict_total(te)}
        res["nikke"][x] = {"n_keep": len(keep), "n_test": len(te), **{k: per_element(te, v) for k, v in pr.items()},
                           "member_ratio": {"M2": member_ratio(mdl, te, x), "M3": member_ratio(m3, te, x)}}
        print(json.dumps({"nikke": x, "n_keep": len(keep), "n_test": len(te)}, ensure_ascii=False), flush=True)

    res["verdict"] = verdict(res)
    res["seconds"] = round(time.time() - t_all, 1)
    (R.LOG / "q2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (HERE / "q2.md").write_text(report(res), encoding="utf-8")
    print(json.dumps(res["verdict"], ensure_ascii=False))
    return 0


def _f(v, d=3):
    return "—" if v is None else f"{v:.{d}f}"


def _row(name, met):
    m = met["median"]
    return f"| {name} | {_f(m['rho'])} | {_f(m['rho_top'])} | {m['hit_k'][0]}/{m['hit_k'][1]} |"


def report(res) -> str:
    L = ["# 실험 33 Q2 — 예측력 비교", "", "`q2_33.py` 생성. 판단은 README §Q2 사전 등록 그대로다. 값은 속성 5개의 중앙(상위 10 적중은 합).", "",
         f"지문 출처 {res['fp_source']} · P 관측 {res['n']['P']} · 넣어 보기 관측 {res['n']['probe']} · 고른 M2 {res['chosen']['m2']} · M1 lam_f {res['chosen']['m1_lam_f']}", "",
         f"## 판단: {res['verdict']['line']}줄 — {res['verdict']['text']}", "",
         f"M2 − M0 상위 10% 안 순위 상관 {res['verdict']['d_rho_top_M2']:+.3f} · M1 − M0 {res['verdict']['d_rho_top_M1']:+.3f} · 니케 가리기 4명 중 M2/M3가 M0 이상 {res['verdict']['holdout_wins']}명", "",
         f"## (가) 무작위 20% — 시험 {res['random']['n_test']}", "", "| 모델 | 순위 상관 | 상위 10% 안 | 상위 10 적중 |", "|---|---:|---:|---:|"]
    L += [_row(k, v) for k, v in res["random"]["all"].items()]
    L += ["", f"한 명만 다른 이웃이 학습에 없는 시험 구성 {res['random']['n_far']}개:", "", "| 모델 | 순위 상관 | 상위 10% 안 | 상위 10 적중 |", "|---|---:|---:|---:|"]
    L += [_row(k, v) for k, v in res["random"]["far"].items()]
    L += ["", "## (나) 짝 가리기", ""]
    for p, v in res["pair"].items():
        L += [f"**{p}** — 시험 {v['n_test']}", ""]
        if v["n_test"]:
            L += ["| 모델 | 순위 상관 | 상위 10% 안 | 상위 10 적중 |", "|---|---:|---:|---:|"] + [_row(k, v[k]) for k in ("M0", "M1", "M2")]
            L += ["", " · ".join(f"{k.replace('member_ratio_', '')} 본인 딜 실제/예측 {_f(vv, 2)}" for k, vv in v.items() if k.startswith("member_ratio_")), ""]
    L += ["## (다) 니케 가리기(신캐 모사 — 넣어 보기만 학습에)", ""]
    for x, v in res["nikke"].items():
        L += [f"**{x}** — 넣어 보기 {v['n_keep']} · 시험 {v['n_test']} · 본인 딜 실제/예측 M2 {_f(v['member_ratio']['M2'], 2)} · M3 {_f(v['member_ratio']['M3'], 2)}", "",
              "| 모델 | 순위 상관 | 상위 10% 안 | 상위 10 적중 |", "|---|---:|---:|---:|"] + [_row(k, v[k]) for k in ("M0", "M1", "M2", "M3")] + [""]
    L += [f"걸린 시간 {res['seconds']}초(시뮬 0)."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
