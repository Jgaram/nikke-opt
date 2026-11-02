"""실험 32 R3d — B′ 수정 2(README §R3d 사전 등록). R3c와 같고 후처리 메뉴에 「버충 담당」 묶음 선택지 하나만 더한다.

    source .cache/evaluators.env && python -I experiments/32_primitive_control/r3d.py post
    python -I experiments/32_primitive_control/r3d.py analyze          # → r3d.json · r3d.md

버충 담당(차지 UP · 풀차지 전용 아닌 니케마다, click 축): 충전 창 톡톡이(4.0 · 0.03 · 등급 상) + 재장전 「풀버스트 끝까지 마치기」(등급 상).
계산기 `tactics.json` 「버충」 택틱의 내용을 이름 없이 원시 조각으로 적은 것이다 — P0 바탕(컨트롤 끔)에서는 택틱 이름이 효과가 없고(확인 시뮬 12),
원시 메뉴에서는 두 키(click · cover_at)를 함께 바꿔야 해서 좌표 하강이 찾기 어렵다(R3c 진단).
끝 탐침 · 최선 5덱 · 지도는 R3c와 같으므로 R3c 기록을 옮겨 쓴다(새 시뮬은 후처리뿐).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import r3c  # noqa: E402  (r3.probes · r3b.post_one · r3b.cmd_maps를 바꿔 끼운다)
import r3b  # noqa: E402
from r3 import r1, MenuConflict  # noqa: E402

SRC = HERE / "r3c"
r3b.OUT = HERE / "r3d"
r3b.ARM = "Bd"
r3b.NAME = "r3d"
CARRIER = {"tap_fire": {"rate": 4.0, "release": 0.03, "window": "burst_charge", "priority": "high"},
           "reload": {"policy": "finish_by_fb_end", "priority": "high"}}

_full_variants, _full_apply = r3c.full_variants, r3c.full_apply


def variants_d(squad: Sequence[str]) -> dict:
    info = r1.nikke_info()
    out = _full_variants(squad)
    for (who, ax), vs in out.items():
        if ax == "click" and not info[who]["full_charge_only"]:
            vs.append(r1._v(who, "click", "carrier", r1._c(who, CARRIER)))
    return out


def apply_d(options: Mapping[str, Any], chosen: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """R3c 조립 규칙 + 버충 담당은 같은 니케의 cover_at(재장전)과 같이 못 건다."""
    car = {v["nikke"] for v in chosen if v["axis"] == "click" and v["label"].endswith(":click:carrier")}
    if any(v["axis"] == "cover_at" and v["nikke"] in car for v in chosen):
        raise MenuConflict("버충 담당과 같은 니케의 재장전 앵커")
    return _full_apply(options, chosen)


r3c.full_variants = variants_d
r3c.full_apply = apply_d


def prepare() -> None:
    """R3c의 끝 탐침 · 지도를 옮긴다(같은 book)."""
    for s in r3b.r3.SEASONS:
        d = r3b.sdir(s)
        d.mkdir(parents=True, exist_ok=True)
        if not (d / "end.json").exists():
            shutil.copyfile(SRC / f"S{s}" / "end.json", d / "end.json")
        if not (d / "map_Bd.json").exists():
            shutil.copyfile(SRC / f"S{s}" / "map_Bc.json", d / "map_Bd.json")


if __name__ == "__main__":
    prepare()
    sys.exit(r3b.main())
