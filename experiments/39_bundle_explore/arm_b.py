"""실험 39 판 b — 탐험 몫. README §판 b. 작업 세션 B가 채운다(이 파일 · dev/b/ 만 소유).

인터페이스(바꾸지 않는다): local_round(sess, n, lineage, fitf) -> list[tuple]
  실험 10 `run10.local_round`와 같은 인자 · 반환. 라운드 하나(n평가)에서 새로 계산할 구성(같은 단계 순서 스쿼드 튜플)을 고른다.
  sess.book.best = 지금까지 평가한 구성 → (값, 순서), sess.pack() = 지금 최선 5덱, sess.acct.owned = 보유 니케(→ burst 단계),
  lineage = 킥 뒤 계보(없으면 None), fitf(book, names) → 대리 모델 score(frozenset) -> 예측 값.
PARAMS: 기록용 설정 값(part_*.json의 params에 남는다).

설계(개발 S33~S42에서 정함)
- 라운드 n = ⓐ 5덱 고치기 · ⓑ 상위 40 이웃(base와 같은 방식, (1 − 0.2)·n 안에서 70 : 30 → n=100이면 56 · 24) + 탐험 20.
  탐험 = 지금 최선 5덱(킥 뒤엔 계보 5덱)마다 5덱이 안 쓰는 니케로 한 명 교체한 아직 안 본 구성 — 같은 단계(ⓐ의 이웃과 같음) +
  다른 단계(구조 틀 6종 안, 배치 1 · 2 · A · 3 — ⓐ에 없는 수). 모델 예측을 보지 않고 덱을 섞어 돌아가며 고르게 무작위로 고른다.
  탐험으로 고른 구성은 계보에 넣는다(ⓐ처럼). 탐험 후보가 모자라면 ⓑ 예측 순으로 채워 라운드 평가 수는 n 그대로.
- 난수: random.Random(f"exp39b-{계정 id}-{sess.used}") — 결정론.
- 근거(시뮬 0, 실험 36 base 기록):
  · 대각 근사 불확실성(니케 1/(λu+n) + 짝 1/(λp+n))은 다음에 평가된 구성의 잔차와 음의 상관(−0.02~−0.20), 높은 쪽 잔차 p90도
    낮다 → 「예측 + κ·불확실성」은 시너지 점프를 가리키지 않아 버렸다. resid_sd는 상수라 더해도 순위가 바뀌지 않는다.
  · base 최종 상위 40은 거의 다 ⓑ(최고 덱 한 언덕), 최종 5덱 중 4개 이상이 ⓐ → 상위 40 부모 탐험(v1)은 언덕만 더 판다. v1은
    S36에서 약 3분 만에 끊고 5덱 부모로 바꿨다.
  · S37에서 놓친 랭커 덱(59.7억)은 5덱 중 한 덱(49.2억)의 같은 단계 한 명 교체인데 모델은 28~36억으로 봐 부모보다 낮았다(ⓐ 순위 밖).
    S36 · S42 다시 묶은 묶음의 랭커 덱 일부는 5덱의 다른 단계 한 명 교체다 → 5덱 한 명 교체를 모델 순위 밖에서 고르게 시험한다.
- 고른 설정: 아래 PARAMS(v2). 비율 0.2는 한 번만 시험했다(조정 실행 없음).

개발 결과(예산 12,500 · 시드 0, base = 실험 36 B_s0 기록을 run39.summarize로 요약. 단일 시드 — base 시드 잡음 s1÷s0 중앙 약 1%, 최대 3.8%)

| 시즌 | base pack | b pack | b/base | G base→b | visit base→b |
|---|---|---|---|---|---|
| S36 | 257.14 | 276.26 | +7.4% | 10.41% → 6.61% | 0.9% → 19.4% |
| S42 | 295.15 | 299.64 | +1.5% | 5.74% → 4.44% | 27.3% → 13.6% |
| S34 | 241.47 | 231.42 | −4.2% | 0.10% → 4.11% | 60.7% → 32.0% |
| S39 | 293.80 | 296.74 | +1.0% | 0.84% → 0.43% | 29.5% → 26.5% |

- S36 최종 5덱 중 2덱이 탐험 몫에서 처음 나왔다(S42 · S34 · S39는 0). S34는 2,000~3,000평가 사이 base의 큰 상승을 못 탔고
  끝까지 따라잡지 못했다(궤적 차이 — 탐험 덱이 5덱에 들지 않음). S37은 시뮬 한도(5만) 때문에 돌리지 않았다.
- 개발 시뮬: 300(점검) + v1 S36 중단분(약 1.7천, 기록 없음 — 추정) + 11,032 + 11,018 + 11,034 + 11,012 ≈ 4.6만.
"""

from __future__ import annotations

