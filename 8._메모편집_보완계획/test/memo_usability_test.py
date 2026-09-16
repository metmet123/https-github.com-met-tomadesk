"""TomaDesk 메모 기능 사용성 테스트 (격리 임시 DB, 오프스크린 Qt).

실행: set QT_QPA_PLATFORM=offscreen && python memo_usability_test.py [S1 S2 ...]
실제 사용자 DB는 열지 않는다. out/ut.db 임시 파일만 쓴다.

사람이 누르는 순서대로 실제 위젯을 클릭/입력하고, 모달 창은 가로채서 화면을 찍은 뒤 닫는다.
결과는 results.json, 화면은 shots/*.png 로 남는다.
"""
import json, sys, traceback, time, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]  # 35_단축키 프로그램
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt, QPoint, QTimer, QMimeData
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (QApplication, QMainWindow, QInputDialog, QMessageBox, QMenu, QDialog,
                             QTreeWidgetItem, QFileDialog, QAbstractScrollArea)

OUT = Path(__file__).resolve().parent / 'out'; SHOTS = OUT / 'shots'; SHOTS.mkdir(parents=True, exist_ok=True)
for f in SHOTS.glob('*.png'): f.unlink()
RESULTS = []
EXC = []

def excepthook(t, v, tb):
    EXC.append(''.join(traceback.format_exception(t, v, tb))[-1500:])
sys.excepthook = excepthook

app = QApplication(sys.argv)
app.setFont(QFont("Segoe UI Variable" if sys.platform == "win32" else "Noto Sans CJK KR", 9))
from ui_theme import scaled_stylesheet
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
import os
if os.environ.get('PATCH_JSON'):
    import json as _j, alert_notes.rich_memo_edit as _r; _r.json=_j

# ---------------------------------------------------------------- 모달 가로채기
INPUT_QUEUE = []
MENU_LOG = []
MENU_PICK = []   # 다음 메뉴에서 고를 항목 텍스트
DIALOG_LOG = []
MSG_LOG = []

def _next_input(default=""):
    if INPUT_QUEUE:
        return INPUT_QUEUE.pop(0), True
    return default, False
QInputDialog.getText = staticmethod(lambda *a, **k: _next_input(k.get('text', '')))
QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: _next_input())
QMessageBox.question = staticmethod(lambda *a, **k: (MSG_LOG.append(('question', a[2] if len(a) > 2 else '')), QMessageBox.StandardButton.Yes)[1])
QMessageBox.warning = staticmethod(lambda *a, **k: (MSG_LOG.append(('warning', a[2] if len(a) > 2 else '')), QMessageBox.StandardButton.Ok)[1])
QMessageBox.information = staticmethod(lambda *a, **k: (MSG_LOG.append(('info', a[2] if len(a) > 2 else '')), QMessageBox.StandardButton.Ok)[1])

def _walk_actions(menu, prefix=""):
    out = []
    for act in menu.actions():
        if act.isSeparator():
            out.append(prefix + '---'); continue
        out.append(prefix + act.text() + ('' if act.isEnabled() else ' (비활성)'))
        if act.menu():
            out += _walk_actions(act.menu(), prefix + act.text() + ' > ')
    return out

def _menu_exec(self, *a, **k):
    MENU_LOG.append(_walk_actions(self))
    if MENU_PICK:
        want = MENU_PICK.pop(0)
        path = want.split(' > ')
        menu = self
        for i, part in enumerate(path):
            act = next((x for x in menu.actions() if x.text() == part), None)
            if act is None:
                return None
            if i < len(path) - 1:
                menu = act.menu()
            else:
                act.trigger(); return act
    return None
QMenu.exec = _menu_exec

DIALOG_HOOK = []  # callables(dialog) run while dialog shown
def _dialog_exec(self):
    self.show(); pump(5)
    name = self.windowTitle() or type(self).__name__
    shot_widget(self, 'dlg_' + re.sub(r'\W+', '_', name))
    DIALOG_LOG.append(name)
    if DIALOG_HOOK:
        try:
            DIALOG_HOOK.pop(0)(self)
        except Exception:
            EXC.append(traceback.format_exc()[-1500:])
    self.hide()
    return 0
QDialog.exec = _dialog_exec

def pump(n=10):
    for _ in range(n):
        app.processEvents(); QTest.qWait(10)

def shot_widget(w, name):
    pump(3)
    path = SHOTS / f"{len(list(SHOTS.glob('*.png'))):02d}_{name}.png"
    w.grab().save(str(path)); return path.name

def record(scenario, check, expected, actual, ok, shot=None):
    RESULTS.append(dict(scenario=scenario, check=check, expected=expected, actual=str(actual), ok=ok, shot=shot))
    print(('PASS ' if ok else 'FAIL ') + f"[{scenario}] {check} :: {actual}")

from PyQt6.QtGui import QKeyEvent
from PyQt6.QtCore import QEvent
def type_text(w, text):
    for ch in text:
        if ch == "\n":
            QTest.keyClick(w, Qt.Key.Key_Return); continue
        if ch.isascii():
            QTest.keyClicks(w, ch); continue
        app.sendEvent(w, QKeyEvent(QEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, ch))
        app.sendEvent(w, QKeyEvent(QEvent.Type.KeyRelease, 0, Qt.KeyboardModifier.NoModifier, ch))
    pump(3)

