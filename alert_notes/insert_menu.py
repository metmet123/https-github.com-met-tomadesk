"""편집 중에 넣을 수 있는 것들을 한곳에 모은 목록.

메모 편집창의 ＋ 단추, 포스트잇의 ＋ 단추, 그리고 본문에서 `/` 를 쳤을 때 뜨는
메뉴가 모두 이 목록 하나를 쓴다.  기능이 늘면 `INSERT_ITEMS` 에 한 줄만 더하면
세 곳에 함께 나타난다.  편집기에 아직 그 기능이 없으면 흐리게 보여 주므로,
아직 만들지 않은 것을 눌러 아무 일도 일어나지 않는 일은 없다.

명령어도 여기 한곳에 적는다.  단축키를 걸어 주는 일(`install_insert_shortcuts`)과
설명을 띄우는 일(`item_tooltip`)이 같은 줄을 읽으므로, 어긋날 수가 없다.
"""

from typing import NamedTuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QMenu, QWidgetAction


class InsertItem(NamedTuple):
    """넣을 수 있는 것 하나.

    `mark` 표시, `name` 이름, `method` 편집기 메서드, `keys` 찾을 때 쓰는 말,
    `hint` 한 줄 설명, `shortcut` 단축키, `typing` 줄 앞에서 치는 입력.
    """

    mark: str
    name: str
    method: str
    keys: tuple
    hint: str
    shortcut: str = ""
    typing: str = ""
    item_id: str = ""


# 단축키는 노션에 있는 것은 노션과 같게 맞췄다(체크리스트 4, 글머리표 5,
# 토글 7, 코드 8, 페이지 9).  노션에 없는 것은 이름 첫 글자를 땄다.
INSERT_ITEMS = (
    InsertItem(
        "▾", "토글", "make_toggle", ("토글", "toggle", "접기"),
        "눌러서 접었다 펴는 줄.  안쪽에 여러 줄을 넣을 수 있습니다",
        "Ctrl+Shift+7", "> ", "toggle",
    ),
    InsertItem(
        "☐", "체크리스트", "toggle_checklist", ("체크", "할일", "checklist", "todo"),
        "끝낸 줄에 줄이 그어집니다.  네모 위에서 스페이스로도 켜고 끕니다",
        "Ctrl+Shift+4", "[] ", "checklist",
    ),
    InsertItem(
        "•", "글머리표", "toggle_bullet_list", ("글머리", "목록", "bullet", "list"),
        "점을 찍어 늘어놓는 목록",
        "Ctrl+Shift+5", "- ", "bullet",
    ),
    InsertItem(
        "💡", "강조 상자", "make_callout", ("강조", "상자", "callout", "노트"),
        "눈에 띄게 두고 싶은 한 줄.  노란 바탕이 깔립니다",
        "Ctrl+Shift+C", "! ", "callout",
    ),
    InsertItem(
        "—", "구분선", "insert_divider", ("구분", "줄", "divider", "line"),
        "이야기가 바뀌는 자리에 긋는 가로줄",
        "Ctrl+Shift+D", "---", "divider",
    ),
    InsertItem(
        "❝", "인용문", "make_quote", ("인용", "quote", "따옴표"),
        "옮겨 적은 말.  왼쪽에 세로줄이 서고 글자가 기울어집니다",
        "Ctrl+Shift+Q", '" ', "quote",
    ),
    InsertItem(
        "⌗", "코드 줄", "make_code_block", ("코드", "code", "명령"),
        "고정폭 글씨에 회색 바탕.  띄어쓰기가 그대로 남습니다",
        "Ctrl+Shift+8", "```", "code",
    ),
    InsertItem(
        "▦", "표", "insert_table", ("표", "table", "칸"),
        "칸을 나눠 적는 표.  Tab 으로 다음 칸, 마지막 칸에서 Tab 이면 줄이 늘어납니다",
        "Ctrl+Shift+T", "", "table",
    ),
    InsertItem(
        "📄", "페이지", "insert_page_link", ("페이지", "page", "하위"),
        "메모 안에 하위 메모를 넣습니다.  줄을 지우면 그 페이지도 휴지통으로 갑니다",
        "Ctrl+Shift+9", "", "page",
    ),
    InsertItem(
        "🔗", "메모 링크", "insert_note_link", ("링크", "link", "메모", "연결"),
        "이미 있는 메모를 가리킵니다.  링크를 지워도 그 메모는 남습니다",
        "Ctrl+Shift+K", "[[", "note_link",
    ),
)

