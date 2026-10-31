"""실험 17 — 큐브 목록 · 니케별 큐브 선택지 · 컨트롤과 합친 선택지 공간 (README §조건 · §기법).

큐브 목록은 평가기 데이터(`upstream/data/base_stat_tables/cube.json`)에서 뽑은 `cubes.json`만 읽는다
(평가기 코드는 import하지 않는다). 새 큐브가 나오면 `--extract`로 다시 뽑으면 선택지에 자동으로 들어간다.

    python experiments/17_cube_control/cubes.py --extract /home/user/nikke-calc-rs   # cubes.json 다시 뽑기
    python experiments/17_cube_control/cubes.py --table                              # 큐브 목록

- 선택지 = 계정이 가진 큐브 중 평가기가 지원하는 것(`unsupported`가 없는 것). 출발점(바꾸지 않음)은 계정 기본 큐브다
  (개발 계정 = 평가기 기본 렐릭 베어 Lv15). 장착 인원 한도는 없다(2026-10-31 사용자) — 니케마다 따로 고른다.
- 선택지 label = `"<니케>:cube:<큐브 이름>"`, patch = `{"chars": {니케: {"cube": {"name", "level"}}}}`.
- 합친 공간의 키 순서 = 배치 순서대로 니케마다 (실험 6 컨트롤 축들 → cube), 그 뒤 스쿼드 축(camera · tactic).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP6 = HERE.parent / "06_control_menu"
sys.path[:0] = [str(EXP6), str(HERE.parent.parent)]
import menu as menu6  # noqa: E402
from common import Variant  # noqa: E402

CUBES_PATH = HERE / "cubes.json"
SOURCE_FILE = "upstream/data/base_stat_tables/cube.json"
DEFAULT_CUBE = "렐릭 베어 큐브"   # 평가기 기본 스펙 큐브(spec/tables.rs) — 개발 계정의 출발점
MAX_LEVEL = 15

_CAT: dict[str, Any] | None = None


def catalog() -> dict[str, Any]:
    global _CAT
    if _CAT is None:
        _CAT = json.loads(CUBES_PATH.read_text(encoding="utf-8"))
    return _CAT


def supported() -> list[str]:
    """평가기가 효과를 등록하는 큐브 이름(목록 순서 = 평가기 데이터 순서)."""
    return [c["name"] for c in catalog()["cubes"] if not c.get("unsupported")]


def full_inventory(level: int = MAX_LEVEL) -> dict[str, int]:
    """개발 계정: 지원 큐브 전부를 같은 레벨로 가진다."""
    return {n: level for n in supported()}


def cube_variant(who: str, name: str, level: int) -> Variant:
    return Variant(nikke=who, axis="cube", label=f"{who}:cube:{name}",
                   patch={"chars": {who: {"cube": {"name": name, "level": int(level)}}}})


def cube_variants(who: str, inventory: Mapping[str, int], *, start: str = DEFAULT_CUBE,
                  allowed: Iterable[str] | None = None) -> list[Variant]:
    """니케 한 명의 큐브 선택지. 출발 큐브는 「바꾸지 않음」이라 넣지 않는다.

    `allowed`가 있으면 그 큐브만(사전값으로 줄인 판). 순서는 큐브 목록 순서(결정론).
    """
    keep = None if allowed is None else set(allowed)
    out = []
    for name in supported():
        if name == start or name not in inventory:
            continue
        if keep is not None and name not in keep:
            continue
        out.append(cube_variant(who, name, inventory[name]))
    return out


def joint_variants_fn(inventory: Mapping[str, int] | None = None, *, start: str = DEFAULT_CUBE,
                      allowed: Mapping[str, Iterable[str]] | Callable[[str], Iterable[str] | None] | None = None,
                      control: bool = True) -> Callable[[Sequence[str]], dict]:
    """`Space(variants_fn=...)`에 넘길 함수. control=False면 큐브 축만.

    allowed: 니케 → 허용 큐브(없는 니케는 전부). 함수면 None을 돌려준 니케는 전부.
    """
    inv = dict(full_inventory() if inventory is None else inventory)

    def allowed_for(who: str) -> Iterable[str] | None:
        if allowed is None:
            return None
        if callable(allowed):
            return allowed(who)
        return allowed.get(who)

    def fn(squad: Sequence[str]) -> dict:
        ctrl = menu6.variants(squad) if control else {}
        out: dict = {}
        for who in squad:
            for k, vs in ctrl.items():
                if k[0] == who:
                    out[k] = vs
            cv = cube_variants(who, inv, start=start, allowed=allowed_for(who))
            if cv:
                out[(who, "cube")] = cv
        for k, vs in ctrl.items():
            if k[0] is None:
                out[k] = vs
        return out

    return fn


def cube_of(labels: Iterable[str], who: str, start: str = DEFAULT_CUBE) -> str:
    """선택 label 목록에서 그 니케의 큐브(없으면 출발 큐브)."""
    pre = f"{who}:cube:"
    for lb in labels:
        if lb.startswith(pre):
            return lb[len(pre):]
    return start


# ---------------------------------------------------------------- 추출 · 표

def extract(rs_dir: Path) -> dict[str, Any]:
    src = rs_dir / SOURCE_FILE
    raw = src.read_bytes()
    data = json.loads(raw)
    commit = subprocess.run(["git", "-C", str(rs_dir), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    cubes = []
    for name, v in data.items():
        if name.startswith("_") or name == "공통" or not isinstance(v, Mapping):
            continue
        vals = v.get("values", {})
        top = max(vals, key=int) if vals else None
        cubes.append({"name": name, "stat": v.get("stat"), "skill": v.get("스킬명"), "template": v.get("template"),
                      "type": v.get("type", "battle_start"), "timing": v.get("timing"),
                      "value_max": vals.get(top, [None])[0] if top else None,
                      "unsupported": v.get("unsupported")})
    return {"_source": {"repo": "nikke-calc-rs", "commit": commit, "file": SOURCE_FILE,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "note": "게임 공개 자료(blablalink CDN)를 평가기가 정리한 큐브 표에서 이름 · 효과 종류만 옮겼다"},
            "default": DEFAULT_CUBE, "cubes": cubes}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--extract", type=Path, metavar="NIKKE_CALC_RS_DIR")
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args(argv)
    if a.extract:
        out = extract(a.extract)
        CUBES_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{CUBES_PATH}: 큐브 {len(out['cubes'])}개(지원 {sum(1 for c in out['cubes'] if not c['unsupported'])})")
    if a.table:
        for c in catalog()["cubes"]:
            mark = "  (미지원)" if c["unsupported"] else ""
            print(f"{c['name']:12s} {c['stat']:24s} {c['value_max']}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