def click(w):
    QTest.mouseClick(w, Qt.MouseButton.LeftButton); pump(6)

# ---------------------------------------------------------------- 준비
db = OUT / 'ut.db'
for p in OUT.glob('ut.db*'): p.unlink()
store = NoteReminderStore(db, "새 메모")
cats = {r['name']: int(r['id']) for r in store.categories()}
a = store.create_note("개발 명령어 정리", "git status\n\ngit log --oneline")
b = store.create_note("알림/캘린더", "알림 기능 메모")
parent = store.create_note("개발", "상위 메모")
store.set_note_category(parent, cats['개발'])
c1 = store.create_child_note(parent, "[TD]메모기능 개선 계획")
c2 = store.create_child_note(parent, "[TD]새 메모")

win = QMainWindow(); panel = AlertNotesPanel(store)
win.setStyleSheet(scaled_stylesheet(1.0))
win.setCentralWidget(panel); win.resize(1330, 800); win.show(); pump(20)
ed = panel.editor; lp = panel.list_panel; body = ed.content_edit

def run(name, fn):
    before = len(EXC)
    try:
        fn()
    except Exception:
        record(name, '시나리오 실행', '예외 없음', traceback.format_exc()[-600:], False)
    if len(EXC) > before:
        for e in EXC[before:]:
            record(name, 'UI 슬롯 예외(실제 앱은 강제 종료될 수 있음)', '예외 없음', e[-500:], False)

# ================================================================ S1 첫 화면·목록
def s1():
    s = shot_widget(win, 'S1_first_screen')
    panel.select_note(c1); lp.select_id(c1); pump()
    s = shot_widget(win, 'S1_child_selected')
    vc, sc = lp.view_combo, lp.sort_combo
    record('S1 목록', '보기·정렬 드롭다운이 화면에 보이는가', '폭 60px 이상으로 표시',
           f'보기 {vc.width()}px, 정렬 {sc.width()}px, visible={vc.isVisible()}', vc.width() >= 60 and sc.width() >= 60, s)
    hidden = lp.table.isColumnHidden(3)
    record('S1 목록', '수정일 열 표시', '보임', f'숨김={hidden}, 목록 폭={lp.width()}px (NARROW_WIDTH={lp.NARROW_WIDTH})', not hidden, s)
    hs = lp.table.horizontalScrollBar()
    record('S1 목록', '가로 스크롤바 없음', '없음', f'visible={hs.isVisible()} max={hs.maximum()}', not hs.isVisible() or hs.maximum() == 0, s)
    allb = lp.category_filter_buttons[0]
    record('S1 목록', "'전체' 필터 칩 선택 상태", 'checked + 눈에 띄는 스타일', f'checked={allb.isChecked()}', allb.isChecked(), s)
    ss = scaled_stylesheet(1.0)
    record('S1 목록', '필터 칩 선택(:checked) 스타일 정의', 'QPushButton:checked 규칙 존재', 'QPushButton:checked' in ss, 'QPushButton:checked' in ss)
ONLY=set(sys.argv[1:])
_run=run
def run(name, fn):
    if ONLY and name not in ONLY: return
    _run(name, fn)
run('S1', s1)

