# 화면 글자 따기 3-1 — 2026-09-19

## 사용법

1. 소스로 토마데스크를 다시 실행한다. 기존 EXE는 갱신하지 않았다.
2. `Ctrl+Alt+O` 또는 트레이의 `화면 글자 따기`를 누른다. 설정에서 단축키를 바꿀 수 있다.
3. 화면에서 글자가 있는 영역을 끌어 선택한다. Esc·우클릭·다른 앱 전환은 선택 취소다.
4. 인식된 글자는 클립보드에 복사되고 결과창에 표시된다. 내용을 수정한 뒤 `복사`하면 수정본이 복사된다.
5. 필요하면 `줄바꿈을 공백으로`를 누른다. 이 편집은 Ctrl+Z로 취소할 수 있다. `인식 원문 복원`은 처음 인식한 내용으로 되돌린다.
6. `다시 인식`은 새 영역을 고른다. 인식 중에는 중복 실행하지 않는다. 닫으면 늦게 도착한 결과를 버린다.

인식 결과가 비어 있거나 오류/취소이면 기존 클립보드를 유지한다. 한국어 엔진이 있으면 우선 사용하고, 없으면 설치된 영어 엔진을 사용한다. 영문 l/I 등의 오인식은 가능하므로 숫자·날짜·고유명사를 확인한다. 메모 생성/D-Day 제안은 다음 3-2단계이며 아직 없다.

## 의존성과 실패 처리

- `requirements.txt`에 Windows 전용 PyWinRT 3.2.1 런타임 및 Foundation, Foundation.Collections, Globalization, Graphics.Imaging, Media.Ocr, Storage.Streams를 명시했다. PyInstaller hiddenimports도 추가했다.
- 이 PC의 Python 3.10 사용자 패키지 경로에 위 OCR 구성 요소를 설치했다. 다른 Python/가상환경을 사용한다면 해당 환경에도 requirements를 설치해야 한다.
- 설정창에 OCR 사용 가능 언어 또는 패키지/언어팩 안내가 표시된다. OCR 구성 요소나 한국어/영어 언어팩이 없더라도 나머지 앱은 실행된다. Windows 언어팩은 자동 설치하지 않는다.
- 언어팩 확인 및 작은 초기화는 UI 스레드, 실제 이미지 인식은 별도 스레드에서 실행한다. 인식 작업은 동시에 하나만 실행하며 닫기/종료 후 결과를 적용하지 않는다.
- 화면당 원본 픽셀 크기와 논리 좌표 비율을 각각 사용한다. 선택 영역의 여러 모니터 조각은 가장 높은 배율에 맞춰 합친다. 가상 화면의 빈 간격은 흰색으로 남긴다.
- 합성 이미지 32,000,000픽셀 초과 및 Windows 엔진 최대 가로/세로 초과는 축소로 정확도를 숨기지 않고 영역을 줄이라는 안내를 한다.
- 캡처는 사용자가 시작할 때 화면들을 메모리에 보관하고, 선택이 끝나거나 취소되면 해제한다. 파일 저장·네트워크·외부 AI·기존 메모/일정 DB 변경은 없다. 클립보드는 Windows/사용자 설정에 따라 다른 앱이나 클립보드 동기화 기능에 노출될 수 있다.

## 검증

- 작업 기준: `1437c1fa3e3f64fe65abe7b7d0e2e5e2e7e34b84` + 기존 미커밋 변경. 사용자 메모 정리 및 파일 이름 변경 구현을 보존한다.
- 파일 이름 변경 재검사: 현재 프로젝트 복사본에서 123 passed, exit 0. 임시 파일만 실제 이동/되돌리기/중단 복구 시험에 사용했다.
- OCR 집중: `TOMADESK_NATIVE_OCR_TEST=1 python -m pytest test_screen_ocr.py -q` → 36 passed, exit 0. Windows 내장 OCR로 생성한 한글/영문/숫자 이미지의 한글·숫자 결과를 검증했다. 실제 데스크톱/PDF 캡처가 아니다. 한국어 엔진에서 영문 l/I 혼동을 관찰했다.
- OCR 의존성 설치 전 별도 환경 검사: 35 passed, 네이티브 인식 1 skipped. 실제 import 누락도 모의해 OCR만 비활성 처리됨을 검사한다.
- Qt 배율 1.25/1.5에서 OCR 검사 각각 36 passed. 가짜 화면의 음수 좌표·혼합 픽셀 비율·빈 간격, 마우스 선택/놓기·Esc·포커스, 결과 편집·복사·단일 Undo, 작업 취소/종료·재시도, 단축키 저장/충돌/ID 중복 방지 포함. 실제 모니터 배율 확인으로 간주하지 않는다.
- 생성한 글자와 명시적으로 불러온 Windows 글꼴로 결과창·설정창을 offscreen 렌더해 확인했다. 설정창 1150×680, 글꼴/테마 적용 상태에서 잘림 없이 배치됨. 실제 화면 사진은 아니다.
- 최종 전체 회귀: `TOMADESK_NATIVE_OCR_TEST=1 python tools/run_memo_full_regression.py` → **69모듈 1242 passed, failed_groups=[], exit 0**. GPT펫 원본 미설치로 1개 건너뜀. 최종 실행은 9개 묶음 모두 첫 시도에 통과했고 네이티브 종료·시간 초과·분할 재시도는 없었다. 앞선 회귀에서 기존 단축키 13개/7+6 배치를 가정한 검사가 실패하여 새 14개/7+7 계약으로 갱신한 뒤 전체를 다시 실행했다.
- 실제 PDF/이미지 화면 선택, 탐색기·엑셀·물리 포인터, 혼합 DPI 모니터, EXE는 미확인으로 TODO에 유지한다.

## 참고

- [Microsoft OcrEngine](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine): 설치 언어·최대 이미지 크기·비동기 인식 경계.
- [PyWinRT 타입/버퍼](https://pywinrt.readthedocs.io/en/stable/types.html): Windows Runtime와 Python 버퍼/비동기 호출. 실제 어댑터는 Windows Storage.Streams Buffer와 SoftwareBitmap을 사용해 검증했다.
- [Qt QScreen](https://doc.qt.io/qt-6/qscreen.html), [Qt High DPI](https://doc.qt.io/qt-6/highdpi.html): 캡처 이미지의 픽셀 크기와 모니터별 논리 좌표를 구분해 처리한다.
