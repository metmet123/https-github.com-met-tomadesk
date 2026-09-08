from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "토마_단축키_런처_사용설명서.pdf"


def register_fonts() -> tuple[str, str]:
    regular = Path(r"C:\Windows\Fonts\malgun.ttf")
    bold = Path(r"C:\Windows\Fonts\malgunbd.ttf")
    if not regular.exists() or not bold.exists():
        raise FileNotFoundError("맑은 고딕 글꼴을 찾을 수 없습니다.")
    pdfmetrics.registerFont(TTFont("Malgun", str(regular)))
    pdfmetrics.registerFont(TTFont("MalgunBold", str(bold)))
    return "Malgun", "MalgunBold"


def styles(font: str, bold: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName=bold, fontSize=26, leading=36,
                                textColor=colors.HexColor("#102A43"), alignment=TA_CENTER, spaceAfter=11 * mm),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName=font, fontSize=12, leading=20,
                                   textColor=colors.HexColor("#486581"), alignment=TA_CENTER),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName=bold, fontSize=18, leading=26,
                              textColor=colors.HexColor("#0B4F8A"), spaceBefore=4 * mm, spaceAfter=4 * mm),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName=bold, fontSize=13, leading=20,
                              textColor=colors.HexColor("#173B6C"), spaceBefore=3 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName=font, fontSize=10.2, leading=17,
                                textColor=colors.HexColor("#243B53"), spaceAfter=2.5 * mm),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName=font, fontSize=8.7, leading=13,
                                 textColor=colors.HexColor("#526D82")),
        "callout": ParagraphStyle("callout", parent=base["BodyText"], fontName=font, fontSize=10, leading=16,
                                   textColor=colors.HexColor("#102A43"), leftIndent=4 * mm, rightIndent=4 * mm),
    }


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), style)


def box(text: str, style: ParagraphStyle, background: str = "#EAF3FF") -> Table:
    table = Table([[paragraph(text, style)]], colWidths=[170 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#93C5FD")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
    ]))
    return table