# ================================================================ S2 편집기 머리 영역
def s2():
    panel.select_note(c1); pump()
    chips = ed.property_chips
    y0 = chips.buttons['reminder'].mapTo(win, QPoint(0, 0)).y()
    s0 = shot_widget(win, 'S2_format_closed')
    click(ed.format_expand_button)
    y1 = chips.buttons['reminder'].mapTo(win, QPoint(0, 0)).y()
    s1_ = shot_widget(win, 'S2_format_open')
    record('S2 머리영역', '서식 펼칠 때 알림 칩 위치 고정', '이동 0px', f'{y1 - y0}px 이동', y1 == y0, s1_)
    # 서식 1~3 버튼 높이
    heights = []
    for slot, w in ed.format_toolbar.preset_buttons.items():
        if w.isVisible():
            heights.append((f"서식 {slot}", w.height()))
    record('S2 머리영역', '서식 1~3 버튼 높이 28px', '<=28px', heights, all(h <= 28 for _, h in heights) if heights else False, s1_)
    body_h = ed.content_edit.height(); total = panel.editor_scroll.viewport().height()
    record('S2 머리영역', '서식 펼침 시 본문 높이 비율', '>=60%', f'본문 {body_h}px / 편집 영역 {total}px = {body_h*100//max(1,total)}%', body_h / max(1, total) >= 0.6, s1_)
    click(ed.format_expand_button)
    # 서식 지정 칩
    DIALOG_LOG.clear()
    click(chips.buttons['format'])
    fmt_open = ed.format_panel.isVisible()
    s = shot_widget(win, 'S2_format_chip')
    record('S2 머리영역', "'서식 지정' 칩 → 서식 1~3 설정 화면", '설정 대화상자 열림', f'열린 대화상자={DIALOG_LOG or "없음"}, 서식 서랍만 펼침={fmt_open}', bool(DIALOG_LOG), s)
    if fmt_open: click(chips.buttons['format'])
    # 단축키 칩
    DIALOG_LOG.clear()
    click(chips.buttons['hotkey'])
    page = ed.property_panel.active_page
    s = shot_widget(win, 'S2_hotkey_chip')
    record('S2 머리영역', "'단축키' 칩 → 단축키 설정 화면", '설정 대화상자 열림', f'열린 대화상자={DIALOG_LOG or "없음"}, 속성 패널 페이지={page}', bool(DIALOG_LOG), s)
    click(chips.buttons['hotkey'])
    # 툴바 단축키 버튼
    DIALOG_LOG.clear(); click(ed.format_expand_button)
    # 2차 수정: 툴바 끝 단축키 텍스트 버튼은 없고 ⚙ 메뉴의 '편집 단축키 설정…'이 대신한다.
    btn = getattr(ed, 'shortcut_settings_button', None)
    record('S2 머리영역', '툴바의 단축키 버튼 존재(칩과 중복)', '중복 없음', f'툴바 단축키 버튼={btn}', btn is None)
    actions = [act for act in ed.format_toolbar.preset_settings_menu.actions() if act.text().startswith('편집 단축키')]
    if actions: actions[0].trigger(); pump()
    record('S2 머리영역', '⚙ › 편집 단축키 설정이 여는 창', '대화상자 열림', DIALOG_LOG or '없음', bool(DIALOG_LOG))
    click(ed.format_expand_button)
    # ⋯ 칩
    click(chips.buttons['other'])
    s = shot_widget(win, 'S2_more_chip')
    texts = [w.text() for w in ed.property_panel.findChildren(type(ed.manual_save_button)) if w.isVisible()]
    record('S2 머리영역', "'⋯' 안의 항목", '메모 색상·투명도·항상 위·포스트잇·잠금·백링크·템플릿·버전', texts, True, s)
    record('S2 머리영역', "'⋯' 열면 본문 높이", '본문이 충분히 남음', f'본문 {ed.content_edit.height()}px', ed.content_edit.height() > 250, s)
    click(chips.buttons['other'])
    # 글자 잘림 검사
    clipped = []
    for w in ed.findChildren(type(ed.manual_save_button)) + ed.findChildren(type(ed.format_expand_button)):
        if not w.isVisible() or not w.text(): continue
        need = w.fontMetrics().horizontalAdvance(w.text()) + 12
        if need > w.width(): clipped.append(f"{w.text()}({w.width()}<{need})")
    click(ed.format_expand_button)
    for combo in ed.format_toolbar.findChildren(type(lp.view_combo).__mro__[1]):
        if combo.isVisible() and combo.currentText():
            need = combo.fontMetrics().horizontalAdvance(combo.currentText()) + 28
            if need > combo.width(): clipped.append(f"콤보:{combo.currentText()}({combo.width()}<{need})")
    click(ed.format_expand_button)
    record('S2 머리영역', '버튼·콤보 글자 잘림', '0개', clipped, not clipped)
    record('S2 머리영역', "삭제 버튼 문구·툴팁", "'삭제' + 휴지통 설명", f"{ed.delete_button.text()} / {ed.delete_button.toolTip()}", ed.delete_button.text() == '삭제' and '휴지통' in ed.delete_button.toolTip())
run('S2', s2)

# ================================================================ S3 카테고리
def s3():
    panel.select_note(a); lp.select_id(a); pump()
    MENU_PICK.append('업무'); click(ed.category_button)
    record('S3 카테고리', '편집기 칩 메뉴 항목', '미지정·카테고리·추가·관리', MENU_LOG[-1] if MENU_LOG else '메뉴 없음', bool(MENU_LOG))
    row = store.note(a)
    item = lp._item_for(a)
    record('S3 카테고리', '칩으로 바꾸면 즉시 저장·목록 반영', "DB·목록 모두 '업무'",
           f"DB={row['category_id']==cats['업무']}, 목록 칸='{item.text(2) if item else None}', 칩='{ed.category_button.text()}'",
           row['category_id'] == cats['업무'] and item is not None and item.text(2) == '업무')
    record('S3 카테고리', '저장 안내가 뜨는 위치', '편집 중인 곳 근처', f"목록 하단='{lp.action_status.text()}'(visible={lp.action_status.isVisible()}), 편집기 하단='{ed.saved_status.text()}'", True, shot_widget(win, 'S3_category_saved'))
    # 필터
    btn = next(x for x in lp.category_filter_buttons if x.text() == '개발')
    click(btn); pump()
    shown = [it.text(1) for it in lp._note_items()]
    s = shot_widget(win, 'S3_filter_dev')
    record('S3 카테고리', "'개발' 필터", "개발 카테고리만", shown, all(store.note(int(it.data(1, Qt.ItemDataRole.UserRole) or 0) or 0) is None or True for it in lp._note_items()), s)
    record('S3 카테고리', "필터 결과에서 하위 메모 표시", '부모가 개발이면 하위(미지정)는 숨김 또는 경로 표시', shown, True, s)
    click(lp.category_filter_buttons[0])
    # 하위 메모 상속
    panel.create_child_note(parent); pump()
    new_child = panel.current_id
    record('S3 카테고리', '새 하위 메모가 부모 카테고리 복사', "'개발'", store.note(new_child)['category_id'] == cats['개발'], store.note(new_child)['category_id'] == cats['개발'])
    # 관리 대화상자: 추가 → 삭제
    def manage(dlg):
        INPUT_QUEUE.append('임시분류'); dlg._add(); pump()
        cid = dlg._selected_id()
        store.set_note_category(b, cid)
        lp._set_category_filter(cid); pump()
        dlg.list.setCurrentRow(dlg.list.count() - 1); dlg._delete(); pump()
    DIALOG_HOOK.append(manage)
    panel.select_note(a)
    MENU_PICK.append('카테고리 관리'); click(ed.category_button)
    pump()
    record('S3 카테고리', '카테고리 삭제 시 메모는 미지정으로', 'category_id=None', store.note(b)['category_id'], store.note(b)['category_id'] is None)
    record('S3 카테고리', '삭제된 카테고리 필터 → 전체로 복귀', 'filter=None', lp.category_filter_id, lp.category_filter_id is None, shot_widget(win, 'S3_after_delete'))
    names = [x.text() for x in lp.category_filter_buttons]
    record('S3 카테고리', "필터 칩에 '미지정' 선택지", '있음', names, '미지정' in names)
