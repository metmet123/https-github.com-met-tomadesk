# 메모 편집기 세로 공간 — 공개 앱 벤치마킹

- 작성일: 2026-09-14
- 대상: TomaDesk `메모 편집` 화면
- 문제: 본문 입력 칸이 세로로 좁다. 붙박이 UI가 위 3줄·아래 5줄, 총 8줄이 본문을 누른다.
  실측 결과 1920×1010 화면에서 본문은 554px, 나머지는 전부 UI였다.

## 이번 조사의 비교 축

문제가 "기능은 다 있는데 본문이 좁다"이므로, **기능을 줄이지 않고 자리를 줄이는 방법**에 맞춰 네 축을 잡았다.

1. **상시 도구막대 처리** — 서식 도구를 늘 띄워 두는가, 필요할 때만 띄우는가
2. **메모 속성 배치** — 알림·마감·색·태그 같은 값을 본문 위아래에 쌓는가, 옆이나 팝오버로 빼는가
3. **임시 확장 수단** — 사용자가 한 번에 넓히는 장치(집중 모드·사이드바 토글)가 있는가
4. **본문 폭·여백 정책** — 가로가 남을 때 본문을 늘리는가, 멈추고 여백을 두는가

> **이미지에 대한 안내**: 첨부한 두 장은 각 앱의 실제 화면이 아니라 **배치 방식만 뽑아 그린 도식**이다.
> 상용 앱의 화면 캡처는 그대로 옮겨 싣지 않았고, 대신 각 항목에 공식 문서 링크를 달았다.
> TomaDesk 쪽 숫자(554px / 684px)는 실제 코드를 렌더해 측정한 값이다.

---

## 1. 앱별 정리

### Notion — 상시 도구막대를 아예 두지 않는다

| 축 | 구현 |
| --- | --- |
| 상시 도구막대 | **없음.** 글자를 끌어 고르면 그 자리에 부동 막대가 뜬다. "a floating tool bar full of options, which comes up anytime you highlight some text" |
| 블록 만들기 | 줄 앞에서 `/` → 메뉴. 마크다운(`# `, `- `, `> `)도 함께 |
| 속성 배치 | 페이지 속성을 **본문 위 칩 한 줄**로 눕힌다. 세로로 쌓지 않는다 |
| 본문 폭 | 기본은 좁은 읽기 폭. `전체 너비(Full width)`를 페이지별로 켠다 |

TomaDesk가 이미 `/` 메뉴와 마크다운 입력을 갖고 있으므로, **부동 막대만 추가하면 상단 서식 2줄(74px)을 통째로 없앨 수 있다.**

### UpNote — 집중 모드 한 방에 전부 감춘다

메모 목록 + 편집기 구조가 TomaDesk와 가장 비슷한 앱이다.

| 축 | 구현 |
| --- | --- |
| 임시 확장 | **Focus mode** — "the sidebar, note list, and other interface elements"를 한 번에 감춘다. `Ctrl+Shift+F` |
| 발견 가능성 | 키 말고 **편집기 오른쪽 위 펼치기 버튼**도 같이 둔다 |
| 기본값 설정 | 설정에서 **새 메모를 항상 집중 모드로 열기**를 켤 수 있다 |
| 본문 폭 | ⋯ 메뉴에 **Line length**(글줄 길이) 선택 |

TomaDesk의 F11과 거의 같은 기능인데, **① 버튼이 함께 있고 ② 기본값으로 지정할 수 있다**는 점이 다르다.

### Google Docs — 같은 키, 같은 발상

`Ctrl+Shift+F`로 **compact mode**를 켜면 메뉴와 도구막대가 함께 사라지고, 같은 키로 돌아온다.
"집중 모드 = `Ctrl+Shift+F`"가 사실상 업계 관례라는 점이 중요하다.

### OneNote(Office 리본) — 도구막대를 "이름줄"로 접는다

| 축 | 구현 |
| --- | --- |
| 상시 도구막대 | 리본을 **탭 이름 한 줄**로 접는다 |
| 접는 방법 | 오른쪽 위 접기 버튼 · `Ctrl+F1` · 탭 더블클릭 · 리본 우클릭 — **네 가지 경로** |
| 쓰는 방법 | 접힌 상태에서 탭을 누르면 잠깐 펼쳐지고, 쓰고 나면 다시 접힌다 |

기능을 하나도 안 없애고 자리만 반납하는 가장 보수적인 방법이다. **TomaDesk의 서식 2줄에 그대로 적용 가능하다.**

### Obsidian — 사이드바 토글 + 본문 폭 제한

| 축 | 구현 |
| --- | --- |
| 임시 확장 | 좌·우 사이드바를 각각 접는다. 접으면 가장자리에 펼치기 아이콘만 남는다 |
| 상시 도구막대 | 기본적으로 없다(마크다운 입력) |
| 본문 폭 | **Readable line length** — 가로가 넓어져도 글줄은 멈추고 양옆을 여백으로 둔다 |
| 집중 모드 | 기본 기능이 아니라 커뮤니티 플러그인(Zen Mode, Super Zen 등)이 담당 |

### Craft · Evernote — 속성을 옆으로 뺀다

