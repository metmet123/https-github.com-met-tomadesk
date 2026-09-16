# 단계 F 배치 기준 이미지

`memo_<창 폭>_<앱 배율>.png` 12장은 임시 SQLite 데이터로 만든 메모 패널을 Windows Qt 백엔드의 `QWidget.grab()`으로 캡처한 것이다. 창 폭은 780·900·1080·1330px, 앱 배율은 100·125·150%다.

캡처는 `test_memo_layout_contract.py --case WIDTH SCALE TEMP_DIR`에서 `TOMADESK_LAYOUT_SHOTS` 환경 변수를 이 폴더로 설정해 생성했다. 배치 비교용 기준 이미지이며 실제 Windows 포인터 입력, 운영체제 디스플레이 배율 또는 사용자 데이터 화면의 검증 결과로 간주하지 않는다.
