"""실험 33 Q2 — 역할 벡터 모델과 비교용 자료 · 나누기(시뮬 0). README §B.

모델 M2: 니케별 딜의 로그를 예측한다(버프는 곱으로 걸리므로 로그에서 더하기가 된다).

    log d(X | S, e) ≈ a_X + g_e + c_X · adv(X, e) + ⟨u_X, Σ_{Y ∈ S, Y ≠ X} v_Y⟩ + Σ_{Y ∈ S, Y ≠ X} r_XY

- a_X 기본 딜, g_e 보스 속성 배율, c_X 우코 배율(adv = X 코드가 e에 우코면 1), u_X 받는 쪽 · v_Y 주는 쪽(비대칭), r_XY 관측된 짝 보정.
- 총딜 예측 = Σ_X exp(예측). 전체 일괄 Adam(numpy, CPU), 난수 시드 고정.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

EPS = 1e6            # 로그 전에 더하는 값(0.01억) — 딜이 0인 니케(순수 지원)를 위해


# ---------------------------------------------------------------- 자료
@dataclass
class Obs:
    """구성 하나 · 속성 하나의 관측(그 구성의 최고 총딜 배치 순서 기록)."""
    comp: frozenset
    element: str
    squad: tuple
    total: float
    members: tuple          # 스쿼드 순서 니케별 딜


def observations(recs: Iterable[Mapping[str, Any]], element_of=None) -> list[Obs]:
    """기록 → (구성, 속성)마다 총딜이 가장 큰 배치 순서의 관측. element_of(r)가 None이면 r["element"]."""
    best: dict[tuple, Obs] = {}
    for r in recs:
        if r.get("total_damage") is None or r.get("members") is None:
            continue
        el = r["element"] if element_of is None else element_of(r)
        sq = tuple(r["squad"])
        key = (frozenset(sq), el)
        t = float(r["total_damage"])
        if key not in best or t > best[key].total:
            best[key] = Obs(key[0], el, sq, t, tuple(float(v) for v in r["members"]))
    return list(best.values())


def split_random(obs: Sequence[Obs], frac: float, seed: str) -> tuple[list[Obs], list[Obs]]:
    """구성 단위로 무작위 frac을 시험에 둔다(같은 구성의 다른 속성 관측이 양쪽에 섞이지 않게)."""
    comps = sorted({o.comp for o in obs}, key=lambda c: sorted(c))
    rng = random.Random(seed)
    test = set(rng.sample(comps, round(frac * len(comps))))
    return [o for o in obs if o.comp not in test], [o for o in obs if o.comp in test]


def split_pair(obs: Sequence[Obs], a: str, b: str) -> tuple[list[Obs], list[Obs]]:
    """짝 가리기: a와 b가 함께 든 구성을 모두 시험에."""
    hit = [o for o in obs if a in o.comp and b in o.comp]
    return [o for o in obs if not (a in o.comp and b in o.comp)], hit


def split_nikke(obs: Sequence[Obs], x: str, keep: Iterable[Obs] = ()) -> tuple[list[Obs], list[Obs]]:
    """니케 가리기(신캐 모사): x가 든 구성을 모두 시험에 두되, keep(그 니케의 넣어 보기 관측)만 학습에 남긴다."""
    keep = list(keep)
    kk = {(o.comp, o.element) for o in keep}
    train = [o for o in obs if x not in o.comp] + keep
    test = [o for o in obs if x in o.comp and (o.comp, o.element) not in kk]
    return train, test


def max_shared(test: Sequence[Obs], train: Sequence[Obs]) -> list[int]:
    """시험 관측마다 같은 속성 학습 구성과 공유하는 니케 수의 최댓값(4 = 한 명만 다른 이웃이 학습에 있다)."""
    by_el: dict[str, list[frozenset]] = {}
    for o in train:
        by_el.setdefault(o.element, []).append(o.comp)
    out = []
    for o in test:
        best = 0
        for c in by_el.get(o.element, ()):
            s = len(o.comp & c)
            if s > best:
                best = s
                if best >= 4:
                    break
        out.append(best)
    return out


# ---------------------------------------------------------------- 평가 지표
def _ranks(v: Sequence[float]) -> np.ndarray:
    a = np.asarray(v, dtype=float)
    order = np.argsort(a, kind="mergesort")
    r = np.empty(len(a))
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and a[order[j + 1]] == a[order[i]]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def top_metrics(actual: Sequence[float], pred: Sequence[float], top: float = 0.10, k: int = 10) -> dict[str, Any]:
    """전체 순위 상관, 실제 상위 top 안 순위 상관, 실제 상위 k 중 예측 상위 k에 든 수."""
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    n = len(a)
    out: dict[str, Any] = {"n": n, "rho": spearman(a, p)}
    if n >= 10:
        m = max(3, int(math.ceil(top * n)))
        idx = np.argsort(-a, kind="mergesort")[:m]
        out["rho_top"] = spearman(a[idx], p[idx])
    kk = min(k, n)
    if kk:
        ta = set(np.argsort(-a, kind="mergesort")[:kk].tolist())
        tp = set(np.argsort(-p, kind="mergesort")[:kk].tolist())
        out["hit_k"] = [len(ta & tp), kk]
    return out


# ---------------------------------------------------------------- M2 역할 벡터
@dataclass
class RoleConfig:
    k: int = 8                  # 벡터 차원
    lam_uv: float = 1e-2        # u · v 벌점(관측 1개당 평균 손실 기준)
    lam_r: float = 1e-1         # 짝 보정 벌점
    lam_ac: float = 1e-4        # a · c 벌점(약하게)
    lr: float = 0.03
    iters: int = 800
    seed: int = 20261102


@dataclass
class RoleModel:
    names: list[str]
    elements: list[str]
    adv_of: Mapping[str, str]                    # 니케 → 우코 속성
    cfg: RoleConfig = field(default_factory=RoleConfig)
    prior: Mapping[str, Mapping[str, Any]] | None = None   # 니케 → {"a", "c", "u", "v"} 시작값 · 끌어당김(M3)
    lam_prior: float = 0.0

    def __post_init__(self):
        self.ni = {n: i for i, n in enumerate(self.names)}
        self.ei = {e: i for i, e in enumerate(self.elements)}
        n, k = len(self.names), self.cfg.k
        rng = np.random.default_rng(self.cfg.seed)
        self.a = np.zeros(n)
        self.c = np.zeros(n)
        self.g = np.zeros(len(self.elements))
        self.u = 0.01 * rng.standard_normal((n, k))
        self.v = 0.01 * rng.standard_normal((n, k))
        self.r = np.zeros((n, n))
        self.loss_trace: list[float] = []

    # 관측 → 배열
    def _arrays(self, obs: Sequence[Obs]):
        S = np.array([[self.ni[x] for x in o.squad] for o in obs], dtype=np.int64)
        E = np.array([self.ei[o.element] for o in obs], dtype=np.int64)
        ADV = np.array([[1.0 if self.adv_of[x] == o.element else 0.0 for x in o.squad] for o in obs])
        T = np.log(np.array([o.members for o in obs]) + EPS)
        return S, E, ADV, T

    def _forward(self, S, E, ADV):
        U, V = self.u[S], self.v[S]                              # N×5×k
        VS = V.sum(1, keepdims=True)
        inter = np.einsum("nik,nik->ni", U, VS - V)
        R = self.r[S[:, :, None], S[:, None, :]]                 # N×5×5, R[n,i,j] = r[X_i, Y_j]
        idx = np.arange(S.shape[1])
        R[:, idx, idx] = 0.0
        return self.a[S] + self.g[E][:, None] + self.c[S] * ADV + inter + R.sum(2), U, V, VS

    def fit(self, obs: Sequence[Obs]) -> "RoleModel":
        S, E, ADV, T = self._arrays(obs)
        n, k = len(self.names), self.cfg.k
        N = T.size
        # 시작값: a = 니케 평균 로그 딜, g = 속성 평균 차
        cnt = np.bincount(S.ravel(), minlength=n)
        s = np.bincount(S.ravel(), weights=T.ravel(), minlength=n)
        self.a = np.where(cnt > 0, s / np.maximum(cnt, 1), T.mean())
        if self.prior:
            for x, p in self.prior.items():
                i = self.ni.get(x)
                if i is None:
                    continue
                if cnt[i] == 0 and "a" in p:
                    self.a[i] = p["a"]
                for key, arr in (("c", self.c), ("u", self.u), ("v", self.v)):
                    if key in p:
                        arr[i] = p[key]
        prior_mask = np.zeros(n, dtype=bool)
        P = {key: np.zeros_like(arr) for key, arr in (("a", self.a), ("c", self.c), ("u", self.u), ("v", self.v))}
        if self.prior and self.lam_prior:
            for x, p in self.prior.items():
                i = self.ni.get(x)
                if i is not None:
                    prior_mask[i] = True
                    for key in P:
                        if key in p:
                            P[key][i] = p[key]
        params = {"a": self.a, "c": self.c, "g": self.g, "u": self.u, "v": self.v, "r": self.r}
        m = {key: np.zeros_like(v) for key, v in params.items()}
        vv = {key: np.zeros_like(v) for key, v in params.items()}
        b1, b2, cfg = 0.9, 0.999, self.cfg
        pos = np.arange(S.shape[1])
        flatS = S.ravel()
        for it in range(1, cfg.iters + 1):
            pred, U, V, VS = self._forward(S, E, ADV)
            err = pred - T                                           # N×5
            self.loss_trace.append(float((err ** 2).mean()))
            e2 = 2 * err / N
            grads = {}
            grads["a"] = np.bincount(flatS, weights=e2.ravel(), minlength=n) + 2 * cfg.lam_ac * self.a / n
            grads["c"] = np.bincount(flatS, weights=(e2 * ADV).ravel(), minlength=n) + 2 * cfg.lam_ac * self.c / n
            grads["g"] = np.bincount(E, weights=e2.sum(1), minlength=len(self.elements))
            gu = e2[:, :, None] * (VS - V)                           # N×5×k
            eu = e2[:, :, None] * U
            gv = eu.sum(1, keepdims=True) - eu
            grads["u"] = np.stack([np.bincount(flatS, weights=gu[:, :, j].ravel(), minlength=n) for j in range(k)], 1) \
                + 2 * cfg.lam_uv * self.u / n
            grads["v"] = np.stack([np.bincount(flatS, weights=gv[:, :, j].ravel(), minlength=n) for j in range(k)], 1) \
                + 2 * cfg.lam_uv * self.v / n
            # r[X_i, Y_j] += e_i (i ≠ j)
            rows = np.repeat(S[:, :, None], S.shape[1], 2)
            cols = np.repeat(S[:, None, :], S.shape[1], 1)
            w = np.repeat(e2[:, :, None], S.shape[1], 2)
            w[:, pos, pos] = 0.0
            gr = np.bincount((rows * n + cols).ravel(), weights=w.ravel(), minlength=n * n).reshape(n, n)
            grads["r"] = gr + 2 * cfg.lam_r * self.r / n
            if self.lam_prior and prior_mask.any():
                for key in ("a", "c", "u", "v"):
                    d = params[key] - P[key]
                    msk = prior_mask if d.ndim == 1 else prior_mask[:, None]
                    grads[key] = grads[key] + 2 * self.lam_prior * np.where(msk, d, 0.0) / n
            for key, p in params.items():
                gk = grads[key]
                m[key] = b1 * m[key] + (1 - b1) * gk
                vv[key] = b2 * vv[key] + (1 - b2) * gk * gk
                mh = m[key] / (1 - b1 ** it)
                vh = vv[key] / (1 - b2 ** it)
                p -= cfg.lr * mh / (np.sqrt(vh) + 1e-8)
        return self

    def predict_members(self, obs: Sequence[Obs]) -> np.ndarray:
        S, E, ADV, _ = self._arrays(obs) if obs and obs[0].members else self._arrays_nolabel(obs)
        pred, *_ = self._forward(S, E, ADV)
        return np.maximum(np.exp(pred) - EPS, 0.0)

    def _arrays_nolabel(self, obs):
        S = np.array([[self.ni[x] for x in o.squad] for o in obs], dtype=np.int64)
        E = np.array([self.ei[o.element] for o in obs], dtype=np.int64)
        ADV = np.array([[1.0 if self.adv_of[x] == o.element else 0.0 for x in o.squad] for o in obs])
        return S, E, ADV, None

    def predict_total(self, obs: Sequence[Obs]) -> np.ndarray:
        return self.predict_members(obs).sum(1)

    def params_of(self, x: str) -> dict[str, Any]:
        i = self.ni[x]
        return {"a": float(self.a[i]), "c": float(self.c[i]), "u": self.u[i].tolist(), "v": self.v[i].tolist()}


# ---------------------------------------------------------------- M0 지금 릿지(속성마다)
class _Book:
    def __init__(self, best):
        self.best = best


def fit_m0(train: Sequence[Obs], names: Sequence[str], dual_cls) -> dict[str, Any]:
    """속성마다 실험 10 `DualFit`(니케 + 짝 릿지, 총딜 억). dual_cls = R10.DualFit."""
    out = {}
    for el in sorted({o.element for o in train}):
        best = {o.comp: (o.total / 1e8, o.squad) for o in train if o.element == el}
        out[el] = dual_cls(_Book(best), list(names))
    return out


def predict_m0(models: Mapping[str, Any], obs: Sequence[Obs]) -> np.ndarray:
    return np.array([models[o.element](o.comp) * 1e8 for o in obs])
