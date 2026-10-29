"""실험 6 W1 — Rust nikke-sim ↔ Python 원본(nikke-calc 23164e4) 대조 → crosscheck.md. (골격: 관리자. 구현: W1)

같은 요청을 두 평가기(make_evaluator("rust") · make_evaluator("python"))로 돌려 총딜 상대 차이를 표로 남긴다.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("W1")


if __name__ == "__main__":
    sys.exit(main())