노트의 메타데이터(정보·태그·공유 설정)를 본문 **아래**가 아니라 **오른쪽 패널이나 ⓘ 팝오버**에 둔다.
본문 세로를 한 줄도 가져가지 않는다.

---

## 2. TomaDesk 현재 방식과의 차이

| 축 | 공개 앱들 | TomaDesk 현재 |
| --- | --- | --- |
| 상시 도구막대 | 0줄(Notion·Bear·Obsidian) 또는 접힌 1줄(OneNote) | **항상 2줄**, 본문 위 고정 |
| 속성 배치 | 위 칩 한 줄(Notion) 또는 옆 패널(Craft) | **아래로 5줄 스택** — 알림·단축키·서식1~3·색·투명·저장·휴지통 |
| 임시 확장 | 단축키 + 버튼 + 기본값 설정(UpNote) | F11·Ctrl+\\ 있음. **버튼은 있으나 설명서·안내 없음**, 기본값 지정 불가 |
| 본문 폭 | 읽기 좋은 폭에서 멈추고 여백(Obsidian·Notion·UpNote) | 가로는 편집 칸 stretch가 0이라 늘지 않고, **오늘 요약만 늘어난다** |

핵심 차이는 하나다. **다른 앱들은 "쓸 때만 꺼내는 것"과 "늘 보이는 것"을 나눴는데, TomaDesk는 전부 늘 보이게 두었다.**
알림 예약·전역 단축키·서식 프리셋·색·투명·잠금은 **메모 하나당 몇 번 안 쓰는 기능**인데 항상 자리를 차지한다.

---

## 3. 개선 방향 (우선순위)

| 순위 | 무엇을 | 참고한 사례 | 얻는 세로 | 난이도 |
| --- | --- | --- | --- | --- |
| 1 | **아래 5줄을 제목 옆 "속성 칩 한 줄"로** — 🔔알림 · 📌D-Day · 🎨색 · ⌨단축키 · ⋯ 를 누르면 팝오버 | Notion 페이지 속성, Craft ⓘ 패널 | **약 170px** | 중간 |
| 2 | **글자를 고를 때 뜨는 부동 서식 막대** + 상단 서식 2줄 제거 | Notion 부동 막대 | **약 74px** | 중간 |
| 3 | 2번이 부담스러우면 **서식 2줄을 "서식 ▾" 한 줄로 접기**(기본 접힘, 누르면 잠깐 펼침) | OneNote 리본 최소화 | 약 40px | 낮음 |
| 4 | **F11 집중 모드를 발견 가능하게** — 설명서 한 장 + 상태줄 안내 + "새 메모는 항상 집중 모드로" 설정 | UpNote Focus mode | (이미 있음) | 낮음 |
| 5 | **편집 칸도 늘어나게** `setStretchFactor(1, 1)` + 오늘 요약 최대 너비 제한 | — (TomaDesk 자체 문제) | 가로 +350px → 세로 +130px | 낮음 |
| 6 | **본문 글줄 폭 선택**(좁게·보통·넓게) 추가 | Obsidian Readable line length, UpNote Line length | 가독성 | 낮음 |

1~3번을 다 하면 붙박이가 **8줄 → 2~3줄**이 되고, 본문은 554px → **800px 안팎**이 된다.
없어지는 기능은 없다. 알림·D-Day·색·투명·잠금·단축키는 칩을 눌러 열고, 서식은 부동 막대와 접힌 한 줄에 모두 들어 있다.

### 지금 당장 (코드 수정 없이)

오늘 요약과의 나눔선을 왼쪽으로 끌어 편집 칸을 **930px 이상**으로 만들면, 아래 도구가 스스로 두 칸으로 갈라지고
서식 막대가 본문 위에서 아래로 내려간다. **본문 554 → 684px.** 이 비율은 저장된다.

---

## 출처

- Notion 서식·`/` 메뉴 — [A Guide to Editing and Formatting Text in Notion (Thomas Frank)](https://thomasjfrank.com/a-guide-to-editing-and-formatting-text-in-notion-notion-fundamentals/)
- Notion 페이지 꾸미기·전체 너비 — [Style & customize your Notion page (Notion Help)](https://www.notion.com/help/customize-and-style-your-content)
- UpNote 집중 모드 — [Focus mode (UpNote Help)](https://help.getupnote.com/organize-and-manage-notes/view-control/focus-mode)
- Google Docs 압축 모드 — [How to hide the menus in Google Docs (8apps)](https://www.8apps.co/guides/accelerator-keys/google-docs-shortcuts/how-to-hide-the-menus)
- OneNote 리본 최소화 — [Minimizing and Expanding the Ribbon (Microsoft OneNote 2010 Plain & Simple, O'Reilly)](https://www.oreilly.com/library/view/microsoft-r-onenote-r-2010/9780735664784/ch09s02.html)
- Obsidian 사이드바 — [Obsidian Help · User interface · Sidebar](https://huggingface.co/spaces/anpigon/obsidian-qa-bot/raw/main/docs/obsidian-help/User%20interface/Sidebar.md)
- Obsidian 집중 모드 플러그인 — [Zen Mode](https://community.obsidian.md/plugins/zenmode) · [Super Zen](https://community.obsidian.md/plugins/super-zen)