run('S3', s3)

# ================================================================ S4 보기·정렬·일괄
def s4():
    lp.view_combo.setCurrentIndex(1); pump()
    groups = [lp.table.topLevelItem(i).text(1) for i in range(lp.table.topLevelItemCount())]
    s = shot_widget(win, 'S4_category_view')
    record('S4 보기·정렬', '카테고리별 보기 그룹', '카테고리 순서 + 미지정', groups, bool(groups), s)
    record('S4 보기·정렬', '카테고리별 보기에서 끌어 이동 막힘', 'dragEnabled=False', lp.table.dragEnabled(), not lp.table.dragEnabled())
    lp.view_combo.setCurrentIndex(0); lp.sort_combo.setCurrentIndex(3); pump()
    tops = [lp.table.topLevelItem(i).text(1) for i in range(lp.table.topLevelItemCount())]
    record('S4 보기·정렬', '제목 가나다순 정렬', '가나다 순', tops, tops == sorted(tops, key=str.casefold))
    lp.sort_combo.setCurrentIndex(0); pump()
    order_before = [int(r['sort_order'] or 0) for r in store.notes()]
    # 일괄 지정
    for nid in (a, b):
        it = lp._item_for(nid); it.setCheckState(0, Qt.CheckState.Checked)
    pump()
    s = shot_widget(win, 'S4_bulk_checked')
    record('S4 보기·정렬', '체크하면 일괄 카테고리 버튼 표시', 'visible', f"visible={lp.bulk_category_button.isVisible()} 폭={lp.bulk_category_button.width()}", lp.bulk_category_button.isVisible() and lp.bulk_category_button.width() > 50, s)
    MENU_PICK.append('자료'); lp._show_bulk_category_menu(); pump()
    ok = store.note(a)['category_id'] == cats['자료'] and store.note(b)['category_id'] == cats['자료']
    record('S4 보기·정렬', '일괄 지정 결과', '두 메모 모두 자료', [store.note(a)['category_id'], store.note(b)['category_id']], ok, shot_widget(win, 'S4_bulk_done'))
    still = [lp._item_for(n).checkState(0) == Qt.CheckState.Checked for n in (a, b) if lp._item_for(n)]
    record('S4 보기·정렬', '일괄 지정 후 체크 상태', '해제 또는 유지(명확히)', still, True)
    for nid in (a, b):
        it = lp._item_for(nid)
        if it: it.setCheckState(0, Qt.CheckState.Unchecked)
run('S4', s4)

