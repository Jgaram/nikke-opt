"""실험 39 판 b — README §판 b. 작업 세션 B가 채운다(이 파일 · dev/b/ 만 소유).

인터페이스(바꾸지 않는다): local_round(sess, n, lineage, fitf) -> list[tuple]
  실험 10 `run10.local_round`와 같은 인자 · 반환. 라운드 하나(n평가)에서 새로 계산할 구성(같은 단계 순서 스쿼드 튜플)을 고른다.
  sess.book.best = 지금까지 평가한 구성 → (값, 순서), sess.pack() = 지금 최선 5덱, sess.acct.owned = 보유 니케(→ burst 단계),
  lineage = 킥 뒤 계보(없으면 None), fitf(book, names) → 대리 모델 score(frozenset) -> 예측 값.
PARAMS: 기록용 설정 값(part_*.json의 params에 남는다).
"""

from __future__ import annotations

PARAMS: dict = {}


def local_round(sess, n, lineage, fitf):
    raise NotImplementedError("판 b는 작업 세션이 채운다")