HEADING_ITEMS = (
    InsertItem("H1", "제목1", "apply_heading1", ("제목1", "heading1", "h1"),
               "가장 큰 제목. 다음 줄은 일반 본문으로 시작합니다", "", "# ", "heading1"),
    InsertItem("H2", "제목2", "apply_heading2", ("제목2", "heading2", "h2"),
               "큰 제목", "", "## ", "heading2"),
    InsertItem("H3", "제목3", "apply_heading3", ("제목3", "heading3", "h3"),
               "중간 제목", "", "### ", "heading3"),
    InsertItem("H4", "제목4", "apply_heading4", ("제목4", "heading4", "h4"),
               "작은 제목", "", "#### ", "heading4"),
    InsertItem("T", "본문", "apply_body_style", ("본문", "일반", "body"),
               "제목 서식을 일반 본문으로 되돌립니다", "Ctrl+Shift+0", "", "body"),
)

INSERT_ITEMS = HEADING_ITEMS + INSERT_ITEMS
PENDING_SUFFIX = " (준비 중)"


def item_label(item) -> str:
    return f"{item[0]}   {item[1]}"


def item_tooltip(item, typing_override: str | None = None) -> str:
    """마우스를 올렸을 때 뜰 설명.  무엇인지 먼저, 어떻게 부르는지 그다음."""
    lines = [f"<b>{item[1]}</b>", item[4]]
    ways = []
    if item[5]:
        ways.append(item[5])
    typing = item[6] if typing_override is None else typing_override
    if typing:
        ways.append(f"줄 앞에서 {typing.strip()} 다음 스페이스"
                    if typing.endswith(" ") else f"줄 앞에서 {typing}")
    if ways:
        lines.append("<span style='color:#64748b'>" + "  ·  ".join(ways) + "</span>")
    return "<div style='white-space:pre'>" + "<br>".join(lines) + "</div>"


def _ordered_items(editor):
    preferences = getattr(editor, "insert_preferences", None)
    return preferences.ordered_items() if preferences is not None else INSERT_ITEMS


def available_items(editor):
    """이 편집기가 실제로 할 수 있는 것과 아직 못 하는 것을 갈라 준다."""
    for item in _ordered_items(editor):
        handler = getattr(editor, item[2], None)
        yield item, (handler if callable(handler) else None)


def matching_items(editor, query: str):
    """`/` 뒤에 친 글로 좁힌 목록.  할 수 있는 것만 돌려준다."""
    text = str(query or "").strip().casefold()
    for item, handler in available_items(editor):
        if handler is None:
            continue
        if not text:
            yield item, handler
            continue
        if any(text in str(word).casefold() for word in (item[1], *item[3])):
            yield item, handler


def build_insert_menu(editor, parent=None) -> QMenu:
    menu = QMenu(parent)
    menu.setObjectName("formatInsertMenu")
    menu.setToolTipsVisible(True)
    from .insert_panel import InsertPanel
    panel_action = QWidgetAction(menu)
    panel_action.setDefaultWidget(InsertPanel(editor, menu))
    menu.addAction(panel_action)
    return menu


def install_insert_shortcuts(editor) -> list:
    """목록에 적힌 단축키를 편집기에 걸어 준다.

    편집기가 아직 못 하는 기능은 건너뛴다.  메모 본문과 포스트잇이 같은 편집기를
    쓰므로 두 곳 모두 같은 키로 움직인다.
    """
    installed = []
    for item, handler in available_items(editor):
        if handler is None or not item[5]:
            continue
        shortcut = QShortcut(QKeySequence(item[5]), editor)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(handler)
        installed.append(shortcut)
    return installed