# ================================================================ S5 Markdown 가져오기
MD = """# 가져오기 테스트

기간은 1~4주, 금액 10~20만원. ~~진짜 취소선~~

인라인 `git status` 코드

```
code ~block~ here
```

## 표 제목

| 항목 | 값 |
|---|---|
| A | 1 |
| B | 2 |

### 제목 3

#### 제목 4

본문 끝
"""
def s5():
    p = OUT / 'import_test.md'; p.write_text(MD, encoding='utf-8')
    panel.create_note(); pump()
    nid = panel.current_id
    panel.import_structured_files((ed, [str(p)])); pump(10)
    doc = body.document()
    text = body.toPlainText()
    strike_on_range = False; strike_real = False; code_mono = False
    blk = doc.begin()
    while blk.isValid():
        it = blk.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                f = frag.charFormat()
                if '1~4' in frag.text() or '10~20' in frag.text() or re.search(r'\d$', frag.text()) and f.fontStrikeOut():
                    strike_on_range = strike_on_range or f.fontStrikeOut()
                if '진짜 취소선' in frag.text() and f.fontStrikeOut(): strike_real = True
                if 'git status' in frag.text():
                    fam = (f.fontFamilies() or [f.fontFamily()]) if hasattr(f, 'fontFamilies') else [f.fontFamily()]
                    code_mono = any(x and ('mono' in str(x).lower() or 'consol' in str(x).lower() or 'courier' in str(x).lower() or 'coding' in str(x).lower()) for x in (fam or [])) or f.fontFixedPitch()
            it += 1
        blk = blk.next()
    s = shot_widget(win, 'S5_md_imported')
    record('S5 MD', "숫자 범위 '1~4' 원문 유지", "'1~4' 보이고 취소선 아님", f"본문에 1~4={'1~4' in text}, 취소선={strike_on_range}", '1~4' in text and not strike_on_range, s)
    record('S5 MD', '진짜 ~~취소선~~ 은 취소선', '취소선', strike_real, strike_real, s)
    record('S5 MD', '인라인 코드 고정폭', '고정폭 글꼴', code_mono, code_mono, s)
    # 표가 들어있는 제목 접기
    target = None; blk = doc.begin()
    while blk.isValid():
        if blk.text().strip().endswith('표 제목'): target = blk; break
        blk = blk.next()
    if target is None:
        record('S5 MD', "'표 제목' 제목 블록 찾기", '있음', '없음', False); return
    before_tables = sum(1 for fr in doc.rootFrame().childFrames())
    body.fold_heading(target); pump(10)
    s = shot_widget(win, 'S5_heading_folded')
    visible_cells = []
    for fr in doc.rootFrame().childFrames():
        cell_blocks = []
        b2 = doc.findBlock(fr.firstPosition())
        while b2.isValid() and b2.position() <= fr.lastPosition():
            cell_blocks.append(b2.isVisible()); b2 = b2.next()
        visible_cells.append(any(cell_blocks))
    record('S5 MD', '접힌 제목 아래 표 숨김', '표 칸 모두 숨김', f'표 {before_tables}개, 보이는 칸 있음={visible_cells}', not any(visible_cells), s)
    body.fold_toggle(target); pump(10)
    shot_widget(win, 'S5_heading_unfolded')
    ed.flush_pending_save(); pump()
    panel.select_note(a); panel.select_note(nid); pump()
    record('S5 MD', '저장 후 다시 열어도 표 유지', '표 1개 이상', len(body.document().rootFrame().childFrames()), len(body.document().rootFrame().childFrames()) >= 1, shot_widget(win, 'S5_reopen'))
run('S5', s5)

# ================================================================ S6 링크·백링크
def s6():
    panel.select_note(b); pump()
    DIALOG_HOOK.append(lambda dlg: (dlg.list.setCurrentRow(next(i for i in range(dlg.list.count()) if int(dlg.list.item(i).data(dlg.ID_ROLE)) == a)), setattr(dlg, '_force_accept', True)))
    orig = QDialog.exec
    def accept_exec(self):
        _dialog_exec(self); return QDialog.DialogCode.Accepted
    QDialog.exec = accept_exec
    try:
        body.moveCursor(QTextCursor.MoveOperation.End)
        body.insert_note_link(); pump()
    finally:
        QDialog.exec = orig
    ed.flush_pending_save(); pump()
    html = str(store.note(b)['content'])
    m = re.findall(r'toma-note://[^"\'<\s]+', html)
    record('S6 링크', '메모 링크 넣기 → v2 UUID 주소', 'toma-note://v2/<uuid>', m, any('/v2/' in x for x in m), shot_widget(win, 'S6_link_inserted'))
    panel.select_note(a); pump()
    click(ed.property_chips.buttons['other'])
    ed.relations_toggle.setChecked(True); pump()
    items = [ed.backlink_list.item(i).text() for i in range(ed.backlink_list.count())]
    s = shot_widget(win, 'S6_backlinks')
    record('S6 링크', '대상 메모에서 백링크 보기', "'알림/캘린더' 표시", items, any('알림/캘린더' in x for x in items), s)
    record('S6 링크', '백링크 찾아가는 단계 수', '1~2 클릭', "⋯ 클릭 → '백링크·주석 ▸' 클릭 (2단계, 개수 표시 없음)", False, s)
    click(ed.property_chips.buttons['other'])
    # 복제 시 v2 링크
    lp._item_for(b).setCheckState(0, Qt.CheckState.Checked); pump()
    panel.copy_selected_notes(); panel.paste_copied_notes(); pump()
    clone = panel.current_id
    record('S6 링크', '링크 있는 메모 복제 후 원래 대상 유지', 'v2 링크 유지', re.findall(r'toma-note://[^"\'<\s]+', str(store.note(clone)['content'])), bool(re.findall(r'toma-note://v2', str(store.note(clone)['content']))))
    record('S6 링크', '복제본 sync_id 새로 발급', '원본과 다름', store.note(clone)['sync_id'] != store.note(b)['sync_id'], store.note(clone)['sync_id'] != store.note(b)['sync_id'])
    it = lp._item_for(b)
    if it: it.setCheckState(0, Qt.CheckState.Unchecked)
run('S6', s6)

