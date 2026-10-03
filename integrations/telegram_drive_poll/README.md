# Telegram → Drive 수신기 (기존 수신 운영 중, 새 회신·조회 코드 미반영)

## 2026-10-03 회신 코드 추가 (실계정 미검증)

저장소의 `Code.gs`에는 Drive 접수 직후의 상태 회신과 PC 승인·거부 결과 회신 코드가 추가됐다. **현재 Apps Script 프로젝트에 자동 반영된 것은 아니다.** 실제 사용하려면 이 파일을 Apps Script에 다시 반영하고 트리거 실행을 확인해야 한다. 기존 `TG_NEXT_OFFSET` 속성은 지우지 않는다.

PC에서 **Drive 데스크톱 앱으로 동기화 중인 로컬 수신 폴더**를 `수신 설정`에 선택한 경우, 승인·거부된 Telegram Action의 상태만 `reply_<bot>_<update>_<state>.json`으로 같은 폴더에 기록한다. 메모 본문과 토큰은 포함하지 않는다. Apps Script의 다음 `pollTelegram` 실행은 해당 파일을 읽어 허용된 개인 채팅으로 결과를 보내고 `sent_reply_...json` 표식을 남긴다. 이미 표시된 회신은 다시 보내지 않는다. Telegram `sendMessage`와 Drive 표식 저장은 하나의 원자적 작업이 아니므로, 전송 직후 중단되면 **상태 메시지가 중복될 수 있다.** Action 본문·승인 결과의 중복 반영 방지는 기존 DB 영수증이 담당한다.

PC는 `data/hub_telegram_reply_start.txt`에 이 회신 기능의 시작 시각을 로컬로 남기고, 그 이전에 이미 처리한 Action은 새 기능 설치 후에도 일괄 회신하지 않는다. 폴더나 연결 ID가 바뀌면 시작 시각을 새로 잡는다. 이 파일은 인증 정보가 아니며 DB 전체 백업에는 포함되지 않는다.

PC에서 Google OAuth **다운로드 전용** 경로만 사용하면 결과 파일이 다시 Drive로 업로드되지 않는다. 이 경로에는 별도의 업로드 구현이 필요하며, 회신이 가능한 것으로 안내하면 안 된다. 실제 봇 송신과 Drive 데스크톱 앱의 업로드 동작은 아직 실계정으로 검증하지 않았다.

`/today`·`/task`·`/dday` 조회 코드는 **Apps Script의 `TG_INCOMING_FOLDER_ID`가 가리키는 바로 그 Drive 폴더**에서 `tomadesk_snapshot_v1.json`을 읽는다. PC의 `모아보기·요약 → 조회 공개 선택`에서 공개할 일정을 고른 뒤 `Snapshot 게시 설정`에서 같은 Google Drive 데스크톱 동기화 폴더를 선택하고 자동 게시를 켜야 한다. 파일이 없거나 손상·링크 공유되면 내용을 보여주지 않는다. `/today`는 오늘 항목·기한 지난 할 일, `/task`는 미완료 할 일, `/dday`는 미완료 D-Day 항목만 제한된 개수로 보여준다. 응답에는 PC의 마지막 게시 시각을 넣으며 15분보다 오래되면 `오래됨`으로 표시한다. PC가 꺼져 있을 때 이 시각은 계속 오래된 상태로 남는다. 이 기능 역시 사용자의 Apps Script 갱신과 실제 휴대폰 시험 전에는 코드 단계다.

이 폴더는 Apps Script 시간 트리거에서 실행할 `pollTelegram()`의 소스와 로컬 단위 테스트다. 사용자가 기존 수신 버전을 실제 봇·Drive에 설치하고 5분 트리거를 켰으며, 새 Telegram 메시지에 대한 JSON 생성과 PC 수집함의 `검토 대기` 4건을 확인했다. **승인·거부와 새 회신·`/today` 코드는 실계정에서 확인하지 않았다.** PC의 OAuth Drive API 다운로드 경로 역시 승인·실계정 시험이 없고, 현재 확인된 PC 경로는 Drive 데스크톱 동기화 폴더의 로컬 스캔이다.

## 연결할 때 필요한 설정

