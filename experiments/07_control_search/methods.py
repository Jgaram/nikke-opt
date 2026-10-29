"""실험 7 — 컨트롤 선택지 탐색 기법 M0~M3와 실행기 (README §기법).

선택지 공간은 실험 6의 `menu.variants(squad)`다. 선택 = 키(니케, 축)마다 선택지 하나 또는 「바꾸지 않음」.
값 = 그 선택을 기본 레이어 위에 얹은 요청의 총딜(`accumulate`, 기본 적). 예산은 평가 수(서로 다른 선택 집합 수)다.

    # 사전값 학습(개발 기록 → prior.json)
    python experiments/07_control_search/methods.py prior --out <prior.json> [--exclude c17,c24] [--extra <run_dir>...]
    # 기법 실행 (조합 × 기법) — 작업마다 <out>/<comp>__<method>.jsonl, 끝나면 .done
    source .cache/evaluators.env && python experiments/07_control_search/methods.py run \
        --set dev --comps c04,c17 --methods M0,M1:attr,M2:attr,M3:k2 --budget 800 --prior <prior.json> --out <dir>

기법 (모두 「중간에 끊어도 그때까지의 최선」이 나온다 — 한 번의 800평가 실행에서 앞부분을 읽는다)
- `M0`: 실험 6 `search_from_layer`의 좌표 하강. 수렴하면 예산이 남아도 끝난다.
- `M1:<prior>`: M0 다음, 2키 동시 변경 이웃을 모델(아래)의 사후 평균이 예측한 이득 순으로 `BATCH`개씩 평가한다.
  개선되면 받아들이고 다시 좌표 하강한다. 모델은 평가가 쌓일 때마다 다시 맞춘다.
- `M2:<prior>`: 기본 레이어 + 한 선택지씩 얹은 점을 모두 평가한 뒤(초기 설계), 모델의 사후에서 가중치를 `BATCH`번
  뽑아(Thompson sampling) 각 표본의 대리 함수를 최대화한 선택을 평가하기를 반복한다(BOCS 계열).
- `M3:k<n>`: M0 다음, 지금까지의 최선에서 키 n개를 무작위로 바꿔(킥) 다시 좌표 하강하기를 반복한다(반복 국소 탐색).

모델 — 선택지 + 선택지 쌍의 베이즈 2차 회귀. y = log(총딜 / 기본 레이어 총딜), 특징 = 고른 선택지 지시자와
서로 다른 키의 두 선택지 지시자 곱. 사전 분포는 특징 묶음마다 평균·분산이다:
- 선택지 묶음 = (축, 선택지 종류) — 종류는 label의 이름(장전컨 `A0.3` 등, 버충은 `버충`, 카메라는 `camera`).
- 쌍 묶음 = (두 축, 같은 니케를 다루는가) — 니케는 니케 단위 축은 그 니케, 버충·카메라는 대상 니케.
- `attr`: 위 묶음별 값을 개발 기록에서 EM(경험적 베이즈)으로 배운다. `flat`: 선택지 한 묶음 · 쌍 한 묶음, 평균 0.
니케 이름은 특징에 넣지 않는다 — 새 조합 · 새 니케에도 그대로 쓴다.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
EXP6 = HERE.parent / "06_control_menu"
sys.path[:0] = [str(EXP6), str(HERE.parent.parent)]
import common  # noqa: E402
import menu as menu6  # noqa: E402
from menu import MenuConflict  # noqa: E402

DEV_COMPS = EXP6 / "compositions.json"
VAL_COMPS = HERE / "val_compositions.json"
EXP6_RECORDS = EXP6 / "run_log" / "main.jsonl.gz"
BATCH = 8           # M1 · M2가 한 번에 평가하는 수
RESTARTS = 24       # 대리 함수 최대화의 무작위 재시작 수(표본마다)
CONFLICT_W = -10.0  # 조립 불가 쌍의 대리 가중치(사실상 금지)
VAR_FLOOR = 1e-8
FLAT_GROUPS = ("main", "pair")


# ---------------------------------------------------------------- 선택지 공간

def _name(v: Mapping[str, Any]) -> str:
    """label `<니케 또는 squad>:<axis>:<이름>`의 이름. 니케 이름에도 `:`가 있어 축 위치로 자른다."""
    lb, tag = v["label"], f":{v['axis']}:"
    return lb[lb.index(tag) + len(tag):]


def _name_class(v: Mapping[str, Any]) -> str:
    name = _name(v)
    if v["axis"] == "tactic":
        return name.split("=", 1)[0]
    if v["axis"] == "camera":
        return "camera"
    return name


def _subject(v: Mapping[str, Any]) -> str | None:
    if v["nikke"] is not None:
        return v["nikke"]
    name = _name(v)
    if v["axis"] == "tactic":
        return name.split("=", 1)[1] if "=" in name else None
    if v["axis"] == "camera":
        return name
    return None


class Space:
    """조합 하나의 선택지 공간. 선택(sel)은 키 순서의 tuple, 원소는 선택지 번호(평탄 목록) 또는 -1(바꾸지 않음)."""

    def __init__(self, squad: Sequence[str], variants_fn: Callable = menu6.variants,
                 apply_fn: Callable = menu6.apply, base: Mapping[str, Any] | None = None):
        self.squad = list(squad)
        self.menu = dict(variants_fn(self.squad))
        self.keys = list(self.menu)
        self.vars: list[dict[str, Any]] = []
        self.key_of: list[int] = []
        self.opts: list[list[int]] = []
        for ki, k in enumerate(self.keys):
            ids = []
            for v in self.menu[k]:
                ids.append(len(self.vars))
                self.vars.append(v)
                self.key_of.append(ki)
            self.opts.append(ids)
        self.nv, self.K = len(self.vars), len(self.keys)
        self.index = {v["label"]: i for i, v in enumerate(self.vars)}
        self.apply_fn = apply_fn
        self.base = dict(common.START_OPTIONS["layer"] if base is None else base)
        self.key_arr = np.array(self.key_of, dtype=int)
        # 조립 불가 쌍(같은 니케 홀드 + 엄폐컨 등): 두 선택지만 얹어 apply가 거절하면 쌍 금지
        # menu.conflicts는 두 선택지 사이의 규칙뿐이라 쌍만 보면 된다
        check = (lambda ids: bool(menu6.conflicts([self.vars[i] for i in ids]))) if apply_fn is menu6.apply \
            else self._conflict
        self.conflict_pairs: set[tuple[int, int]] = set()
        for a in range(self.nv):
            for b in range(a + 1, self.nv):
                if self.key_of[a] != self.key_of[b] and check([a, b]):
                    self.conflict_pairs.add((a, b))
        self._bad = {a: set() for a in range(self.nv)}
        for a, b in self.conflict_pairs:
            self._bad[a].add(b)
            self._bad[b].add(a)

    def ok(self, sel: Sequence[int]) -> bool:
        """조립할 수 있는가(조립 불가 쌍이 없는가)."""
        ch = [i for i in sel if i >= 0]
        return not any(b in self._bad[a] for a in ch for b in ch)

    def empty(self) -> tuple[int, ...]:
        return (-1,) * self.K

    def chosen(self, sel: Sequence[int]) -> list[dict[str, Any]]:
        return [self.vars[i] for i in sel if i >= 0]

    def labels(self, sel: Sequence[int]) -> tuple[str, ...]:
        return tuple(sorted(self.vars[i]["label"] for i in sel if i >= 0))

    def from_labels(self, labels: Iterable[str]) -> tuple[int, ...] | None:
        sel = [-1] * self.K
        for lb in labels:
            i = self.index.get(lb)
            if i is None:
                return None
            sel[self.key_of[i]] = i
        return tuple(sel)

    def _conflict(self, ids: Sequence[int]) -> bool:
        try:
            self.apply_fn(self.base, [self.vars[i] for i in ids])
        except MenuConflict:
            return True
        return False

    def options(self, sel: Sequence[int]) -> dict[str, Any] | None:
        """요청 options. 조립 불가면 None."""
        ch = self.chosen(sel)
        if not ch:
            return dict(self.base)
        try:
            return self.apply_fn(self.base, ch)
        except MenuConflict:
            return None

    def neighbors(self, sel: Sequence[int], k: int) -> list[tuple[int, ...]]:
        """키 k만 바꾼 선택들 — 실험 6 좌표 하강의 후보 순서(선택지 순서, 그다음 「바꾸지 않음」)."""
        out = []
        for o in self.opts[k]:
            if sel[k] != o:
                s = list(sel)
                s[k] = o
                out.append(tuple(s))
        if sel[k] >= 0:
            s = list(sel)
            s[k] = -1
            out.append(tuple(s))
        return out

    def onehot(self, sels: Sequence[Sequence[int]]) -> np.ndarray:
        X = np.zeros((len(sels), self.nv))
        for r, s in enumerate(sels):
            for i in s:
                if i >= 0:
                    X[r, i] = 1.0
        return X


# ---------------------------------------------------------------- 실행(평가 · 예산 · 기록)

class Run:
    """(조합, 기법) 하나의 평가 상태. 같은 선택은 한 번만 평가하고, 조립 불가는 시뮬·예산 밖이다."""

    def __init__(self, comp: Mapping[str, Any], space: Space, ev: Any, *, method: str, budget: int,
                 out: Path | None, lookup: Mapping[str, int] | None = None):
        self.comp, self.space, self.ev, self.method = comp, space, ev, method
        self.budget, self.out, self.lookup = budget, out, lookup or {}
        self.seen: dict[tuple[int, ...], int | None] = {}
        self.used = 0
        self.lookups = 0
        self.history: list[tuple[tuple[int, ...], int]] = []  # 오류 없이 평가한 (선택, 딜), 평가 순
        self.best: int | None = None
        self.best_sel: tuple[int, ...] = space.empty()
        self.base_damage: int | None = None
        self.exhausted = False
        self._fh = open(out, "w", encoding="utf-8") if out else None

    def close(self) -> None:
        if self._fh:
            self._fh.close()

    def value(self, sel: tuple[int, ...]) -> int | None:
        return self.seen.get(sel)

    def evaluate(self, sels: Sequence[tuple[int, ...]]) -> list[int | None]:
        """선택들의 딜(오류·조립 불가·예산 밖은 None). 처음 보는 것만 평가하고, 예산이 모자라면 앞에서부터."""
        from nikke_opt.evaluator import EvalRequest
        todo: list[tuple[tuple[int, ...], dict]] = []
        queued: set[tuple[int, ...]] = set()
        for s in sels:
            if s in self.seen or s in queued:
                continue
            opts = self.space.options(s)
            if opts is None:
                self.seen[s] = None
                continue
            if self.used + len(todo) >= self.budget:
                self.exhausted = True
                break
            todo.append((s, opts))
            queued.add(s)
        if todo:
            reqs = [EvalRequest(tuple(self.comp["squad"]), boss=common.BOSS, options=o) for _, o in todo]
            lines = [r.to_line() for r in reqs]
            keys = [json.dumps(ln, sort_keys=True, ensure_ascii=False) for ln in lines]
            miss = [i for i, k in enumerate(keys) if k not in self.lookup]
            futs = dict(zip(miss, self.ev.submit([reqs[i] for i in miss]))) if miss else {}
            for i, (s, _) in enumerate(todo):
                if i in futs:
                    res = futs[i].result()
                    dmg = None if res.error else res.total_damage
                    err, cached = res.error, res.cached
                else:
                    dmg, err, cached = self.lookup[keys[i]], None, "lookup"
                    self.lookups += 1
                self.seen[s] = dmg
                self.used += 1
                if dmg is not None:
                    self.history.append((s, dmg))
                    if self.base_damage is None and all(x < 0 for x in s):
                        self.base_damage = dmg
                    if self.best is None or dmg > self.best:
                        self.best, self.best_sel = dmg, s
                if self._fh:
                    self._fh.write(json.dumps({
                        "comp_id": self.comp["id"], "method": self.method, "step": self.used - 1,
                        "variants": list(self.space.labels(s)), "total_damage": dmg, "error": err,
                        "cached": cached, "sim_count": self.ev.sim_count}, ensure_ascii=False) + "\n")
            if self._fh:
                self._fh.flush()
        return [self.seen.get(s) for s in sels]


def _better(a: int | None, b: int | None) -> bool:
    return a is not None and (b is None or a > b)


def descend(run: Run, start: tuple[int, ...]) -> tuple[tuple[int, ...], int | None]:
    """실험 6 `_descend`와 같은 좌표 하강: 키 순서대로 그 키의 후보를 한 번에 평가해 엄격히 좋은 최선으로 바꾼다.
    직전에 바꾼 키를 뺀 모든 키를 한 바퀴 돌 동안 개선이 없으면 끝난다. 이미 본 선택은 다시 평가하지 않는다."""
    sp = run.space
    cur = start
    best = run.evaluate([cur])[0]
    idle, i, limit = 0, 0, sp.K
    while sp.K and idle < limit and not run.exhausted:
        cands = sp.neighbors(cur, i)
        vals = run.evaluate(cands)
        pick, pv = None, best
        for c, v in zip(cands, vals):
            if _better(v, pv):
                pick, pv = c, v
        if pick is not None:
            cur, best = pick, pv
            idle, limit = 0, sp.K - 1
        else:
            idle += 1
        i = (i + 1) % sp.K
    return cur, best


# ---------------------------------------------------------------- 모델(베이즈 2차 회귀)

def pair_group(va: Mapping[str, Any], vb: Mapping[str, Any]) -> str:
    axes = "|".join(sorted((va["axis"], vb["axis"])))
    sa, sb = _subject(va), _subject(vb)
    same = sa is not None and sa == sb
    return f"{axes}|{'same' if same else 'other'}"


def main_group(v: Mapping[str, Any]) -> str:
    return f"{v['axis']}|{_name_class(v)}"


class Prior:
    """특징 묶음 → (평균, 분산), 잡음 분산. `flat`은 묶음 둘(main · pair)뿐이고 평균 0."""

    def __init__(self, kind: str, groups: Mapping[str, tuple[float, float]], sigma2: float,
                 fallback: Mapping[str, tuple[float, float]] | None = None):
        self.kind, self.groups, self.sigma2 = kind, dict(groups), sigma2
        self.fallback = dict(fallback or {})

    def group_of_main(self, v: Mapping[str, Any]) -> str:
        return "main" if self.kind == "flat" else main_group(v)

    def group_of_pair(self, va: Mapping[str, Any], vb: Mapping[str, Any]) -> str:
        return "pair" if self.kind == "flat" else pair_group(va, vb)

    def get(self, g: str, is_pair: bool) -> tuple[float, float]:
        if g in self.groups:
            return self.groups[g]
        return self.fallback.get("pair" if is_pair else "main", (0.0, 1e-3))

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "sigma2": self.sigma2, "groups": self.groups, "fallback": self.fallback}

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> "Prior":
        return cls(d["kind"], {k: tuple(v) for k, v in d["groups"].items()}, d["sigma2"],
                   {k: tuple(v) for k, v in d.get("fallback", {}).items()})


class Model:
    """선택지 + 쌍 특징의 베이즈 선형 회귀. 사후는 쌍대 형태(n×n)로 계산하고, 표본은 경로 조건화(Matheron)로 뽑는다."""

    def __init__(self, space: Space, prior: Prior):
        self.sp = space
        nv = space.nv
        pa, pb = [], []
        for a in range(nv):
            for b in range(a + 1, nv):
                if space.key_of[a] != space.key_of[b] and (a, b) not in space.conflict_pairs:
                    pa.append(a)
                    pb.append(b)
        self.pa, self.pb = np.array(pa, dtype=int), np.array(pb, dtype=int)
        self.main_groups = [prior.group_of_main(v) for v in space.vars]
        self.pair_groups = [prior.group_of_pair(space.vars[a], space.vars[b]) for a, b in zip(pa, pb)]
        mg = [prior.get(g, False) for g in self.main_groups]
        pg = [prior.get(g, True) for g in self.pair_groups]
        self.m0 = np.array([m for m, _ in mg] + [m for m, _ in pg])
        self.s0 = np.maximum(np.array([s for _, s in mg] + [s for _, s in pg]), VAR_FLOOR)
        self.sigma2 = max(prior.sigma2, VAR_FLOOR)
        self.d = len(self.m0)
        self.Phi: np.ndarray | None = None

    def features(self, sels: Sequence[Sequence[int]]) -> np.ndarray:
        X = self.sp.onehot(sels)
        return np.hstack([X, X[:, self.pa] * X[:, self.pb]])

    def fit(self, sels: Sequence[Sequence[int]], y: np.ndarray) -> None:
        self.Phi = self.features(sels)
        self.y = np.asarray(y, dtype=float)
        PS = self.Phi * self.s0
        Kmat = PS @ self.Phi.T + self.sigma2 * np.eye(len(self.y))
        self.L = np.linalg.cholesky(Kmat)
        r = self.y - self.Phi @ self.m0
        self.alpha = self._solve(r)
        self.mean = self.m0 + self.s0 * (self.Phi.T @ self.alpha)

    def _solve(self, r: np.ndarray) -> np.ndarray:
        z = np.linalg.solve(self.L, r)
        return np.linalg.solve(self.L.T, z)

    def sample(self, rng: np.random.Generator) -> np.ndarray:
        w0 = self.m0 + np.sqrt(self.s0) * rng.standard_normal(self.d)
        if self.Phi is None:
            return w0
        eps = math.sqrt(self.sigma2) * rng.standard_normal(len(self.y))
        return w0 + self.s0 * (self.Phi.T @ self._solve(self.y - self.Phi @ w0 - eps))

    def quadratic(self, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """가중치 → (h, W): 대리 값 = Σ h[i] x_i + Σ_{i<j} W[i,j] x_i x_j. W는 대칭, 같은 키 · 대각은 0."""
        nv = self.sp.nv
        h = w[:nv].copy()
        W = np.zeros((nv, nv))
        W[self.pa, self.pb] = w[nv:]
        W[self.pb, self.pa] = w[nv:]
        for a, b in self.sp.conflict_pairs:
            W[a, b] = W[b, a] = CONFLICT_W
        return h, W


def surrogate(h: np.ndarray, W: np.ndarray, X: np.ndarray) -> np.ndarray:
    """one-hot 행렬 X(n×nv)의 대리 값."""
    return X @ h + 0.5 * np.einsum("ij,jk,ik->i", X, W, X)


def local_max(space: Space, h: np.ndarray, W: np.ndarray, start: Sequence[int]) -> tuple[float, tuple[int, ...]]:
    """대리 함수의 최선 개선 단일 키 이동 언덕 오르기. (값, 선택)."""
    cur = np.array(start, dtype=int)
    C = [i for i in cur if i >= 0]
    f = h + (W[:, C].sum(axis=1) if C else 0.0)
    val = float(sum(h[i] for i in C) + 0.5 * sum(W[i, j] for i in C for j in C))
    ka = space.key_arr
    for _ in range(4 * space.K + 10):
        a_of = cur[ka]
        fa = np.where(a_of >= 0, f[np.maximum(a_of, 0)], 0.0)
        delta = f - fa
        delta[a_of == np.arange(space.nv)] = -np.inf
        b = int(np.argmax(delta))
        db = float(delta[b])
        on = np.flatnonzero(cur >= 0)
        if len(on):
            neg = -f[cur[on]]
            j = int(np.argmax(neg))
            none_k, dn = int(on[j]), float(neg[j])
        else:
            none_k, dn = -1, -np.inf
        if max(db, dn) <= 1e-12:
            break
        if db >= dn:
            k = space.key_of[b]
            a = cur[k]
            if a >= 0:
                f -= W[:, a]
            f += W[:, b]
            cur[k] = b
            val += db
        else:
            a = cur[none_k]
            f -= W[:, a]
            cur[none_k] = -1
            val += dn
    return val, tuple(int(x) for x in cur)


def random_sel(space: Space, rng: random.Random) -> tuple[int, ...]:
    return tuple(rng.choice(opts + [-1]) for opts in space.opts)


def maximize(space: Space, h: np.ndarray, W: np.ndarray, starts: Sequence[tuple[int, ...]],
             rng: random.Random, restarts: int = RESTARTS) -> list[tuple[float, tuple[int, ...]]]:
    """여러 출발점에서 언덕 오르기 → (값, 선택) 내림차순(중복 제거)."""
    found: dict[tuple[int, ...], float] = {}
    for s in list(starts) + [random_sel(space, rng) for _ in range(restarts)]:
        v, sel = local_max(space, h, W, s)
        found[sel] = v
    return sorted(((v, s) for s, v in found.items()), key=lambda x: -x[0])


def _y(run: Run) -> tuple[list[tuple[int, ...]], np.ndarray]:
    base = run.base_damage
    sels = [s for s, _ in run.history]
    y = np.array([math.log(d / base) for _, d in run.history])
    return sels, y


# ---------------------------------------------------------------- 기법

def m0(run: Run, **_: Any) -> None:
    descend(run, run.space.empty())


def m3(run: Run, *, kick: int = 2, seed: int = 0, **_: Any) -> None:
    sp = run.space
    rng = random.Random(seed)
    descend(run, sp.empty())
    stale = 0
    while not run.exhausted and stale < 200:
        before = run.used
        s = list(run.best_sel)
        for k in rng.sample(range(sp.K), min(kick, sp.K)):
            s[k] = rng.choice([o for o in sp.opts[k] + [-1] if o != s[k]])
        descend(run, tuple(s))
        stale = stale + 1 if run.used == before else 0


def pair_moves(space: Space, sel: tuple[int, ...]) -> list[tuple[int, ...]]:
    out = []
    for k1 in range(space.K):
        n1 = space.neighbors(sel, k1)
        for k2 in range(k1 + 1, space.K):
            for s1 in n1:
                for o in space.opts[k2] + [-1]:
                    if o != sel[k2]:
                        s = list(s1)
                        s[k2] = o
                        out.append(tuple(s))
    return out


def m1(run: Run, *, prior: Prior, **_: Any) -> None:
    sp = run.space
    cur, _ = descend(run, sp.empty())
    model = Model(sp, prior)
    while not run.exhausted:
        if run.base_damage is None:
            return
        cand = [s for s in pair_moves(sp, run.best_sel) if s not in run.seen and sp.ok(s)]
        if not cand:
            return
        sels, y = _y(run)
        model.fit(sels, y)
        h, W = model.quadratic(model.mean)
        pred = surrogate(h, W, sp.onehot(cand))
        order = np.argsort(-pred, kind="stable")[:BATCH]
        best0 = run.best
        run.evaluate([cand[i] for i in order])
        if _better(run.best, best0):
            descend(run, run.best_sel)


def m2(run: Run, *, prior: Prior, seed: int = 0, batch: int = BATCH, temp: float = 1.0, **_: Any) -> None:
    sp = run.space
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    empty = sp.empty()
    init = [empty]
    for i in range(sp.nv):
        s = list(empty)
        s[sp.key_of[i]] = i
        init.append(tuple(s))
    run.evaluate(init)
    if run.base_damage is None:
        return
    model = Model(sp, prior)
    while not run.exhausted:
        sels, y = _y(run)
        model.fit(sels, y)
        top = [s for s, _ in sorted(run.history, key=lambda x: -x[1])[:3]]
        props: list[tuple[int, ...]] = []
        for _ in range(batch):
            w = model.mean + temp * (model.sample(nrng) - model.mean)  # temp < 1: 사후 표본의 폭을 줄인다
            h, W = model.quadratic(w)
            for _v, s in maximize(sp, h, W, top, rng):
                if s not in run.seen and s not in props and sp.ok(s):
                    props.append(s)
                    break
        if not props:  # 표본의 최선을 모두 이미 봤다 — 최선에서 키 1~3개를 무작위로 바꾼 것 하나
            for t in range(300):
                s = list(run.best_sel)
                for k in rng.sample(range(sp.K), min(1 + t // 100, sp.K)):
                    s[k] = rng.choice([o for o in sp.opts[k] + [-1] if o != s[k]])
                s = tuple(s)
                if s not in run.seen and sp.ok(s):
                    props.append(s)
                    break
            if not props:
                return
        run.evaluate(props)


METHODS: dict[str, Callable[..., None]] = {"M0": m0, "M1": m1, "M2": m2, "M3": m3}


def parse_method(spec: str) -> tuple[str, dict[str, Any]]:
    """`M0` · `M1:attr` · `M2:flat` · `M2:attr:t0.3` · `M3:k4` → (기법, 설정)."""
    name, _, opt = spec.partition(":")
    if name not in METHODS:
        raise ValueError(f"기법은 {list(METHODS)} 중 하나: {spec!r}")
    kw: dict[str, Any] = {}
    if name in ("M1", "M2"):
        parts = (opt or "attr").split(":")
        kw["prior_kind"] = parts[0]
        for x in parts[1:]:
            if name == "M2" and x.startswith("t"):
                kw["temp"] = float(x[1:])
            else:
                raise ValueError(f"모르는 설정 {x!r}: {spec!r}")
    if name == "M3":
        kw["kick"] = int(opt[1:]) if opt.startswith("k") else 2
    return name, kw


def job_seed(comp_id: str, spec: str) -> int:
    return int(hashlib.sha256(f"{comp_id}|{spec}".encode()).hexdigest()[:8], 16)


def run_job(comp: Mapping[str, Any], spec: str, ev: Any, *, budget: int, out: Path | None,
            priors: Mapping[str, Prior] | None = None, lookup: Mapping[str, int] | None = None,
            space: Space | None = None) -> dict[str, Any]:
    name, kw = parse_method(spec)
    space = space or Space(comp["squad"])
    run = Run(comp, space, ev, method=spec, budget=budget, out=out, lookup=lookup)
    t0 = time.time()
    try:
        if "prior_kind" in kw:
            kw["prior"] = (priors or {})[kw.pop("prior_kind")]
        METHODS[name](run, seed=job_seed(comp["id"], spec), **kw)
    finally:
        run.close()
    return {"comp_id": comp["id"], "method": spec, "evals": run.used, "lookups": run.lookups,
            "best_damage": run.best, "base_damage": run.base_damage,
            "best_variants": list(space.labels(run.best_sel)), "exhausted": run.exhausted,
            "seconds": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- 사전값 학습(EM)

def load_points(paths: Sequence[Path], comp_ids: set[str] | None = None) -> dict[str, dict[tuple[str, ...], int]]:
    """기록 파일들(실험 6 Record · 실험 7 줄 모두) → 조합 id → {선택 label tuple: 딜}."""
    out: dict[str, dict[tuple[str, ...], int]] = {}
    for p in paths:
        op = gzip.open if str(p).endswith(".gz") else open
        with op(p, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("total_damage") is None:
                    continue
                if r.get("condition") in ("auto", "search_from_auto", "fixed_layer"):
                    continue  # 바탕이 기본 레이어가 아닌 기록
                cid = r["comp_id"]
                if comp_ids is not None and cid not in comp_ids:
                    continue
                out.setdefault(cid, {})[tuple(sorted(r["variants"]))] = r["total_damage"]
    return out


def learn_prior(kind: str, data: Mapping[str, tuple[Space, list[tuple[int, ...]], np.ndarray]],
                iters: int = 15, init_var: tuple[float, float] = (1e-3, 1e-4), init_sigma2: float = 1e-4,
                log: Callable[[str], None] | None = None) -> Prior:
    """조합별 (공간, 선택, y)에서 묶음별 평균·분산과 잡음 분산을 EM으로 추정한다."""
    groups: dict[str, tuple[float, float]] = {}
    fallback = {"main": (0.0, init_var[0]), "pair": (0.0, init_var[1])}
    prior = Prior(kind, groups, init_sigma2, fallback)
    for it in range(iters):
        acc: dict[str, list[tuple[float, float]]] = {}
        res_sum, n_sum = 0.0, 0
        for cid, (sp, sels, y) in data.items():
            m = Model(sp, prior)
            m.fit(sels, y)
            V = np.linalg.solve(m.L, m.Phi * m.s0)  # n×d
            post_var = np.maximum(m.s0 - (V * V).sum(axis=0), 0.0)
            for g, mu, var in zip(m.main_groups + m.pair_groups, m.mean, post_var):
                acc.setdefault(g, []).append((float(mu), float(var)))
            r = y - m.Phi @ m.mean
            Linv = np.linalg.inv(m.L)
            trKinv = float((Linv * Linv).sum())
            n = len(y)
            res_sum += float(r @ r) + n * m.sigma2 - m.sigma2 ** 2 * trKinv
            n_sum += n
        new: dict[str, tuple[float, float]] = {}
        for g, xs in acc.items():
            mus = np.array([a for a, _ in xs])
            vs = np.array([b for _, b in xs])
            mu = 0.0 if kind == "flat" else float(mus.mean())
            new[g] = (mu, max(float(((mus - mu) ** 2 + vs).mean()), VAR_FLOOR))
        sigma2 = max(res_sum / max(n_sum, 1), VAR_FLOOR)
        main_vals = [v for g, v in new.items() if not _is_pair_group(g)]
        pair_vals = [v for g, v in new.items() if _is_pair_group(g)]
        fallback = {"main": (0.0, float(np.median([s for _, s in main_vals])) if main_vals else init_var[0]),
                    "pair": (0.0, float(np.median([s for _, s in pair_vals])) if pair_vals else init_var[1])}
        prior = Prior(kind, new, sigma2, fallback)
        if log:
            log(f"EM {kind} {it + 1}/{iters}: sigma {math.sqrt(sigma2):.4f} · 묶음 {len(new)}")
    return prior


def _is_pair_group(g: str) -> bool:
    return g == "pair" or g.endswith("|same") or g.endswith("|other")


def prior_data(points: Mapping[str, Mapping[tuple[str, ...], int]], comps: Mapping[str, Mapping[str, Any]],
               max_points: int | None = None) -> dict[str, tuple[Space, list[tuple[int, ...]], np.ndarray]]:
    """조합마다 (공간, 선택, y). `max_points`보다 많으면 기본 레이어를 남기고 시드 고정으로 무작위로 줄인다
    (EM 비용이 점 수의 제곱 · 세제곱으로 는다)."""
    data = {}
    for cid, pts in sorted(points.items()):
        if cid not in comps:
            continue
        sp = Space(comps[cid]["squad"])
        base = pts.get(())
        if base is None:
            continue
        sels, ys = [], []
        items = sorted(pts.items())
        if max_points is not None and len(items) > max_points:
            rest = [x for x in items if x[0]]
            items = [((), base)] + random.Random(f"prior|{cid}").sample(rest, max_points - 1)
        for lb, d in items:
            s = sp.from_labels(lb)
            if s is not None:
                sels.append(s)
                ys.append(math.log(d / base))
        data[cid] = (sp, sels, np.array(ys))
    return data


# ---------------------------------------------------------------- CLI

def load_comps(which: str) -> list[dict[str, Any]]:
    if which == "dev":
        return common.load_compositions(DEV_COMPS)
    if which == "val":
        return common.load_compositions(VAL_COMPS)
    raise ValueError(which)


def exp6_lookup() -> dict[str, int]:
    """실험 6 기록의 요청 → 총딜. 개발 실행에서 같은 요청의 시뮬을 아낀다(검증 실행에는 쓰지 않는다)."""
    out = {}
    with gzip.open(EXP6_RECORDS, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("total_damage") is not None:
                out[json.dumps(r["request"], sort_keys=True, ensure_ascii=False)] = r["total_damage"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prior", help="개발 기록에서 사전값 학습 → JSON")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--exclude", default="", help="뺄 개발 조합 id 콤마 목록(교차 적합)")
    p.add_argument("--extra", type=Path, nargs="*", default=[], help="더 넣을 실험 7 실행 폴더(*.jsonl)")
    p.add_argument("--iters", type=int, default=15)
    p.add_argument("--max-points", type=int, default=1500, help="조합당 점 상한(넘으면 무작위로 줄인다)")
    r = sub.add_parser("run", help="조합 × 기법 실행")
    r.add_argument("--set", choices=("dev", "val"), required=True)
    r.add_argument("--comps", default="all")
    r.add_argument("--methods", required=True, help="콤마 목록: M0,M1:attr,M2:attr,M2:flat,M3:k2,M3:k4")
    r.add_argument("--budget", type=int, default=800)
    r.add_argument("--prior", type=Path, nargs="*", default=[], help="prior JSON (attr · flat), 조합별이면 --prior-map")
    r.add_argument("--prior-map", type=Path, help="조합 id → {attr: 경로, flat: 경로} JSON")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--threads", type=int, default=4)
    r.add_argument("--lookup-exp6", action="store_true", help="실험 6 기록 재사용(개발 전용)")
    args = ap.parse_args(argv)

    if args.cmd == "prior":
        comps = {c["id"]: c for c in load_comps("dev")}
        excl = {x for x in args.exclude.split(",") if x}
        paths = [EXP6_RECORDS] + [f for d in args.extra for f in sorted(d.glob("*.jsonl"))]
        pts = load_points(paths, set(comps) - excl)
        data = prior_data(pts, comps, args.max_points)
        print(f"조합 {len(data)}개 · 점 {sum(len(v[1]) for v in data.values())}개", file=sys.stderr)
        out = {}
        for kind in ("attr", "flat"):
            out[kind] = learn_prior(kind, data, iters=args.iters, log=lambda s: print(s, file=sys.stderr)).to_json()
        out["meta"] = {"comps": sorted(data), "exclude": sorted(excl), "extra": [str(x) for x in args.extra]}
        args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return 0

    comps = load_comps(args.set)
    if args.comps != "all":
        want = args.comps.split(",")
        comps = [c for c in comps if c["id"] in want]
    specs = [s for s in args.methods.split(",") if s]
    for s in specs:
        parse_method(s)
    prior_by_comp: dict[str, dict[str, Prior]] = {}
    if args.prior_map:
        pm = json.loads(args.prior_map.read_text(encoding="utf-8"))
        cache: dict[str, dict] = {}
        for cid, path in pm.items():
            d = cache.setdefault(path, json.loads(Path(path).read_text(encoding="utf-8")))
            prior_by_comp[cid] = {k: Prior.from_json(d[k]) for k in ("attr", "flat")}
    elif args.prior:
        d = json.loads(args.prior[0].read_text(encoding="utf-8"))
        shared = {k: Prior.from_json(d[k]) for k in ("attr", "flat")}
        prior_by_comp = {c["id"]: shared for c in comps}
    lookup = exp6_lookup() if args.lookup_exp6 else None
    args.out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for c in comps:
        for s in specs:
            stem = f"{c['id']}__{s.replace(':', '_')}"
            if (args.out / f"{stem}.done").exists():
                continue
            jobs.append((c, s, stem))
    spaces: dict[str, Space] = {}
    lock = threading.Lock()

    def space_of(c: Mapping[str, Any]) -> Space:
        with lock:
            if c["id"] not in spaces:
                spaces[c["id"]] = Space(c["squad"])
            return spaces[c["id"]]

    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()

    def work(job):
        c, s, stem = job
        summ = run_job(c, s, ev, budget=args.budget, out=args.out / f"{stem}.jsonl",
                       priors=prior_by_comp.get(c["id"]), lookup=lookup, space=space_of(c))
        (args.out / f"{stem}.done").write_text(json.dumps(summ, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({**summ, "t": round(time.time() - t0), "sims": ev.sim_count}, ensure_ascii=False), flush=True)
        return summ

    with ev:
        with ThreadPoolExecutor(max_workers=args.threads) as pool:
            for f in [pool.submit(work, j) for j in jobs]:
                f.result()
    print(f"작업 {len(jobs)}개 · 시뮬 {ev.sim_count}회 · 캐시 {ev.cache_hits}회 · {time.time() - t0:.0f}초 · "
          f"평가기 {ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
