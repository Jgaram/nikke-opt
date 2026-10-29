"""실험 6 W3 — 조합 약 30개 선정 → compositions.json. (골격: 관리자. 구현: W3)

규칙은 README §평가 문제. 규칙을 코드로 고정하고, 컨트롤 결과를 보기 전에 고른다.
출력 형식은 common.Composition. 과정·니케별 등장 조합 수·사용한 시뮬 수는 selection.md에 남긴다.
(`select.py`가 아닌 이유: 표준 모듈 `select`를 가린다 — common.py 참고)
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("W3")


if __name__ == "__main__":
    sys.exit(main())
