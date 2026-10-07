"""사전 실험 2·3 분석 — 점수 분포와 학습 가능성.

입력: results.jsonl (run.py), pool.json · ranker_squads.json (prepare.py)
사용: python analyze.py [results.jsonl]  → 표준출력에 마크다운 표

딜 단위는 억(1e8). 「구성」은 순서를 무시한 5명, 「스쿼드」는 배치 순서까지 포함한 것.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
E8 = 1e8
FOLDS = 5
SEED = 20261007


def load(path: Path):
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]
    df = pd.DataFrame(rows)
    bad = df["error"].notna().sum()
    df = df[df["error"].isna()].copy()
    df["dmg"] = df["total_damage"] / E8
    df["comp"] = df["squad"].map(frozenset)
    pool = json.loads((HERE / "pool.json").read_text(encoding="utf-8"))["pool"]
    rk = json.loads((HERE / "ranker_squads.json").read_text(encoding="utf-8"))
    return df, int(bad), pool, rk


def template(comp, pool) -> str:
    c = defaultdict(int)
    for n in comp:
        c[pool[n]["burst"]] += 1
    return f"{c['1']}-{c['2']}-{c['3']}" + ("+A" if c["A"] else "")


def q(s: pd.Series) -> dict:
    return {"n": len(s), "최소": s.min(), "p10": s.quantile(.1), "중앙": s.median(), "p90": s.quantile(.9),
            "p99": s.quantile(.99), "최대": s.max()}


def table(rows: list[dict], fmt: str = "{:.1f}") -> str:
    d = pd.DataFrame(rows)
    return d.to_markdown(index=False, floatfmt=fmt[2:-1])


def spearman(a, b) -> float:
    """순위 상관 (scipy 없이: 순위의 피어슨 상관)."""
    a, b = pd.Series(np.asarray(a, float)).rank(), pd.Series(np.asarray(b, float)).rank()
    return float(np.corrcoef(a, b)[0, 1])


# ── 실험 2 ─────────────────────────────────────────────────────────────

def distribution(df, pool, rk) -> None:
    rnd = df[df["group"] == "random"]
    rkr = df[df["group"] == "ranker"]
    best_rk = rkr.groupby("comp")["dmg"].max()  # 구성마다 랭커가 둔 순서 중 최선
    print("## 실험 2 — 점수 분포 (억)\n")
    print(table([{"묶음": "무작위 스쿼드", **q(rnd["dmg"])},
                 {"묶음": "랭커 스쿼드(순서 포함)", **q(rkr["dmg"])},
                 {"묶음": "랭커 구성(순서 중 최선)", **q(best_rk)}]))

    top = rnd["dmg"].sort_values(ascending=False).to_numpy()
    print("\n### 상위권의 뾰족함 (무작위)\n")
    rows = []
    for k in (1, 5, 10, 25, 50, 150):
        if k <= len(top):
            rows.append({"상위 k": str(k), "k번째 딜": top[k - 1], "1위 대비": top[k - 1] / top[0],
                         "중앙값 대비": top[k - 1] / np.median(top)})
    print(table(rows, "{:.2f}"))

    print("\n### 유효 후보 수 — 기준 딜의 x% 이상인 무작위 스쿼드\n")
    refs = {"무작위 1위": top[0], "랭커 구성 1위": best_rk.max(), "랭커 구성 5위": best_rk.nlargest(5).iloc[-1]}
    rows = []
    for name, ref in refs.items():
        r = {"기준": f"{name} ({ref:.1f})"}
        for pct in (0.8, 0.9, 0.95, 1.0):
            r[f"≥{int(pct * 100)}%"] = int((rnd["dmg"] >= pct * ref).sum())
        rows.append(r)
    print(table(rows))

    print("\n### 랭커 구성은 무작위 분포의 어디쯤인가\n")
    pct = best_rk.map(lambda v: (rnd["dmg"] < v).mean())
    use = {frozenset(s["squad"]): 0 for s in rk["squads"]}
    for s in rk["squads"]:
        use[frozenset(s["squad"])] += s["count"]
    w = best_rk.index.map(use)
    print(table([{"랭커 구성": str(len(best_rk)), "무작위 대비 백분위 중앙": pct.median(),
                  "사용 빈도 가중 평균": float(np.average(pct, weights=w)),
                  "무작위 상위 1% 이상": int((best_rk >= np.quantile(top, .99)).sum()),
                  "무작위 1위 이상": int((best_rk >= top[0]).sum())}], "{:.2f}"))
    top_used = sorted(use.items(), key=lambda kv: -kv[1])[:10]
    rows = [{"구성(빈도순)": " · ".join(sorted(c)), "덱 수": n, "딜": best_rk[c], "무작위 백분위": pct[c]}
            for c, n in top_used]
    print()
    print(table(rows, "{:.2f}"))

    print("\n### 버스트 틀별 (무작위)\n")
    rnd = rnd.assign(t=rnd["comp"].map(lambda c: template(c, pool)))
    rows = [{"틀": t, "n": len(g), "중앙": g["dmg"].median(), "p90": g["dmg"].quantile(.9), "최대": g["dmg"].max(),
             "상위 50 중": int(g.index.isin(rnd["dmg"].nlargest(50).index).sum())}
            for t, g in rnd.groupby("t")]
    print(table(sorted(rows, key=lambda r: -r["n"])))

    print("\n### 니케별 기여 — 무작위 스쿼드에서 그 니케가 있을 때의 평균 딜 (상·하위 10)\n")
    rows = []
    for n in pool:
        has = rnd["comp"].map(lambda c: n in c)
        if has.sum() >= 10:
            rows.append({"니케": n, "단계": pool[n]["burst"], "등장": int(has.sum()),
                         "있을 때 평균": rnd.loc[has, "dmg"].mean(), "없을 때 평균": rnd.loc[~has, "dmg"].mean(),
                         "S40 랭커 사용률": pool[n]["s40_use"]})
    d = pd.DataFrame(rows).assign(차=lambda d: d["있을 때 평균"] - d["없을 때 평균"]).sort_values("차", ascending=False)
    print(pd.concat([d.head(10), d.tail(10)]).to_markdown(index=False, floatfmt=".2f"))
    # 랭커 사용률과 니케 단위 기여의 순위 상관
    print(f"\n니케 기여(차) ↔ S40 랭커 사용률 Spearman = {spearman(d['차'], d['S40 랭커 사용률']):.2f}"
          f" (니케 {len(d)}명)")


def order_effect(df, pool) -> None:
    print("\n## 배치 순서의 영향\n")
    o = df[df["group"] == "order"]
    rows = []
    for comp, g in o.groupby("comp"):
        if len(g) < 2:
            continue
        rows.append({"orders": len(g), "spread": g["dmg"].max() / g["dmg"].min() - 1,
                     "random_gap": 1 - g["dmg"].mean() / g["dmg"].max(), "best": g["dmg"].max(),
                     "t": template(comp, pool)})
    d = pd.DataFrame(rows)
    if d.empty:
        print("(순서 데이터 없음)")
        return
    print(table([{"구성": len(d), "순서 수 평균": d["orders"].mean(),
                  "최선/최악 −1 중앙": d["spread"].median(), "p90": d["spread"].quantile(.9),
                  "최대": d["spread"].max(),
                  "무작위 순서의 기대 손실(중앙)": d["random_gap"].median(),
                  "기대 손실 p90": d["random_gap"].quantile(.9)}], "{:.3f}"))
    print()
    print(d.groupby("t").agg(n=("spread", "size"), spread_중앙=("spread", "median"),
                             spread_최대=("spread", "max")).reset_index().to_markdown(index=False, floatfmt=".3f"))
    # 순서 차이 vs 구성 차이: 순서 간 분산이 구성 간 분산에서 차지하는 몫
    var_within = o.groupby("comp")["dmg"].var().mean()
    var_between = o.groupby("comp")["dmg"].mean().var()
    print(f"\n구성 {len(d)}개 기준 분산: 순서 안 {var_within:.2f} · 구성 사이 {var_between:.2f}"
          f" → 순서 몫 {var_within / (var_within + var_between):.1%}")
    # 상위권에서도 순서가 순위를 바꾸나
    best = o.groupby("comp")["dmg"].max()
    first = o.drop_duplicates("comp").set_index("comp")["dmg"]  # 무작위로 뽑힌 원래 순서
    print(f"원래(무작위) 순서 ↔ 최선 순서의 구성 순위 Spearman = "
          f"{spearman(first.reindex(best.index), best):.3f}")
    r = df[df["group"] == "ranker"].groupby("comp")["dmg"]
    rs = pd.DataFrame({"n": r.size(), "spread": r.max() / r.min() - 1})
    rs = rs[rs["n"] > 1]
    print(f"랭커가 같은 구성을 여러 순서로 둔 경우 {len(rs)}개: 최선/최악 −1 중앙 {rs['spread'].median():.3f}, "
          f"최대 {rs['spread'].max():.3f}")


def ranker_baseline(df, rk) -> None:
    print("\n## 랭커 구성 기준선 — 랭커마다 실제 5덱을 같은 육성·S40으로 시뮬한 합 (억)\n")
    dmg = df[df["group"] == "ranker"].assign(k=lambda d: d["squad"].map(tuple)).groupby("k")["dmg"].first()
    sq = [tuple(s["squad"]) for s in rk["squads"]]
    tot = [sum(dmg[sq[i]] for i in p["squads"]) for p in rk["players"] if all(sq[i] in dmg for i in p["squads"])]
    tot = pd.Series(tot)
    print(table([{"랭커": len(tot), **{k: v for k, v in q(tot).items() if k != "n"}}]))
    print(f"\n최고 랭커 5덱 시뮬 합 = **{tot.max():.1f}억** (실험 4의 랭커 구성 기준선)")


# ── 실험 3 ─────────────────────────────────────────────────────────────

def features(comps, names, pairs):
    ni = {n: i for i, n in enumerate(names)}
    pi = {p: i for i, p in enumerate(pairs)}
    U = np.zeros((len(comps), len(names)))
    P = np.zeros((len(comps), len(pairs)))
    for r, c in enumerate(comps):
        for n in c:
            U[r, ni[n]] = 1
        for p in combinations(sorted(c), 2):
            if p in pi:
                P[r, pi[p]] = 1
    return U, P


def ridge(X, y, lam_u, lam_p, nu):
    """니케 항과 짝 항의 벌점을 따로 준 릿지. 절편은 벌점 없음."""
    X1 = np.hstack([np.ones((len(X), 1)), X])
    pen = np.r_[0.0, np.full(nu, lam_u), np.full(X.shape[1] - nu, lam_p)]
    return np.linalg.solve(X1.T @ X1 + np.diag(pen), X1.T @ y)


def predict(w, X):
    return w[0] + X @ w[1:]


def learnability(df, pool) -> None:
    print("\n## 실험 3 — 학습 가능성 (무작위 스쿼드로 학습, 처음 보는 구성의 순위를 맞히나)\n")
    rnd = df[df["group"] == "random"].reset_index(drop=True)
    rkr = df[df["group"] == "ranker"].groupby("comp")["dmg"].max()
    names = sorted(pool)
    pairs = sorted({p for c in rnd["comp"] for p in combinations(sorted(c), 2)})
    U, P = features(rnd["comp"], names, pairs)
    y = rnd["dmg"].to_numpy()
    rng = np.random.default_rng(SEED)
    fold = rng.permutation(len(y)) % FOLDS

    models = {
        "니케만 (λ=1)": (U, 1.0, None),
        "니케만 (λ=10)": (U, 10.0, None),
        "니케+짝 (λ니케=1, λ짝=3)": (np.hstack([U, P]), 1.0, 3.0),
        "니케+짝 (λ니케=1, λ짝=10)": (np.hstack([U, P]), 1.0, 10.0),
        "니케+짝 (λ니케=1, λ짝=30)": (np.hstack([U, P]), 1.0, 30.0),
    }
    rows, best = [], None
    for name, (X, lu, lp) in models.items():
        pred = np.zeros_like(y)
        for f in range(FOLDS):
            tr, te = fold != f, fold == f
            w = ridge(X[tr], y[tr], lu, lp if lp is not None else lu, len(names))
            pred[te] = predict(w, X[te])
        top = y >= np.quantile(y, .9)
        ptop = pred >= np.quantile(pred, .9)
        rows.append({"모델": name, "Spearman": spearman(pred, y),
                     "상위10% 안 Spearman": spearman(pred[top], y[top]),
                     "상위10% 적중": (top & ptop).sum() / top.sum(),
                     "RMSE/표준편차": np.sqrt(np.mean((pred - y) ** 2)) / y.std()})
        if best is None or rows[-1]["Spearman"] > best[1]:
            best = (name, rows[-1]["Spearman"], X, lu, lp)
    print(f"{FOLDS}겹 교차검증, 무작위 스쿼드 {len(y)}개\n")
    print(table(rows, "{:.3f}"))

    # 분포 밖: 무작위로만 학습해서 랭커 구성(대부분 상위권)의 순위를 맞히나
    name, _, X, lu, lp = best
    w = ridge(X, y, lu, lp if lp is not None else lu, len(names))
    Ur, Pr = features(list(rkr.index), names, pairs)
    Xr = Ur if X.shape[1] == len(names) else np.hstack([Ur, Pr])
    pr = predict(w, Xr)
    print(f"\n분포 밖 — 무작위 전체로 학습한 「{name}」로 랭커 구성 {len(rkr)}개 예측: "
          f"Spearman {spearman(pr, rkr.to_numpy()):.3f}, "
          f"예측 상위 10개 중 실제 상위 10개 {len(set(np.argsort(-pr)[:10]) & set(np.argsort(-rkr.to_numpy())[:10]))}개")
    # 학습 곡선
    if len(y) < 600:
        return
    print("\n학습 곡선 (니케+짝 λ짝=10, 남겨 둔 300개로 평가):\n")
    Xf = np.hstack([U, P])
    perm = rng.permutation(len(y))
    test, train_all = perm[:300], perm[300:]
    rows = []
    for n in (50, 100, 200, 400, 800, len(train_all)):
        tr = train_all[:n]
        rows.append({"학습 수": str(n),
                     "니케만": spearman(predict(ridge(U[tr], y[tr], 1.0, 1.0, len(names)), U[test]), y[test]),
                     "니케+짝": spearman(predict(ridge(Xf[tr], y[tr], 1.0, 10.0, len(names)), Xf[test]), y[test])})
    print(table(rows, "{:.3f}"))


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "results.jsonl"
    df, bad, pool, rk = load(path)
    print(f"결과 {len(df)}줄 (오류 {bad}줄)\n")
    distribution(df, pool, rk)
    order_effect(df, pool)
    ranker_baseline(df, rk)
    learnability(df, pool)


if __name__ == "__main__":
    main()
