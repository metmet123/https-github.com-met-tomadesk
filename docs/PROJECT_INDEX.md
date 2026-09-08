# 반복작업매크로 프로젝트 현황

마지막 정리: 2026-08-05

## 한눈에 보기

- 실제 폴더: `35_단축키 프로그램`
- 표시명: 반복작업매크로
- 종류: PyQt6 기반 단축키·매크로 실행 데스크톱 프로그램
- 실행 진입점: `A_shortcut_launcher.py`
- 주요 UI 모듈: `main_window.py`
- 배포 스크립트: `build_release.ps1`
- 배포 문서: `DISTRIBUTION.md`

## 중요 폴더와 파일

| 경로 | 역할 | 관리 원칙 |
|---|---|---|
| `data/` | 단축키·설정 등 런타임 데이터 | 삭제·초기화 전 확인 |
| `backup/` | 복구용 데이터 | 원본 보존 |
| `assets/` | UI·아이콘 자산 | 원본 보존 |
| `release/` | 배포 결과 | 실행 중 EXE 확인 후 빌드 |
| `output/` | 생성 결과 | 원본과 구분 |
| `test_feature_updates.py` | 기능 테스트 | 관련 변경 시 실행 |
| `test_ui_responsive.py` | 반응형 UI 테스트 | UI 변경 시 실행 |

## 실행과 테스트

```powershell
python .\A_shortcut_launcher.py
python -m pytest -q .\test_feature_updates.py .\test_ui_responsive.py
```

## 배포

EXE가 명시적으로 요청된 경우에만 다음 배포 흐름을 사용하며, 자세한 내용은 `DISTRIBUTION.md`를 따릅니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -Clean
```

## 바로가기

- [Markdown 작성 매뉴얼](MARKDOWN_작성_매뉴얼.md)
- [통합 작업 기록](WORK_LOG.md)
- [할 일](TODO.md)
- [설계 결정](DECISIONS.md)
- [알림 메모 UI 검토](ALERT_NOTES_UI_REVIEW.md)
- [Markdown 작성 매뉴얼](MARKDOWN_작성_매뉴얼.md)
