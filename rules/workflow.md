# 작업 규칙

모든 저장소 작업에 적용한다. 에이전트 진입점은 [AGENTS.md](../AGENTS.md)다.

## 브랜치와 반영

- **`main` 하나만 쓴다.** 기능 브랜치·PR을 만들지 않는다.
- 작업은 커밋하고 **`main`에 직접 push**한다. 레포 소유자의 상시 허가다.
  세션에 `claude/...`·`ccr-...` 같은 브랜치가 배정되어도 그 브랜치를 원격에 올리지 않는다.
- 기존 변경과 로컬 커밋을 확인·보존하고 최신 `origin/main`을 합친다. 원격 변경과 충돌하면 해결한 뒤 다시 검증한다.
- push 전에 저장소 루트에서 `python -m unittest discover -s tests -t .`를 실행한다.
  `NIKKE_SIM_BIN`(Rust)·`NIKKE_CALC_DIR`(Python)이 설정되어 있으면 해당 실제 평가기 테스트도 실행된다.
  통과·실패·생략을 구분해 보고한다.

```bash
git fetch origin main && git merge origin/main
python -m unittest discover -s tests -t .
# 작업 파일을 확인해 커밋한 뒤
git push origin HEAD:main
```

## 저장소 경계

- 이 레포는 공개 예정이다. 비공개 평가기 코드(자체 Rust 포팅·외부 배포본 스냅샷 등)는 커밋하지 않는다.
  평가기를 부르는 어댑터만 둔다. 계산기 코드를 이 레포에 복사해 수정하지 않는다.
- 평가기 내부를 직접 import하지 않고 평가기 인터페이스를 사용한다.
- 개인 육성 프로필은 그대로 공개 저장소에 기록하지 않는다. 평가 요청에는 인라인 육성 정보를 쓸 수 있다.

## 문서 관리

- [AGENTS.md](../AGENTS.md)는 필요한 문서를 찾는 진입점으로 유지한다.
- 목표·단계·범위는 [GOALS.md](../docs/GOALS.md), 설계·성공 기준은 [SEARCH.md](../docs/SEARCH.md),
  진행 현황은 [ROADMAP.md](../docs/ROADMAP.md), 실행 방법은 [README](../README.md)에 둔다.
- 규칙을 옮길 때 기존 지침과 참조를 함께 갱신한다. 목표 명세와 실제 구현·검증 상태를 구분하고 기존 실험 결과를 보존한다.

## 연구 진행

- 탐색 기법 연구는 [연구 회차](../docs/SEARCH.md#연구-회차-계획--실험--해석--다음-방향-결정)에 따라
  계획·실험·해석 후 심화·수정·전환 등을 판단하고 다음 계획을 갱신한다. 판단 근거는 실험 문서에,
  현재 연구 초점과 다음 행동은 [로드맵](../docs/ROADMAP.md)에 남긴다.

## 자동화 참고

Claude 원격 세션에서는 [.claude/settings.json](../.claude/settings.json)이
[single-branch.mjs](../.claude/hooks/single-branch.mjs)를 호출한다. 로컬 작업이 있으면 이를 보존하며 처리한다.

- SessionStart: 배정 브랜치를 확인하고 가능한 경우 `main`으로 전환·최신화한다.
- PreToolUse(Bash): `main`이 아닌 브랜치로의 push를 막는다. 브랜치 삭제는 이 검사에서 허용한다.
- Stop: `main`에 반영하지 않은 커밋이 있으면 종료를 막는다. 커밋하지 않은 변경은 경고한다.

[merge-to-main.yml](../.github/workflows/merge-to-main.yml)은 실수로 올라온 `claude/**`·`ccr-*` 브랜치를
검증 후 `main`에 합치고 삭제하는 안전망이다. 충돌하면 해당 브랜치가 남으므로 최신 `main`을 합쳐 해결한다.
이 자동화의 실행 여부와 관계없이 위 작업 규칙을 따른다.