def step_table(rows: list[tuple[str, str]], s: dict[str, ParagraphStyle]) -> Table:
    content = [[paragraph("단계", s["small"]), paragraph("방법", s["small"])] ]
    for number, text in rows:
        content.append([paragraph(number, s["body"]), paragraph(text, s["body"])])
    table = Table(content, colWidths=[26 * mm, 144 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCEBFA")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D7E8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    return table


def footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D9E2EC"))
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.setFont("Malgun", 8)
    canvas.setFillColor(colors.HexColor("#627D98"))
    canvas.drawString(20 * mm, 9.5 * mm, "토마 단축키 런처 사용설명서")
    canvas.drawRightString(190 * mm, 9.5 * mm, f"{document.page}쪽")
    canvas.restoreState()


def build() -> Path:
    font, bold = register_fonts()
    s = styles(font, bold)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm,
        topMargin=19 * mm, bottomMargin=22 * mm, title="토마 단축키 런처 사용설명서",
        author="Codex",
    )
    story = []

    story.extend([
        Spacer(1, 28 * mm),
        paragraph("토마 단축키 런처", s["title"]),
        paragraph("작업을 등록하고 단축키로 빠르게 실행하는 방법", s["subtitle"]),
        Spacer(1, 15 * mm),
        box("<b>이 프로그램으로 할 수 있는 일</b><br/>자주 쓰는 문구 입력, 사이트 열기, 프로그램 또는 폴더 실행, 마우스·키보드 반복작업을 단축키 하나로 실행할 수 있습니다.", s["callout"]),
        Spacer(1, 9 * mm),
        paragraph("빠른 시작", s["h1"]),
        step_table([
            ("1", "<b>＋ 새 작업</b>을 눌러 새 작업을 만듭니다."),
            ("2", "이름, 단축키, 작업 유형과 내용을 입력합니다."),
            ("3", "<b>저장</b>을 누릅니다. 저장된 활성 작업은 단축키에 자동 등록됩니다."),
            ("4", "다른 프로그램을 사용 중이어도 등록한 단축키를 눌러 실행합니다."),
        ], s),
        Spacer(1, 8 * mm),
        box("<b>안전 안내</b><br/>반복작업은 다른 프로그램에서 실제 클릭·입력을 수행합니다. 처음에는 짧은 동작으로 녹화하고 <b>저장 전 테스트</b>를 실행하세요. 실행 중 문제가 생기면 기본 <b>Ctrl+Alt+Esc</b>로 즉시 중지할 수 있습니다.", s["callout"], "#FFF7E6"),
        PageBreak(),
    ])

    story.extend([
        paragraph("1. 기본 작업 만들기", s["h1"]),
        paragraph("왼쪽 목록에서 작업을 관리하고, 오른쪽 작업 편집 영역에서 내용을 입력합니다. 작업 유형에 맞는 입력칸이 자동으로 표시됩니다.", s["body"]),
        paragraph("작업 유형", s["h2"]),
        step_table([
            ("문구 입력", "입력할 문구를 작성합니다. 필요하면 ‘입력 후 Enter’를 켜서 전송·검색까지 이어갈 수 있습니다."),
            ("사이트 열기", "열고 싶은 웹 주소(URL)를 입력합니다."),
            ("프로그램/폴더 열기", "실행 파일 또는 폴더 경로를 직접 입력하거나 선택 버튼으로 찾습니다."),
            ("반복작업", "마우스 클릭, 드래그, 키 입력, 문구 입력과 대기 시간을 녹화하여 재생합니다."),
        ], s),
        Spacer(1, 5 * mm),
        paragraph("단축키와 상태", s["h2"]),
        paragraph("Ctrl, Alt, Win, Shift 조합과 실행 키를 정합니다. 같은 단축키를 두 작업에 중복해서 저장할 수 없습니다. 목록의 ON/OFF 스위치나 상단 활성·비활성 버튼으로 작업을 잠시 끌 수 있습니다.", s["body"]),
        paragraph("목록 찾기와 정리", s["h2"]),
        paragraph("상태 필터, 작업 유형 필터, 검색창을 함께 사용해 원하는 작업만 볼 수 있습니다. 체크박스로 여러 작업을 선택한 뒤 활성·비활성 또는 삭제를 한 번에 수행할 수 있습니다.", s["body"]),
        box("<b>팁</b><br/>‘삭제 (N)’은 현재 체크된 작업 수를 뜻합니다. 삭제 전에는 선택 수를 확인하세요.", s["callout"], "#F0F9F4"),
        PageBreak(),
    ])

    story.extend([
        paragraph("2. 반복작업 녹화와 재생", s["h1"]),
        paragraph("반복작업은 자주 반복하는 마우스·키보드 절차를 기록해 재생하는 기능입니다. 민감한 화면이나 결제·삭제 작업은 충분히 테스트한 뒤 사용하세요.", s["body"]),
        step_table([
            ("1", "작업 유형에서 <b>반복작업</b>을 선택합니다."),
            ("2", "<b>녹화 시작</b>을 누른 뒤 대상 프로그램에서 필요한 동작을 수행합니다."),
            ("3", "기본 <b>Ctrl+Alt+F12</b> 또는 ‘녹화 종료’ 버튼으로 녹화를 끝냅니다."),
            ("4", "녹화된 단계와 대기 시간을 확인합니다. 필요하면 단계별 시간 편집으로 조정합니다."),
            ("5", "<b>저장 전 테스트</b>로 확인한 뒤 저장합니다."),
        ], s),
        Spacer(1, 5 * mm),
        paragraph("재생 속도와 대기 시간", s["h2"]),
        paragraph("녹화한 대기 시간을 그대로 쓰거나 재생 속도를 조절할 수 있습니다. 단계별 시간 편집에서는 각 동작 뒤 대기 시간을 0초부터 60초까지 설정할 수 있습니다.", s["body"]),
        paragraph("실행 중지", s["h2"]),
        box("<b>기본 실행 중지 단축키: Ctrl+Alt+Esc</b><br/>반복작업이 예상과 다르게 진행되면 즉시 누르세요. 녹화 종료 단축키와 실행 중지 단축키는 설정에서 변경할 수 있습니다.", s["callout"], "#FFF1F2"),
        paragraph("고급 JSON", s["h2"]),
        paragraph("고급 설정의 JSON은 녹화 단계 데이터를 직접 확인·가져오기·내보내기 위한 기능입니다. 일반 사용은 녹화와 단계별 시간 편집만으로 충분합니다. JSON을 가져온 뒤에는 반드시 저장해야 실제 작업에 적용됩니다.", s["body"]),
        PageBreak(),
    ])

    story.extend([
        paragraph("3. 백업, 창 사용, 문제 해결", s["h1"]),
        paragraph("백업과 이동", s["h2"]),
        step_table([
            ("JSON 백업", "현재 설정 전체를 백업합니다. 다른 PC로 옮기거나 큰 변경 전 보관할 때 사용합니다."),
            ("JSON 복원", "백업 파일의 작업을 복원합니다. 복원 전 현재 설정을 따로 백업해 두면 안전합니다."),
            ("Excel 내보내기", "작업 목록을 표 형식으로 내보냅니다."),
            ("Excel 가져오기", "정리한 작업 목록을 가져옵니다. 가져오기 전 자동 백업이 만들어집니다."),
        ], s),
        Spacer(1, 5 * mm),
        paragraph("창 크기와 화면 배치", s["h2"]),
        paragraph("창 모서리를 드래그해 크기를 바꿀 수 있습니다. 작은 화면에서는 목록과 편집 화면이 위아래로 배치됩니다. 종료할 때 마지막 창 위치·크기와 목록/편집 영역의 분할 위치가 저장되어 다음 실행 때 복원됩니다.", s["body"]),
        PageBreak(),
        paragraph("4. 문제 해결과 권장 사용", s["h1"]),
        paragraph("문제 해결", s["h2"]),
        step_table([
            ("단축키가 실행되지 않음", "작업이 활성(ON)인지, 단축키가 다른 프로그램과 충돌하지 않는지 확인합니다. 저장 후 상태 메시지에서 등록 결과를 확인하세요."),
            ("반복작업이 너무 빠르거나 느림", "재생 속도 또는 단계별 대기 시간을 조절하고 저장 전 테스트를 다시 실행합니다."),
            ("창이 보이지 않음", "트레이 아이콘 메뉴에서 메인 창을 엽니다. 모니터 구성이 바뀐 경우에는 다음 실행 때 화면 안으로 자동 보정됩니다."),
            ("가져온 내용이 적용되지 않음", "반복작업 JSON은 편집기에만 먼저 들어옵니다. 가져온 뒤 저장 버튼을 눌러 적용합니다."),
        ], s),
        Spacer(1, 7 * mm),
        box("<b>권장 사용 순서</b><br/>작은 작업부터 만들기 → 단축키로 테스트 → 반복작업은 짧게 녹화 → 저장 전 테스트 → JSON 백업으로 보관", s["callout"]),
    ])

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return OUTPUT


if __name__ == "__main__":
    print(build())