# ================================================================ S7 페이지 포함 메모 복제
def s7():
    host = store.create_note("페이지 호스트", "")
    panel.refresh(); panel.select_note(host); pump()
    body.setFocus(); body.insert_page_link(); type_text(body, "하위페이지"); pump(); ed.flush_pending_save(); pump()
    html = str(store.note(host)['content'])
    links = re.findall(r'toma-note://[^"\'<\s]+', html)
    record('S7 페이지', '새 페이지 링크 형식', 'v2 UUID', links, any('/v2/' in x for x in links))
    lp._item_for(host).setCheckState(0, Qt.CheckState.Checked); pump()
    panel.copy_selected_notes(); panel.paste_copied_notes(); pump()
    clone = panel.current_id
    clinks = re.findall(r'toma-note://v2/([0-9a-f-]{36})', str(store.note(clone)['content']))
    orig_links = re.findall(r'toma-note://v2/([0-9a-f-]{36})', html)
    children = [r for r in store.conn.execute("SELECT id,sync_id,title FROM notes WHERE parent_id=? AND deleted_at=''", (clone,))]
    child_sync = {str(r['sync_id']) for r in children}
    record('S7 페이지', '복제본의 페이지 링크가 복제된 하위 페이지를 가리킴', '복제본 하위 UUID',
           f'복제본 링크={clinks}, 원본 링크={orig_links}, 복제본 하위={list(child_sync)}',
           bool(clinks) and all(x in child_sync for x in clinks), shot_widget(win, 'S7_page_clone'))
    it = lp._item_for(host)
    if it: it.setCheckState(0, Qt.CheckState.Unchecked)
run('S7', s7)

# ================================================================ S8 주석
def s8():
    nid = store.create_note("주석 테스트", "첫 문장입니다. 중요한 결정 사항. 마지막 문장.")
    panel.refresh(); panel.select_note(nid); pump()
    cur = body.textCursor(); t = body.toPlainText(); i = t.find('중요한 결정')
    cur.setPosition(i); cur.setPosition(i + len('중요한 결정 사항'), QTextCursor.MoveMode.KeepAnchor); body.setTextCursor(cur)
    click(ed.property_chips.buttons['other'])
    INPUT_QUEUE.append('여기 다시 확인'); click(ed.add_annotation_button)
    anns = store.memo_data.annotations(nid)
    s = shot_widget(win, 'S8_annotation_added')
    record('S8 주석', '선택 영역에 주석 추가', '1개 저장', len(anns), len(anns) == 1, s)
    extras = body.extraSelections()
    has_mark = False
    blk = body.document().begin()
    while blk.isValid():
        itx = blk.begin()
        while not itx.atEnd():
            fr = itx.fragment()
            if fr.isValid() and '중요한' in fr.text() and (fr.charFormat().background().style() != Qt.BrushStyle.NoBrush or fr.charFormat().underlineStyle() != fr.charFormat().UnderlineStyle.NoUnderline):
                has_mark = True
            itx += 1
        blk = blk.next()
    record('S8 주석', '본문에 주석 위치 표시(밑줄/배경/아이콘)', '표시 있음', f'글자 표시={has_mark}, extraSelections={len(extras)}', has_mark or bool(extras), s)
    click(ed.property_chips.buttons['other'])
    # 본문 수정: 앞에 글자 추가 → 위치 복구, 원문 삭제 → 위치 확인 필요
    cur = body.textCursor(); cur.setPosition(0); cur.insertText("추가된 앞글. "); body.setTextCursor(cur)
    ed.flush_pending_save(); panel.select_note(a); panel.select_note(nid); pump()
    row = store.memo_data.annotations(nid)[0]
    newpos = body.toPlainText().find('중요한 결정')
    record('S8 주석', '앞에 글이 늘면 주석 위치 따라감', f'start_offset={newpos}', f"start_offset={row['start_offset']}", int(row['start_offset']) == newpos)
    t = body.toPlainText(); i = t.find('중요한 결정 사항')
    cur = body.textCursor(); cur.setPosition(i); cur.setPosition(i + len('중요한 결정 사항'), QTextCursor.MoveMode.KeepAnchor); cur.removeSelectedText()
    ed.flush_pending_save(); panel.select_note(a); panel.select_note(nid); pump()
    row = store.memo_data.annotations(nid)[0]
    ed.property_chips.buttons['other'].click(); pump()
    MENU_LOG.clear(); click(ed.annotation_menu_button)
    record('S8 주석', "원문이 지워지면 '위치 확인 필요'", 'location_status=needs_review', f"status={row['location_status']}, 메뉴={MENU_LOG[-1] if MENU_LOG else None}", str(row['location_status']) != 'resolved', shot_widget(win, 'S8_after_delete_quote'))
    record('S8 주석', "주석 팝오버(본문 위 말풍선)", '본문에서 바로 보기/수정', '⋯ > 주석 보기 메뉴의 하위 메뉴(수정/삭제)만 있음', False)
    # 실행 취소
    MENU_PICK.append('주석 실행 취소'); click(ed.annotation_menu_button)
    record('S8 주석', '주석 실행 취소(추가 취소)', '0개', len(store.memo_data.annotations(nid)), len(store.memo_data.annotations(nid)) == 0)
    record('S8 주석', 'Ctrl+Z로 주석 취소', '본문 Ctrl+Z와 연동', '별도 메뉴에서만 가능(본문 Undo와 분리)', False)
    ed.property_chips.buttons['other'].click(); pump()
run('S8', s8)

