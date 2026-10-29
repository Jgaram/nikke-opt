"""실험 6 W5 — 실행 기록 분석 → results.md. (골격: 관리자. 구현: W5)

README §잴 것 1~5를 계산한다. 입력은 common.Record JSON Lines와 compositions.json뿐이다(평가기를 부르지 않는다).

    python experiments/06_control_menu/analyze.py experiments/06_control_menu/run_log/*.jsonl
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]
from common import Composition, Record  # noqa: E402


def summarize(records: Sequence[Record], compositions: Sequence[Composition]) -> dict[str, Any]:
    """잴 것 1~5의 수치를 dict로. 키 이름과 구조는 W5가 정해 results.md 앞머리에 적는다."""
    raise NotImplementedError("W5")


def render(summary: dict[str, Any]) -> str:
    """summarize() 결과 → results.md 본문(Markdown)."""
    raise NotImplementedError("W5")


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("W5")


if __name__ == "__main__":
    sys.exit(main())
