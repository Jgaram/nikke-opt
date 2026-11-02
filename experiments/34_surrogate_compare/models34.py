"""실험 34 — 대리 모델 넓게 비교(시뮬 0). README §모델.

실험 33 Q2와 같은 관측(`roles33.Obs`) · 나누기 · 지표를 쓰고, 모델만 바꾼다.

- G1 LightGBM, G2 랜덤 포레스트: 표 특징(니케 원-핫 177 · 보스 속성 5 · 속성 개수 19)으로 log 총딜.
- G3 Deep Sets: 니케마다 (이름 임베딩 + 속성 원-핫 + 우코) → φ → 합 → ρ(+ 보스 속성) → log 총딜. 시드 3개 평균.
- G4 자카드 커널 GP: 속성마다. 니케 자카드 · 짝 자카드(둘 다 공유 니케 수 s의 함수) + 속성 개수 RBF. log 총딜.

니케 속성은 실험 33 `attrs.json`(무기 · 단계 · 클래스 · 코드)만 쓴다. 스킬 효과는 쓰지 않는다.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

WEAPONS = ("AR", "SMG", "SG", "SR", "RL", "MG")
STAGES = ("1", "2", "3", "A")
CLASSES = ("화력형", "지원형", "방어형")
CODES = ("작열", "수냉", "철갑", "전격", "풍압")
# 게임 규칙(실험 33 run33.BEATS와 같다): 왼쪽 코드가 오른쪽 속성 보스에 우월 코드다.
BEATS = {"작열": "풍압", "풍압": "철갑", "철갑": "전격", "전격": "수냉", "수냉": "작열"}
N_MEMBER = len(WEAPONS) + len(STAGES) + len(CLASSES) + len(CODES) + 1      # 19 = 원-핫 18 + 우코


# ---------------------------------------------------------------- 특징
def member_attr(x: str, element: str, at: Mapping[str, Mapping[str, str]]) -> list[float]:
    """니케 하나의 속성 원-핫(무기 6 · 단계 4 · 클래스 3 · 코드 5) + 우코 1."""
    a = at[x]
    v = [1.0 if a["weapon"] == w else 0.0 for w in WEAPONS]
    v += [1.0 if a["stage"] == s else 0.0 for s in STAGES]
    v += [1.0 if a["class"] == c else 0.0 for c in CLASSES]
    v += [1.0 if a["code"] == c else 0.0 for c in CODES]
    v.append(1.0 if BEATS[a["code"]] == element else 0.0)
    return v


def attr_counts(comp: Sequence[str], element: str, at) -> np.ndarray:
    """구성의 속성 개수(19) — 니케마다 member_attr의 합."""
    return np.sum([member_attr(x, element, at) for x in comp], axis=0)


def table(obs: Sequence[Any], names: Sequence[str], elements: Sequence[str], at) -> np.ndarray:
    """표 특징: [니케 원-핫 | 보스 속성 원-핫 | 속성 개수]. float32."""
    ni = {n: i for i, n in enumerate(names)}
    ei = {e: i for i, e in enumerate(elements)}
    nn_, ne = len(names), len(elements)
    X = np.zeros((len(obs), nn_ + ne + N_MEMBER), dtype=np.float32)
    for r, o in enumerate(obs):
        for x in o.comp:
            X[r, ni[x]] = 1.0
        X[r, nn_ + ei[o.element]] = 1.0
        X[r, nn_ + ne:] = attr_counts(sorted(o.comp), o.element, at)
    return X


def log_total(obs: Sequence[Any]) -> np.ndarray:
    return np.log(np.array([o.total for o in obs], dtype=float))


# ---------------------------------------------------------------- G1 LightGBM
@dataclass
class GBMConfig:
    num_leaves: int = 31
    min_data_in_leaf: int = 20
    learning_rate: float = 0.05
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    bagging_freq: int = 1
    max_rounds: int = 5000
    early_stop: int = 100
    rounds: int | None = None          # 정해지면(안쪽 나누기의 최선 반복 수) 그만큼만 돈다
    seed: int = 20261102


class GBM:
    def __init__(self, names, elements, at, cfg: GBMConfig):
        self.names, self.elements, self.at, self.cfg = list(names), list(elements), at, cfg
        self.best_iter: int | None = None

    def _params(self):
        c = self.cfg
        return {"objective": "regression", "num_leaves": c.num_leaves, "min_data_in_leaf": c.min_data_in_leaf,
                "learning_rate": c.learning_rate, "feature_fraction": c.feature_fraction,
                "bagging_fraction": c.bagging_fraction, "bagging_freq": c.bagging_freq,
                "seed": c.seed, "deterministic": True, "force_row_wise": True, "num_threads": 4, "verbose": -1}

    def fit(self, train, valid=None) -> "GBM":
        import lightgbm as lgb
        X, y = table(train, self.names, self.elements, self.at), log_total(train)
        ds = lgb.Dataset(X, y, free_raw_data=True)
        if valid is not None:
            Xv, yv = table(valid, self.names, self.elements, self.at), log_total(valid)
            dv = lgb.Dataset(Xv, yv, reference=ds)
            self.model = lgb.train(self._params(), ds, num_boost_round=self.cfg.max_rounds, valid_sets=[dv],
                                   callbacks=[lgb.early_stopping(self.cfg.early_stop, verbose=False)])
            self.best_iter = int(self.model.best_iteration)
        else:
            self.model = lgb.train(self._params(), ds, num_boost_round=self.cfg.rounds or self.cfg.max_rounds)
            self.best_iter = self.cfg.rounds
        return self

    def predict_total(self, obs) -> np.ndarray:
        X = table(obs, self.names, self.elements, self.at)
        return np.exp(self.model.predict(X, num_iteration=self.best_iter))


# ---------------------------------------------------------------- G2 랜덤 포레스트
@dataclass
class RFConfig:
    n_estimators: int = 300
    max_features: Any = 0.33
    min_samples_leaf: int = 1
    seed: int = 20261102


class RF:
    def __init__(self, names, elements, at, cfg: RFConfig):
        self.names, self.elements, self.at, self.cfg = list(names), list(elements), at, cfg

    def fit(self, train) -> "RF":
        from sklearn.ensemble import RandomForestRegressor
        c = self.cfg
        self.model = RandomForestRegressor(n_estimators=c.n_estimators, max_features=c.max_features,
                                           min_samples_leaf=c.min_samples_leaf, n_jobs=4, random_state=c.seed)
        self.model.fit(table(train, self.names, self.elements, self.at), log_total(train))
        return self

    def predict_total(self, obs) -> np.ndarray:
        return np.exp(self.model.predict(table(obs, self.names, self.elements, self.at)))


# ---------------------------------------------------------------- G3 Deep Sets
@dataclass
class DSConfig:
    d: int = 16                    # 이름 임베딩 차원
    hidden: int = 128
    weight_decay: float = 0.0
    lr: float = 1e-3
    batch: int = 512
    max_epochs: int = 60
    patience: int = 6
    epochs: int | None = None      # 정해지면(안쪽 나누기의 최선 에포크) 그만큼만 돈다
    seeds: tuple = (20261102, 20261103, 20261104)


def _ds_arrays(obs, names, elements, at):
    ni = {n: i for i, n in enumerate(names)}
    ei = {e: i for i, e in enumerate(elements)}
    ids = np.array([[ni[x] for x in sorted(o.comp)] for o in obs], dtype=np.int64)
    attr = np.array([[member_attr(x, o.element, at) for x in sorted(o.comp)] for o in obs], dtype=np.float32)
    el = np.zeros((len(obs), len(elements)), dtype=np.float32)
    el[np.arange(len(obs)), [ei[o.element] for o in obs]] = 1.0
    return ids, attr, el


class DeepSets:
    """φ(이름 임베딩 ‖ 속성) → 합 → ρ(‖ 보스 속성). 순서 없는 묶음 입력이라 배치 순서와 무관하다."""

    def __init__(self, names, elements, at, cfg: DSConfig):
        self.names, self.elements, self.at, self.cfg = list(names), list(elements), at, cfg
        self.best_epoch: int | None = None

    def _net(self):
        import torch.nn as nn

        class Net(nn.Module):
            def __init__(s, n, d, h, ne):
                super().__init__()
                s.emb = nn.Embedding(n, d)
                s.phi = nn.Sequential(nn.Linear(d + N_MEMBER, h), nn.ReLU(), nn.Linear(h, h), nn.ReLU())
                s.rho = nn.Sequential(nn.Linear(h + ne, h), nn.ReLU(), nn.Linear(h, 1))

            def forward(s, ids, attr, el):
                import torch
                z = s.phi(torch.cat([s.emb(ids), attr], -1)).sum(1)
                return s.rho(torch.cat([z, el], -1)).squeeze(-1)

        return Net(len(self.names), self.cfg.d, self.cfg.hidden, len(self.elements))

    def fit(self, train, valid=None) -> "DeepSets":
        import torch
        torch.set_num_threads(4)
        c = self.cfg
        A = [torch.from_numpy(a) for a in _ds_arrays(train, self.names, self.elements, self.at)]
        y = log_total(train)
        self.mu, self.sd = float(y.mean()), float(y.std())
        Y = torch.from_numpy(((y - self.mu) / self.sd).astype(np.float32))
        if valid is not None:
            Av = [torch.from_numpy(a) for a in _ds_arrays(valid, self.names, self.elements, self.at)]
            Yv = torch.from_numpy(((log_total(valid) - self.mu) / self.sd).astype(np.float32))
        self.nets, best_epochs = [], []
        for seed in c.seeds:
            torch.manual_seed(seed)
            g = torch.Generator().manual_seed(seed)
            net = self._net()
            opt = torch.optim.Adam(net.parameters(), lr=c.lr, weight_decay=c.weight_decay)
            n_ep = c.epochs or c.max_epochs
            best, best_ep, best_state, bad = math.inf, 0, None, 0
            for ep in range(1, n_ep + 1):
                net.train()
                perm = torch.randperm(len(Y), generator=g)
                for i in range(0, len(Y), c.batch):
                    b = perm[i:i + c.batch]
                    opt.zero_grad()
                    loss = ((net(A[0][b], A[1][b], A[2][b]) - Y[b]) ** 2).mean()
                    loss.backward()
                    opt.step()
                if valid is None:
                    continue
                net.eval()
                with torch.no_grad():
                    vl = float(((net(*Av) - Yv) ** 2).mean())
                if vl < best - 1e-6:
                    best, best_ep, bad = vl, ep, 0
                    best_state = {k: v.clone() for k, v in net.state_dict().items()}
                else:
                    bad += 1
                    if bad >= c.patience:
                        break
            if best_state is not None:
                net.load_state_dict(best_state)
                best_epochs.append(best_ep)
            net.eval()
            self.nets.append(net)
        if best_epochs:
            self.best_epoch = int(round(sum(best_epochs) / len(best_epochs)))
        return self

    def predict_total(self, obs) -> np.ndarray:
        import torch
        A = [torch.from_numpy(a) for a in _ds_arrays(obs, self.names, self.elements, self.at)]
        with torch.no_grad():
            z = np.mean([net(*A).numpy() for net in self.nets], axis=0)
        return np.exp(z * self.sd + self.mu)


# ---------------------------------------------------------------- G4 자카드 커널 GP
def set_kernel(s: np.ndarray) -> np.ndarray:
    """5인 구성 둘의 공유 니케 수 s → ½(니케 자카드 + 짝 자카드). 니케 J = s / (10 − s), 짝 J = p / (20 − p), p = s(s − 1)/2."""
    s = np.asarray(s, dtype=float)
    p = s * (s - 1) / 2
    return 0.5 * (s / (10 - s) + p / (20 - p))


@dataclass
class GPConfig:
    w_attr: float = 0.0           # 속성 RBF 커널 몫(나머지는 자카드)
    noise: float = 0.1            # 표준화한 log 총딜 기준 잡음 분산
    ell_sample: int = 2000        # RBF 폭 = 학습 속성 벡터 사이 거리의 중앙(무작위 2,000개)
    seed: int = 20261102
    chunk: int = 500


class JaccardGP:
    """속성마다 정확한 GP 평균 · 분산(상수 평균, 표준화한 log 총딜)."""

    def __init__(self, names, elements, at, cfg: GPConfig):
        self.names, self.elements, self.at, self.cfg = list(names), list(elements), at, cfg
        self.ni = {n: i for i, n in enumerate(names)}

    def _onehot(self, obs):
        M = np.zeros((len(obs), len(self.names)))
        for r, o in enumerate(obs):
            for x in o.comp:
                M[r, self.ni[x]] = 1.0
        return M

    def _attr(self, obs, el):
        return np.array([attr_counts(sorted(o.comp), el, self.at) for o in obs], dtype=float)

    def _k(self, Ma, Aa, Mb, Ab, m):
        K = (1 - self.cfg.w_attr) * set_kernel(Ma @ Mb.T)
        if self.cfg.w_attr > 0:
            d2 = (Aa ** 2).sum(1)[:, None] + (Ab ** 2).sum(1)[None, :] - 2 * Aa @ Ab.T
            K += self.cfg.w_attr * np.exp(-np.maximum(d2, 0) / (2 * m["ell"] ** 2))
        return K

    def fit(self, train) -> "JaccardGP":
        """학습 관측만 기억한다. 분해는 predict에서 속성 하나씩 하고 버린다(속성마다 n×n 행렬 — 한꺼번에 들면 메모리가 넘친다)."""
        self.train = list(train)
        return self

    def _factor(self, el):
        from scipy.linalg import cho_factor, cho_solve
        tr = [o for o in self.train if o.element == el]
        y = log_total(tr)
        m: dict[str, Any] = {"mu": float(y.mean()), "sd": float(y.std())}
        M = self._onehot(tr)
        A = self._attr(tr, el)
        m["amu"], m["asd"] = A.mean(0), A.std(0) + 1e-12
        A = (A - m["amu"]) / m["asd"]
        rng = np.random.default_rng(self.cfg.seed)
        idx = rng.choice(len(A), size=min(self.cfg.ell_sample, len(A)), replace=False)
        sub = A[idx]
        d = np.sqrt(np.maximum((sub ** 2).sum(1)[:, None] + (sub ** 2).sum(1)[None, :] - 2 * sub @ sub.T, 0))
        m["ell"] = float(np.median(d[np.triu_indices(len(sub), 1)])) or 1.0
        n = len(tr)
        K = np.empty((n, n))
        for i in range(0, n, self.cfg.chunk):
            K[i:i + self.cfg.chunk] = self._k(M[i:i + self.cfg.chunk], A[i:i + self.cfg.chunk], M, A, m)
        K[np.diag_indices(n)] += self.cfg.noise
        # K는 대칭이라 K.T(포트란 순서)를 넘기면 scipy가 복사하지 않고 제자리에서 분해한다
        m["L"] = cho_factor(K.T, lower=True, overwrite_a=True, check_finite=False)
        del K
        m["alpha"] = cho_solve(m["L"], (y - m["mu"]) / m["sd"], check_finite=False)
        m["M"], m["A"] = M, A
        return m

    def predict(self, obs, var: bool = False):
        from scipy.linalg import cho_solve
        mean, sdv = np.zeros(len(obs)), np.zeros(len(obs))
        for el in sorted({o.element for o in self.train}):
            idx = [i for i, o in enumerate(obs) if o.element == el]
            if not idx:
                continue
            m = self._factor(el)
            for j in range(0, len(idx), self.cfg.chunk):
                part = [obs[i] for i in idx[j:j + self.cfg.chunk]]
                Ms = self._onehot(part)
                As = (self._attr(part, el) - m["amu"]) / m["asd"]
                Ks = self._k(Ms, As, m["M"], m["A"], m)
                ii = idx[j:j + self.cfg.chunk]
                mean[ii] = m["mu"] + m["sd"] * (Ks @ m["alpha"])
                if var:
                    v = cho_solve(m["L"], Ks.T, check_finite=False)
                    prior = 1.0                                           # 자카드(s = 5 → 1) · RBF(0 → 1)의 대각
                    sdv[ii] = m["sd"] * np.sqrt(np.maximum(prior - (Ks * v.T).sum(1), 0) + self.cfg.noise)
            del m
        return (mean, sdv) if var else mean

    def predict_total(self, obs) -> np.ndarray:
        return np.exp(self.predict(obs))


# ---------------------------------------------------------------- 부트스트랩
def bootstrap_delta(obs: Sequence[Any], pred_x: Sequence[float], pred_0: Sequence[float], metrics_fn,
                    elements: Sequence[str], B: int = 1000, seed: str = "exp34-boot") -> dict[str, float]:
    """(가) 시험 관측을 속성마다 복원 추출해 Δ = 중앙_속성 rho_top(X) − 중앙_속성 rho_top(M0)의 분포. 5 · 50 · 95 백분위."""
    rng = random.Random(seed)
    by_el = {e: [i for i, o in enumerate(obs) if o.element == e] for e in elements}
    px, p0 = np.asarray(pred_x, float), np.asarray(pred_0, float)
    act = np.array([o.total for o in obs], dtype=float)
    out = []
    for _ in range(B):
        rx, r0 = [], []
        for e, idx in by_el.items():
            if len(idx) < 10:
                continue
            s = [idx[rng.randrange(len(idx))] for _ in idx]
            a = act[s]
            mx, m0 = metrics_fn(a, px[s]), metrics_fn(a, p0[s])
            if mx.get("rho_top") is not None and m0.get("rho_top") is not None:
                rx.append(mx["rho_top"])
                r0.append(m0["rho_top"])
        if rx:
            out.append(float(np.median(rx) - np.median(r0)))
    q = np.percentile(out, [5, 50, 95]) if out else [math.nan] * 3
    return {"p5": float(q[0]), "p50": float(q[1]), "p95": float(q[2]), "B": len(out)}


def timed(fn, *a, **k):
    t = time.time()
    r = fn(*a, **k)
    return r, round(time.time() - t, 1)