1. 전용 Telegram 봇과 Google Drive의 **링크 공유를 끈 전용 수신 폴더**를 준비한다. 명시적으로 공유한 사용자·앱의 접근권한도 별도로 검토한다.
2. Apps Script의 *Script Properties*에 `TG_BOT_TOKEN`, `TG_BOT_ID`, `TG_ALLOWED_USER_ID`, `TG_ALLOWED_CHAT_ID`, `TG_INCOMING_FOLDER_ID`를 설정한다. 토큰과 실제 식별자는 코드·Git·문서에 넣지 않는다.
3. `Code.gs`를 Apps Script 프로젝트에 넣고, `pollTelegram`의 시간 기반 트리거를 설정한다. 처음에는 테스트 봇·테스트 폴더로 시험한다. 동일 봇에 활성화된 웹훅이 있으면 `getUpdates`는 사용할 수 없으므로 연결 방식부터 확인한다.
4. 테스트 메시지 1개를 보내 Drive에 `telegram_<bot_id>_<update_id>.json` 하나가 만들어지는지, 재실행해도 중복 파일이 생기지 않는지, 스크립트 오류 및 마지막 조회 시각을 확인한다.

수신 파일은 `schema_version`, `transport`, `bot_id`, `update_id`, `received_at_utc`와 제한된 `message` 필드를 담는다. 토큰은 저장하지 않는다. 실패한 Drive 저장에 대해서는 offset을 전진시키지 않는다. 파일은 저장됐지만 offset 기록이 실패하면 다음 실행 때 같은 이름·내용을 확인한 후 재시도한다. PC 측 형식 검증·로컬 중복 방지는 `alert_notes/hub_drive_ingress.py`가 담당한다. TomaDesk의 **메모 정리 → 수집함·검토 → 수신 설정**에서 이 PC에 이미 내려받은 전용 폴더와 봇/사용자/개인 채팅 숫자 ID를 지정하고 자동 수집을 켜면, 프로그램이 실행되는 동안 30초마다 폴더를 확인한다. 설정은 이 PC의 `data/hub_telegram_folder.json`에만 저장하고 DB 전체 백업에는 넣지 않는다. 파일을 지우지 않으며 재확인 시 Action 영수증으로 중복을 막는다. 손상·짝이 맞지 않는 파일이나 사라진 폴더는 화면에 오류로 표시한다. 전체 DB 복원 직전에는 이전 영수증과 재수신 파일이 어긋나지 않도록 이 자동 수집을 끄며, 사용자가 확인한 뒤 다시 켜야 한다. 실제 Google 계정 승인·다운로드 시험은 아직 남아 있다.

허용된 개인 채팅의 일반 문자만 수집함 Action으로 저장한다. 새 코드에서는 `/today`만 별도 조회 명령으로 처리하며, 다른 사용자·그룹·명령·미디어는 저장하지 않고 조회 offset을 넘긴다. 미지원 입력의 안내·실패 회신과 운영 모니터링은 아직 남아 있다. PC가 꺼져 있어도 수신 폴더에 저장될 수 있지만 Telegram의 업데이트 보관 한도, Apps Script 트리거 지연·할당량, Drive 장애 시 재시도는 추가 실계정 검증이 필요하다.

## PC의 Drive 자동 다운로드 코드

`alert_notes/hub_google_drive.py`는 **지정 폴더의 작은 Telegram JSON만** Drive API에서 내려받고, 파일 이름·크기·MD5·본문 ID를 검사해 PC 수신 폴더에 원자적으로 보관한다. 기존 파일은 덮어쓰거나 지우지 않으며 충돌 시 오류를 표시한다. `메모 정리 → 수집함·검토 → Drive 설정`에서 폴더 ID와 별도로 준비한 데스크톱 OAuth 클라이언트 JSON을 선택하고 자동 다운로드를 켤 수 있다. `Google 연결`을 눌러 사용자 본인이 승인하기 전에는 로그인 창이 자동으로 열리지 않는다. 승인 토큰과 설정은 이 PC의 `data` 폴더에만 저장하며 Git과 전체 DB 백업에 넣지 않는다. 자동 다운로드는 별도 작업 스레드에서 진행하고, 성공하면 로컬 수집함 검사를 바로 실행한다. 전체 DB 복원 시 자동 수집을 끄고 재확인을 요구한다.

Google Cloud 프로젝트의 Drive API 활성화·동의 화면·데스크톱 OAuth 클라이언트 생성이 필요하다. 앱은 지정 폴더만 조회하지만 OAuth의 `drive.readonly` 권한은 Google 계정의 Drive 전체 읽기를 허용하므로, 연결 화면에서 범위를 확인한 뒤 승인해야 한다. 현재 PC에서 해당 승인과 실제 Drive 파일 다운로드는 **실행·검증하지 않았다**. 계정이 연결되기 전까지는 단위 테스트의 가짜 Drive 서비스만 검증했다. 이 기능은 Telegram 봇/Apps Script 배포까지 자동으로 완료하지 않는다.

로컬 테스트: `node --test integrations/telegram_drive_poll/Code.test.js`
