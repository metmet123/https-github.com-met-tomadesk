# 알림 메모 UI 전체 검토

- 모드: full
- 범위: PyQt6 알림 메모 패널, 화면 전환 버튼, 알림 설정, 포스트잇 창
- 스타일 기준: 기존 `ui_theme.py` QSS와 `make-interfaces-feel-better`

| 범주 | 확인 근거 | 결과 |
| --- | --- | --- |
| Typography | 페이지·섹션 제목, 메모 목록, 알림 날짜, 상태 문구 | Clear |
| Surfaces | 카드 반경, 선택 테두리, 포스트잇 색상, 40px 조작 영역 | Clear |
| Animations | 화면 전환·저장·알림 상태 | 고빈도 동작에 별도 애니메이션을 넣지 않음 |
| Icons | 포스트잇 닫기, 날짜 입력, 색상 선택 | Clear |
| Performance | 20초 알림 검사, 500ms 포스트잇 저장 지연, 화면 전환 | Clear |

## 수정한 발견 사항

| Severity | 위치 | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | 알림 메모 하단 상태 | 상태 라벨이 남는 높이를 확장 | 38px 고정 상태 표시줄 | 콘텐츠 위계를 침범하지 않도록 함 |
| MEDIUM | 좁은 화면 편집 패널 | 옵션 행 때문에 가로 스크롤 발생 | 옵션·저장 동작을 두 행으로 분리하고 가로 스크롤 차단 | 820px 최소 폭에서 조작 가능성 보존 |
| MEDIUM | 알림·저장 버튼과 체크 옵션 | 일부 조작 높이가 40px 미만 | 알림 메모 범위의 주요 조작 영역을 40px 이상으로 통일 | 데스크톱 최소 클릭 영역 확보 |

## 고려했지만 제외

| 위치 | 후보 | 제외 이유 |
| --- | --- | --- |
| 화면 전환 | 슬라이드 애니메이션 | 자주 사용하는 전환에 반복적인 시각 비용을 추가함 |
| 메모 카드 | 강한 그림자 | 기존 단축키 화면의 테두리 중심 표면 체계와 어긋남 |
| 포스트잇 | 별도 이미지 아이콘 묶음 | 기존 Qt 텍스트 컨트롤과 불필요하게 스타일이 섞임 |

## 검증과 판정

- `output/alert_notes_preview_wide.png`: 1420×720 좌우 배치와 선택 상태 확인
- `output/alert_notes_preview_narrow.png`: 820×650 위아래 배치와 세로 스크롤 확인
- `output/alert_notes_postit_preview.png`: 독립 포스트잇 내용·닫기·크기 조절 영역 확인
- Qt 오프스크린 테스트와 실제 Python 소스 5초 실행 확인
- 판정: **Approve** — 남은 actionable interface-polish finding 없음