import importlib.util
import random
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
    "explore_share": 0.2,    # 라운드 n 중 탐험 몫(나머지는 base와 같은 ⓐ · ⓑ, 비율 70 : 30)
    "parents": "best5",      # 탐험 부모: 지금 최선 5덱(킥 뒤엔 계보 5덱) — 들어오는 니케는 5덱이 안 쓰는 니케
    "moves": "single(same+cross)",  # 한 명 교체: 같은 단계(ⓐ와 같은 이웃) + 다른 단계(구조 틀 6종 안, ⓐ에 없는 수)
    "pick": "uniform",       # 모델 예측을 보지 않고 덱을 돌아가며 덱마다 아직 안 본 교체를 고르게 무작위로
    "seed": "exp39b",        # 난수: random.Random(f"{seed}-{계정 id}-{sess.used}")
}


def single_moves(d, used, owned):
    """덱 d의 한 명 교체(들어오는 니케 ∉ used). 같은 단계는 그 자리에, 다른 단계는 구조 틀(STRUCT_FRAMES) 안일 때만
    배치 순서 1 · 2 · A · 3(R10.arrange)으로."""
    burst = {n: v["burst"] for n, v in owned.items()}
    out = []
    for i, n in enumerate(d):
        for m in owned:
            if m in used:
                continue
            nd = d[:i] + (m,) + d[i + 1:]
            if burst[m] == burst[n]:
                out.append(nd)
            elif R10.frame_of(nd, burst) in R10.STRUCT_FRAMES:
                by: dict[str, list[str]] = {}
                for x in nd:
                    by.setdefault(burst[x], []).append(x)
                out.append(R10.arrange(by))
    return out


def _explore(sess, pick_n, take, decks, lineage, rng):
    """탐험 몫: 5덱마다 아직 안 본 한 명 교체(single_moves)를 모으고, 덱 순서를 섞어 돌아가며 덱마다 하나씩 고르게
    무작위로 고른다(모델 순위를 쓰지 않는다). 고른 구성은 계보에 넣는다(ⓐ와 같은 5덱 고치기라서)."""
    book = sess.book.best
    used = {x for d in decks for x in d}
    pools = [[nb for nb in single_moves(d, used, sess.acct.owned) if frozenset(nb) not in book] for d in decks]
    pools = [p for p in pools if p]
    rng.shuffle(pools)
    got = 0
    while got < pick_n and pools:
        nxt = []
        for lst in pools:
            if got >= pick_n:
                break
            while lst:
                nb = lst.pop(rng.randrange(len(lst)))
                if take([nb]):
                    got += 1
                    if lineage is not None:
                        lineage.add(frozenset(nb))
                    break
            if lst:
                nxt.append(lst)
        pools = nxt
    return got


def local_round(sess, n, lineage, fitf):
    """base(실험 10 `local_round`)의 ⓐ 5덱 고치기 · ⓑ 상위 40 이웃을 (1 − explore_share)·n 안에서 70 : 30으로 하고,
    남은 몫을 `_explore`로 채운다. 탐험이 모자라면(후보 없음) ⓑ를 예측 순으로 더 채운다 — 라운드 평가 수는 n 그대로."""
    acct = sess.acct
    score = fitf(sess.book, acct.names)
    pick: list[tuple] = []
    seen: set[frozenset] = set()
    take = R9._take_factory(sess, pick, seen, n)
    n_exp = int(round(n * PARAMS["explore_share"]))
    n_mod = n - n_exp
    share = int(n_mod * R9.PACK_SHARE)
    if lineage is None:
        decks = [sq for _, sq in sess.pack()[1]]
    else:
        decks = [sq for _, sq in R9.pack_vals({c: v for c, v in sess.book.best.items() if c in lineage})[1]]
    got = 0
    for _, new in S4.pack_moves(decks, acct.owned, score):
        if got >= share:
            break
        got += take(new)
    if lineage is not None:
        lineage.update(frozenset(s) for s in pick)
    parents = sorted(sess.book.best.values(), reverse=True)[:R9.PARENTS]
    cands = []
    for _, sq in parents:
        lst = [(score(frozenset(nb)), nb) for nb in S4.neighbors(sq, acct.owned) if frozenset(nb) not in sess.book.best]
        cands += sorted(lst, reverse=True)[:R9.PER_PARENT]
    cands.sort(reverse=True)
    j = 0
    while j < len(cands) and len(pick) < n_mod:
        take([cands[j][1]])
        j += 1
    rng = random.Random(f"{PARAMS['seed']}-{acct.id}-{sess.used}")
    _explore(sess, n - len(pick), take, decks, lineage, rng)
    while j < len(cands) and len(pick) < n:
        take([cands[j][1]])
        j += 1
    return pick