# ================================================================ S9 템플릿
def s9():
    src = store.create_note("템플릿 원본", "")
    panel.refresh(); panel.select_note(src); pump()
    body.setFocus(); type_text(body, "회의록"); QTest.keyClick(body, Qt.Key.Key_Return); type_text(body, "참석자: "); QTest.keyClick(body, Qt.Key.Key_Return); type_text(body, "결정: "); pump()
    body.selectAll(); pump()
    INPUT_QUEUE.extend(['회의록', '회의'])
    ok = body.save_selection_as_template(); pump()
    record('S9 템플릿', '선택 → 템플릿으로 저장', '저장됨', f'결과={ok}, 개수={len(store.memo_data.templates())}', len(store.memo_data.templates()) == 1)
    record('S9 템플릿', "'템플릿으로 저장' 진입 위치", '눈에 보이는 버튼/메뉴', '본문 우클릭 > 블록 메뉴 안에만 있음 (⋯ 에는 관리만)', False)
    dst = store.create_note("템플릿 사용", "")
    panel.refresh(); panel.select_note(dst); pump()
    body.setFocus(); type_text(body, "/템플릿"); pump(10)
    items = body.insert_popup_items()
    s = shot_widget(win, 'S9_slash_template')
    record('S9 템플릿', "'/템플릿' 입력 시 목록", "'템플릿 · 회의록' 표시", items, any('회의록' in x for x in items), s)
    if body.insert_popup_visible():
        for r in range(body._insert_popup.count()):
            if '회의록' in body._insert_popup.item(r).text(): body._insert_popup.setCurrentRow(r)
        body.run_selected_insert(); pump(10)
    txt = body.toPlainText()
    record('S9 템플릿', '템플릿 삽입 결과', '회의록/참석자/결정 들어감, /템플릿 글자 제거', repr(txt[:80]), '참석자' in txt and '/템플릿' not in txt, shot_widget(win, 'S9_inserted'))
    body.undo(); pump()
    record('S9 템플릿', 'Ctrl+Z 한 번으로 삽입 전체 취소', "본문 비거나 '/템플릿'만", repr(body.toPlainText()[:40]), '참석자' not in body.toPlainText())
    # 개발 메모 내용이 들어간 템플릿
    dev = store.create_note("PyQt 템플릿", "")
    panel.refresh(); panel.select_note(dev); pump()
    body.setFocus(); type_text(body, "from PyQt6.QtCore import QObject"); pump(); body.selectAll()
    INPUT_QUEUE.extend(['파이썬', 'py'])
    before = len(EXC)
    try:
        r = body.save_selection_as_template()
        record('S9 템플릿', "본문에 'PyQt6/QObject' 글자가 있는 템플릿 저장", '저장됨(일반 글자일 뿐)', f'결과={r}', r)
    except Exception as e:
        record('S9 템플릿', "본문에 'PyQt6/QObject' 글자가 있는 템플릿 저장", '저장됨(일반 글자일 뿐)', f'거부+예외 처리 안 됨: {e}', False)
    DIALOG_HOOK.append(lambda d: None)
    click(ed.property_chips.buttons['other']); click(ed.template_manager_button); click(ed.property_chips.buttons['other'])
run('S9', s9)

# ================================================================ S10 버전 기록 + 오늘 요약
def s10():
    nid = store.create_note("버전 테스트", "처음 내용")
    panel.refresh(); panel.select_note(nid); pump()
    body.setFocus(); body.moveCursor(QTextCursor.MoveOperation.End); type_text(body, " 두번째 수정"); pump()
    ed.flush_pending_save(); panel.select_note(a); pump(); panel.select_note(nid); pump()
    vers = store.memo_data.versions(nid)
    record('S10 버전', '메모 전환 시 자동 버전 생성', '1개 이상', [v['kind'] for v in vers], len(vers) >= 1)
    captured = {}
    def inspect(dlg):
        captured['labels'] = [dlg.list.item(i).text() for i in range(dlg.list.count())]
        captured['preview'] = dlg.preview.toPlainText()[:400]
    DIALOG_HOOK.append(inspect)
    click(ed.property_chips.buttons['other']); click(ed.version_button); click(ed.property_chips.buttons['other'])
    record('S10 버전', '버전 목록 표시 형식', '예: 09-15 14:02 · 자동', captured.get('labels'), bool(captured.get('labels')) and not re.search(r'\d{12,}', ' '.join(captured.get('labels', []))))
    prev = captured.get('preview', '')
    record('S10 버전', '미리보기/차이 비교 가독성', '사람이 읽는 글 차이', prev[:300], '<' not in prev and 'toma-block' not in prev)
    # 복원
    ver = store.memo_data.versions(nid)[-1]
    store.memo_data.restore_version(int(ver['id'])); panel.select_note(a); panel.select_note(nid); pump()
    record('S10 버전', "가장 오래된 버전으로 복원하면 편집 전 내용('처음 내용')으로 돌아감", "'두번째 수정' 없음", repr(body.toPlainText()[:40]), '두번째' not in body.toPlainText())
    kinds = [v['kind'] for v in store.memo_data.versions(nid)]
    record('S10 버전', '복원 직전 상태 저장', "'before_restore' 있음", kinds, 'before_restore' in kinds)
    # 오늘 요약이 메모 전환 뒤에도 갱신되는가
    from datetime import datetime
    store.set_deadline(b, datetime.now().strftime('%Y-%m-%d 23:59'), '오늘 마감 테스트')
    panel.refresh(); pump(10)
    txt = ' '.join(w.text() for w in panel.summary.findChildren(type(lp.action_status)) if w.isVisible())
    s = shot_widget(win, 'S10_summary_after_switch')
    record('S10 오늘 요약', '메모를 몇 번 바꾼 뒤 새 D-Day가 요약에 뜨는가', "'오늘 마감 테스트' 표시", f"_shutdown={getattr(panel.summary, '_shutdown', None)}, 표시 포함={'오늘 마감 테스트' in txt}", '오늘 마감 테스트' in txt, s)
