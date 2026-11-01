"""5덱 편성안끼리의 유사도 — 「누구와 누가 같은 덱에 묶였나」를 센다.

덱 안 배치 순서와 덱의 순서는 보지 않는다. 편성안은 덱(니케 이름 묶음)의 나열이다.
두 안의 니케 구성이 달라도 그대로 쓸 수 있다(없는 니케는 어느 쪽과도 맞지 않을 뿐이다).

- **쌍 자카드**(co-membership Jaccard): 편성안을 「같은 덱에 있는 두 니케」 쌍의 집합으로 보고
  |공유 쌍| / |두 안 쌍의 합집합|. 5명 덱 5개면 쌍이 50개이고, 공유 쌍이 S개면 S / (100 − S)다.
- **바꿀 니케 수**(분할 이동 거리): 두 안의 덱을 가장 잘 맞게 짝지었을 때(헝가리안, 같은 니케 수의 합 최대)
  맞지 않는 니케 수 = 큰 쪽 니케 수 − 맞은 수. 한 안을 다른 안으로 바꾸려면 이만큼 니케를 옮기거나 교체해야 한다.
  같은 25명을 덱만 다르게 나눈 안도 0보다 커진다.

덱 하나끼리는 공유 쌍 = C(같은 니케 수, 2)라서 쌍 기준이 니케 겹침 수와 같은 정보다. 쌍 기준은 5덱 단위에서 의미가 있다.
"""

from __future__ import annotations

from itertools import combinations, permutations
from typing import Iterable, Sequence

Plan = Sequence[Iterable[str]]


def decks_of(plan: Plan) -> list[frozenset[str]]:
    """편성안 → 덱(니케 집합) 목록. 빈 덱은 뺀다."""
    out = [frozenset(d) for d in plan]
    return [d for d in out if d]


def pairs(plan: Plan) -> frozenset[frozenset[str]]:
    """같은 덱에 있는 두 니케 쌍 전부."""
    return frozenset(frozenset(p) for d in decks_of(plan) for p in combinations(sorted(d), 2))


def pair_jaccard(a: Plan, b: Plan) -> float:
    """쌍 자카드(0~1). 두 안 모두 쌍이 없으면 1."""
    pa, pb = pairs(a), pairs(b)
    union = len(pa | pb)
    return len(pa & pb) / union if union else 1.0


def matched_members(a: Plan, b: Plan) -> int:
    """덱끼리 1:1로 짝지어 같은 니케 수의 합이 가장 큰 값. 덱 수가 다르면 짝 없는 덱은 0으로 센다."""
    da, db = decks_of(a), decks_of(b)
    if len(da) < len(db):
        da, db = db, da
    if not db:
        return 0
    if len(da) > 8:
        raise ValueError("덱이 8개를 넘는 편성안은 지원하지 않는다")
    m = [[len(x & y) for y in db] for x in da]
    return max(sum(m[i][j] for j, i in enumerate(p)) for p in permutations(range(len(da)), len(db)))


def moves(a: Plan, b: Plan) -> int:
    """바꿀 니케 수: max(두 안의 니케 수) − 맞은 수."""
    n = max(sum(len(d) for d in decks_of(a)), sum(len(d) for d in decks_of(b)))
    return n - matched_members(a, b)


def compare(a: Plan, b: Plan) -> dict[str, float | int]:
    """두 편성안의 유사도 묶음. shared_nikkes는 참고용(덱 나누기를 보지 않는 니케 공유 수)."""
    pa, pb = pairs(a), pairs(b)
    union = len(pa | pb)
    na = frozenset().union(*decks_of(a)) if decks_of(a) else frozenset()
    nb = frozenset().union(*decks_of(b)) if decks_of(b) else frozenset()
    return {"pair_jaccard": len(pa & pb) / union if union else 1.0, "pair_shared": len(pa & pb),
            "moves": moves(a, b), "shared_nikkes": len(na & nb)}
