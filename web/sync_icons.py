"""현황판 사이트 그림을 nikke-analysis에서 가져온다 — 화면에 나오는 니케 얼굴 · 시즌 보스 그림 · 속성 · 버스트.

    git clone --depth 1 https://github.com/Jgaram/nikke-analysis ../nikke-analysis
    python web/sync_icons.py --analysis ../nikke-analysis

- `web/icons/{units,bosses,elements,bursts}/`에 그림을 복사하고, `web/icons/icons.json`에
  이름 → 얼굴 번호 · 속성 · 버스트(로스터 `data/processed/roster.csv`)와 시즌 → 보스 그림
  (`data/processed/soloraid_seasons.csv`)을 적는다. 어느 커밋에서 받았는지도 남긴다.
- 사이트에 나오는 니케 · 시즌만 받고, 더는 안 쓰는 얼굴 · 보스 그림은 지운다.
  실험 결과가 늘어 새 니케가 나오면 다시 돌린다(`web/build.py`가 그림 없는 니케를 알려 준다).
- 그림의 권리는 SHIFT UP · Level Infinite에 있다(nikke-analysis README 「라이선스」).
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ICONS = HERE / "icons"
ANALYSIS_REPO = "https://github.com/Jgaram/nikke-analysis"
ELEMENTS = ("Electric", "Fire", "Iron", "Water", "Wind")
BURSTS = ("I", "II", "III", "I-II-III")


def slug(v: str) -> str:
    """nikke-analysis 파일 이름 규칙: 소문자 · 공백은 하이픈(`I-II-III` → `i-ii-iii`)."""
    return v.strip().lower().replace(" ", "-")


def load_build():
    name = "web_build"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "build.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def read_csv(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def commit_of(repo: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def sync(analysis: Path, out: Path = ICONS) -> dict[str, Any]:
    B = load_build()
    data = B.build_data()
    names = sorted({B.base_name(n) for n in B.site_names(data["seasons"])})
    seasons = [x["season"] for x in data["seasons"]]

    src = analysis / "data" / "assets" / "icons"
    roster = {r["name_ko"]: r for r in read_csv(analysis / "data" / "processed" / "roster.csv")}
    raid = {int(r["season"]): r for r in read_csv(analysis / "data" / "processed" / "soloraid_seasons.csv")}

    units: dict[str, Any] = {}
    missing: list[str] = []
    for n in names:
        r = roster.get(n)
        if not r or not (src / "units" / f"{r['unit_id']}.webp").exists():
            missing.append(n)
            continue
        el = [r["element"]] + [e for e in (r.get("extra_elements") or "").split(";") if e]
        units[n] = {"id": r["unit_id"], "el": [e for e in el if e in ELEMENTS], "b": r["burst"] or None}

    bosses: dict[str, str] = {}
    for s in seasons:
        img = (raid.get(s) or {}).get("boss_image") or ""
        if img and (src / "bosses" / f"{img}.webp").exists():
            bosses[str(s)] = img
        else:
            missing.append(f"S{s} 보스")

    want = {
        "units": {f"{u['id']}.webp" for u in units.values()},
        "bosses": {f"{img}.webp" for img in bosses.values()},
        "elements": {f"{slug(e)}.png" for e in ELEMENTS},
        "bursts": {f"{slug(b)}.png" for b in BURSTS},
    }
    for d, files in want.items():
        (out / d).mkdir(parents=True, exist_ok=True)
        for old in (out / d).iterdir():
            if old.is_file() and old.name not in files:
                old.unlink()
        for f in sorted(files):
            shutil.copyfile(src / d / f, out / d / f)

    index = {
        "source": {"repo": ANALYSIS_REPO, "commit": commit_of(analysis),
                   "files": "data/assets/icons/ · data/processed/roster.csv · data/processed/soloraid_seasons.csv"},
        "units": units, "bosses": bosses,
    }
    (out / "icons.json").write_text(json.dumps(index, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"units": len(units), "bosses": len(bosses), "missing": missing}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--analysis", type=Path, required=True, help="nikke-analysis 레포를 받아 둔 경로")
    a = p.parse_args(argv)
    r = sync(a.analysis)
    print(f"{ICONS}: 니케 얼굴 {r['units']}명 · 보스 그림 {r['bosses']}장")
    if r["missing"]:
        print(f"그림 못 찾음 {len(r['missing'])}개: {', '.join(r['missing'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
