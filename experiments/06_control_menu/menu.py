"""실험 6 W2 — 니케별 컨트롤 선택지 생성. (골격: 관리자. 구현: W2)

평가기 어휘는 nikke-calc `docs/CONTROL.md` §설정 스키마 · `docs/SIM-JSON.md` §요청.
평가기 코드는 import하지 않는다. 평가기 데이터를 읽기 전용으로 쓰면 출처 커밋을 menu.md에 남긴다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]
from common import Variant  # noqa: E402

Key = tuple["str | None", str]  # (니케 또는 None, 축)


def variants(squad: Sequence[str]) -> dict[Key, list[Variant]]:
    """스쿼드의 (니케, 축)마다 선택지 목록. 「바꾸지 않음」(출발점 그대로)은 넣지 않는다.

    - 니케 단위 축(click·reload·cover·cancel·burst)의 키는 (니케, 축), 스쿼드 단위(camera·tactic)는 (None, 축).
    - 선택지가 없는 축은 키를 두지 않는다(빈 list 금지).
    - 순서는 결정론적이어야 한다(같은 스쿼드 → 같은 순서). 좌표 하강이 이 순서로 시도한다.
    - label은 `common.Variant` 규칙을 따른다.
    """
    raise NotImplementedError("W2")


def apply(options: Mapping[str, Any], chosen: Sequence[Variant]) -> dict[str, Any]:
    """기본 options 위에 선택지 patch들을 병합한 새 options. 입력은 바꾸지 않는다.

    - 같은 (니케, 축)의 선택지가 둘 이상이면 ValueError.
    - 한 니케의 여러 축은 `chars.<니케>.control` 안에서 합친다(예: reload 축과 cancel 축이 모두 `reload` 키를 쓰면
      두 조각을 합쳐야 한다 — 축 사이 키 충돌 규칙은 W2가 정하고 menu.md에 적는다).
    - options의 다른 칸(sim · operation.auto 등)은 보존한다.
    """
    raise NotImplementedError("W2")