run('S10', s10)

# ================================================================ S11 삭제·휴지통·요약 접기
def s11():
    tmp = store.create_note("지울 메모", "x"); panel.refresh(); panel.select_note(tmp); pump()
    click(ed.delete_button)
    row = store.conn.execute("SELECT * FROM notes WHERE id=?", (tmp,)).fetchone()
    record('S11 삭제', '삭제 → 휴지통 이동', 'deleted_at 채워짐', row['deleted_at'], bool(row['deleted_at']), shot_widget(win, 'S11_deleted'))
    store.restore_note(tmp)
    record('S11 삭제', '휴지통 복원', 'deleted_at 비움', store.note(tmp)['deleted_at'], not store.note(tmp)['deleted_at'])
    store.delete_note(tmp)
    store.conn.execute("UPDATE notes SET deleted_at='2000-01-01 00:00' WHERE id=?", (tmp,)); store.conn.commit()
    sid = store.conn.execute("SELECT sync_id FROM notes WHERE id=?", (tmp,)).fetchone()['sync_id']
    n = store.purge_expired_trash(7)
    tomb = store.conn.execute("SELECT * FROM sync_tombstones WHERE sync_id=?", (sid,)).fetchone()
    record('S11 삭제', '영구 정리 후 tombstone 기록', 'tombstone 1행', f'정리 {n}개, tombstone={dict(tomb) if tomb else None}', tomb is not None)
    # 오늘 요약 접기
    panel.refresh(); pump()
    w0 = panel.editor_scroll.width(); vis0 = panel.editor_remainder.isVisible()
    ed.summary_button.click() if ed.summary_button.isVisible() else panel._toggle_summary(); pump(10)
    w1 = panel.editor_scroll.width(); vis1 = panel.editor_remainder.isVisible()
    s = shot_widget(win, 'S11_summary_toggled')
    record('S11 요약', '요약 접기/펴기에 편집기 폭 반응', '폭이 바뀜', f'요약 {vis0}->{vis1}, 편집기 {w0}->{w1}px', (vis0 != vis1) and w0 != w1, s)
run('S11', s11)

# ================================================================ S12 좁은 폭
def s12():
    for width in (900, 780):
        win.resize(width, 760); pump(20)
        s = shot_widget(win, f'S12_width_{width}')
        clipped = []
        for w in win.findChildren(type(ed.manual_save_button)) + win.findChildren(type(ed.format_expand_button)):
            if w.isVisible() and w.text() and w.width() > 0:
                need = w.fontMetrics().horizontalAdvance(w.text()) + 10
                if need > w.width(): clipped.append(f"{w.text()}({w.width()}<{need})")
        record('S12 좁은 창', f'{width}px 글자 잘린 버튼', '0개', clipped[:12], not clipped, s)
    win.resize(1330, 800); pump(20)
run('S12', s12)


def s13():
    from alert_notes.memo_archive import export_memo_archive, restore_memo_archive, inspect_memo_archive
    path = OUT / 'backup.tomamemo'
    export_memo_archive(store, path)
    man = inspect_memo_archive(path)
    record('S13 백업', '.tomamemo 내보내기', '파일 생성', f'{path.stat().st_size} bytes, 미리보기={man}', path.exists())
    target = store.note(a); old = str(target['content'])
    store.update_note(a, content=old + ' (로컬 수정)')
    try:
        res = restore_memo_archive(store, path, 'merge')
        dup = [dict(r) for r in store.conn.execute("SELECT id,title,conflict_of_sync_id FROM notes WHERE conflict_of_sync_id=? AND deleted_at=''", (str(target['sync_id']),))]
        record('S13 백업', '병합 복원: 같은 UUID 내용 다르면 충돌 사본', '충돌 사본 1개 + 로컬 수정 유지', f"사본={dup}, 로컬 유지={'로컬 수정' in str(store.note(a)['content'])}", len(dup) == 1 and '로컬 수정' in str(store.note(a)['content']))
        panel.refresh(); pump()
        s = shot_widget(win, 'S13_after_merge')
        item = lp._item_for(dup[0]['id']) if dup else None
        record('S13 백업', '충돌 사본이 목록에서 구분되는가', '제목/표시로 충돌임을 알 수 있음', item.text(1) if item else None, bool(item) and ('충돌' in item.text(1)), s)
    except Exception as e:
        record('S13 백업', '병합 복원', '성공', repr(e)[:300], False)
run('S13', s13)

panel.shutdown(); store.close()
(OUT / 'results.json').write_text(json.dumps(dict(results=RESULTS, exceptions=EXC, dialogs=DIALOG_LOG, messages=MSG_LOG, menus=MENU_LOG), ensure_ascii=False, indent=1), encoding='utf-8')
print('\nTOTAL', len(RESULTS), 'FAIL', sum(1 for r in RESULTS if not r['ok']), 'EXC', len(EXC))
