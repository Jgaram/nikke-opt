"""실험 39 판 a — README §판 a. 작업 세션 A가 채운다(이 파일 · dev/a/ 만 소유).

인터페이스(바꾸지 않는다): local_round(sess, n, lineage, fitf) -> list[tuple]
  실험 10 `run10.local_round`와 같은 인자 · 반환. 라운드 하나(n평가)에서 새로 계산할 구성(같은 단계 순서 스쿼드 튜플)을 고른다.
  sess.book.best = 지금까지 평가한 구성 → (값, 순서), sess.pack() = 지금 최선 5덱, sess.acct.owned = 보유 니케(→ burst 단계),
  lineage = 킥 뒤 계보(없으면 None), fitf(book, names) → 대리 모델 score(frozenset) -> 예측 값.
PARAMS: 기록용 설정 값(part_*.json의 params에 남는다).

설계(2026-11-03, 세션 A 하위 에이전트) — ⓑ의 부모를 「값 상위 40」에서 「5덱의 칸 대안」으로 넓힌다.
  한 라운드 n = ⓐ 5덱 고치기 60%(base 70%, S4.pack_moves 그대로) + ⓑ2 칸 대안 이웃 30% + ⓑ1 값 상위 40 이웃 10%(base ⓑ 30%).
  ⓑ2: 5덱(킥 뒤엔 계보 5덱)의 칸 i마다, 나머지 4덱과 니케가 겹치지 않는 평가한 구성(= 그 칸에 들어갈 수 있는 덱 — 최선 5덱이
  안 쓰는 니케로 짠 덱을 포함) 값 상위 8개를 부모로, 같은 단계 한 명 교체(들어오는 니케도 나머지 4덱 밖) 이웃을 만든다.
  이득 = 예측(이웃) − 예측(칸 i 덱)(pack_moves와 같은 기준) — 부모마다 상위 8개, 모아서 이득 순. 약한 칸(4 · 5번째 덱)의
  대안이 앞에 온다. ⓑ2로 고른 구성은 ⓐ처럼 계보에 넣는다.
  버린 안: R9.pack_vals(avoid=[최선 5덱]) 대안 5덱 — 재생(실험 36 S36 s0 기록, 3,000~11,000평가)에서 대안 4묶음 값이 최선과
  거의 같고(255.9 대 257.1) 놓친 랭커 덱의 부모를 하나도 담지 않았으며, 묶기 한 번에 8~30초라 라운드마다 쓰기 어렵다.
재생으로 본 것(시뮬 0): 놓친 큰 랭커 덱(S36 99.2억 · S42 96.1억 · S37 59.7억)은 대리 모델 예측이 실제의 45~58%이고,
  부모 안 예측 순위가 30~170위라 부모를 넓혀도 그 덱 자체는 거의 뽑히지 않는다. 개선은 그 덱보다 「약한 칸을 채울 중간 덱」을
  더 계산하는 쪽에서 기대했다.
고른 설정: PARAMS(v1). 개발 예산(5만)으로 12,500평가 4번만 돌 수 있어 설정 비교는 하지 않았다.

개발 결과(S33~S42, 시드 0, 예산 12,500, 평가기 nikke-calc-rs 8bc51a2; base = 실험 36 B_s0 기록을 run39.summarize로 요약):

| 시즌 | base pack | a pack | a/base | G base → a | visit base → a | 킥 base → a |
|---|---|---|---|---|---|---|
| S36 (G 큼) | 257.1 | 277.8 | +8.02% | +10.4% → +6.5% | 0.9% → 20.8% | 13 → 22 |
| S42 (G 큼) | 295.1 | 295.2 | +0.03% | +5.7% → +6.4% | 27.3% → 27.9% | 13 → 22 |
| S39 (G 작음) | 293.8 | 296.0 | +0.76% | +0.8% → +0.0% | 29.5% → 21.5% | 13 → 22 |
| S34 (G 작음) | 241.5 | 238.9 | −1.05% | +0.1% → +0.8% | 60.7% → 30.6% | 14 → 21 |

  참고 시드 잡음(base s1 ÷ s0 − 1): S36 +1.41% · S42 −3.43% · S39 +0.92% · S34 −1.19%. S37은 예산 때문에 못 돌렸다.
  S36의 a 5덱은 96.0 + 50.7 · 44.5 · 43.7 · 42.9(base 101.6 + 약한 칸)로 랭커 묶음 모양(한 덱 조금 낮고 나머지 고르게)에 가깝다.
  킥이 모든 시즌에서 21~22번으로 늘었다(계보 정체가 잦아짐 — ⓐ 몫 감소 · ⓑ2를 계보에 넣은 영향으로 보이나 따로 재지 않음).
  개발 시뮬 합 44,690(smoke 600 + 12,500 실행 4번).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _run31():
    m = sys.modules.get("run31")
    if m is None:
        p = Path(__file__).resolve().parent.parent / "31_recent_seasons" / "run31.py"
        spec = importlib.util.spec_from_file_location("run31", p)
        m = importlib.util.module_from_spec(spec)
        sys.modules["run31"] = m
        spec.loader.exec_module(m)
    return m


_R31 = _run31()
R10, R9 = _R31.R10, _R31.R9
S4 = R10.S4

PARAMS: dict = {
    "pack_share": 0.6,      # ⓐ 최선 5덱(킥 뒤엔 계보 5덱) 고치기 — base 0.7
    "top_share": 0.1,       # ⓑ1 값 상위 PARENTS(40) 구성의 이웃(base ⓑ와 같은 방식) — base 0.3
    "slot_k": 8,            # ⓑ2 칸마다 대안 부모 수: 나머지 4덱과 겹치지 않는 평가한 구성 값 상위
    "per_parent": 8,        # ⓑ2 부모마다 이웃 수(예상 칸 이득 상위)
    "slot_lineage": True,   # ⓑ2로 고른 구성을 킥 뒤 계보에 넣는다(ⓐ처럼 묶음 고치기라서)
}


def slot_moves(decks, book, owned, score, slot_k, per_parent):
    """ⓑ2 묶음 대안: 5덱의 칸 i마다, 나머지 4덱과 니케가 겹치지 않는 평가한 구성(지금 덱 제외) 값 상위 slot_k개를 부모로
    같은 단계 한 명 교체 이웃(들어오는 니케도 나머지 4덱 밖)을 만든다. 이득 = 예측(이웃) − 예측(칸 i 덱) — 칸을 바꿨을 때의
    묶음 예상 이득(S4.pack_moves와 같은 기준). 부모마다 이득 상위 per_parent개를 모아 이득 순으로 돌려준다."""
    if len(decks) < 5:
        return []
    order = sorted(book.items(), key=lambda kv: (-kv[1][0], kv[1][1]))
    stage = {n: v["burst"] for n, v in owned.items()}
    by_stage: dict[str, list[str]] = {}
    for m in sorted(owned):
        by_stage.setdefault(stage[m], []).append(m)
    out = []
    for i, d in enumerate(decks):
        others = {x for j, e in enumerate(decks) if j != i for x in e}
        di = frozenset(d)
        base_pred = score(di)
        parents = []
        for c, (v, sq) in order:
            if c == di or not others.isdisjoint(c):
                continue
            parents.append(sq)
            if len(parents) >= slot_k:
                break
        for sq in parents:
            lst = []
            for j, x in enumerate(sq):
                cur = [y for k, y in enumerate(sq) if k != j]
                opts = [m for m in by_stage[stage[x]] if m not in others and m not in sq
                        and frozenset(cur + [m]) not in book]
                if not opts:
                    continue
                for p, m in zip(R10.add_scores(score, cur, opts), opts):
                    lst.append((p - base_pred, sq[:j] + (m,) + sq[j + 1:]))
            lst.sort(key=lambda t: (-t[0], t[1]))
            out += lst[:per_parent]
    out.sort(key=lambda t: (-t[0], t[1]))
    return out


def local_round(sess, n, lineage, fitf):
    """base(실험 10 `local_round`)에서 ⓑ를 둘로 나눈다: ⓐ 5덱 고치기(pack_share) → ⓑ2 칸 대안 부모의 이웃(남은 몫 중
    top_share를 뺀 만큼) → ⓑ1 값 상위 40 부모의 이웃(남은 전부). 5덱 = 계보가 있으면 계보 5덱, 없으면 전체 최선 5덱."""
    acct = sess.acct
    book = sess.book.best
    score = fitf(sess.book, acct.names)
    pick: list[tuple] = []
    seen: set[frozenset] = set()
    take = R9._take_factory(sess, pick, seen, n)
    share = int(n * PARAMS["pack_share"])
    if lineage is None:
        decks = [sq for _, sq in sess.pack()[1]]
    else:
        decks = [sq for _, sq in R9.pack_vals({c: v for c, v in book.items() if c in lineage})[1]]
    got = 0
    for _, new in S4.pack_moves(decks, acct.owned, score):
        if got >= share:
            break
        got += take(new)
    mark = len(pick)
    slot_cap = n - int(n * PARAMS["top_share"])
    for _, nb in slot_moves(decks, book, acct.owned, score, PARAMS["slot_k"], PARAMS["per_parent"]):
        if len(pick) >= slot_cap:
            break
        take([nb])
    if lineage is not None:
        upto = len(pick) if PARAMS["slot_lineage"] else mark
        lineage.update(frozenset(s) for s in pick[:upto])
    parents = sorted(book.values(), reverse=True)[:R9.PARENTS]
    cands = []
    for _, sq in parents:
        lst = [(score(frozenset(nb)), nb) for nb in S4.neighbors(sq, acct.owned) if frozenset(nb) not in book]
        cands += sorted(lst, reverse=True)[:R9.PER_PARENT]
    for _, nb in sorted(cands, reverse=True):
        if len(pick) >= n:
            break
        take([nb])
    return pick
