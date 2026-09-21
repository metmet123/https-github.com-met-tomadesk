import json
from datetime import date
from pathlib import Path
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox
from alert_notes.memo_organizer import analyze, dday
from alert_notes.memo_organizer_store import OrganizerStore, DuplicateMemoError
from alert_notes.memo_organizer_panel import OrganizerPanel
from test_memo_organizer import app, store
from qt_test_support import destroy_widget

CASES=json.loads((Path(__file__).parent/'tests/fixtures/memo_v2_cases.json').read_text(encoding='utf-8-sig'))

@pytest.mark.parametrize('case',CASES,ids=lambda c:str(c['index']))
def test_audited_examples(case):
    item=analyze(case['raw'],date.fromisoformat(case['base']))[0]
    expected=dict(case['expected'])
    # Noon is now explicitly supported; the earlier audit requested review
    # only because silently dropping the time was unsafe.
    if case['raw']=='내일 정오 제출':
        expected.update(kind=['task'],day='2026-09-20',clock='12:00')
    assert item.raw==case['raw']
    assert item.kind in expected['kind']
    for key,field in [('day','day'),('clock','clock'),('end','end_clock')]:
        if expected[key] is not None: assert getattr(item,field)==expected[key]

def test_duplicates_require_explicit_override_and_keep_raw(store):
    repo=OrganizerStore(store); base=date(2026,9,19)
    a=repo.capture('내일 회신',base); repo.apply(a,repo.get_capture(a)['items'])
    b=repo.capture('- 내일 회신  ',base)
    assert repo.get_capture(b)['raw']=='- 내일 회신  '
    with pytest.raises(DuplicateMemoError): repo.apply(b,repo.get_capture(b)['items'])
    assert len([r for r in repo.rows() if r['schedule_id']])==1
    repo.apply(b,repo.get_capture(b)['items'],allow_duplicates=True)
    assert len([r for r in repo.rows() if r['schedule_id']])==2

def test_duplicates_within_one_capture_roll_back(store):
    repo=OrganizerStore(store)
    c=repo.capture('내일 회신\n- 내일 회신',date(2026,9,19))
    with pytest.raises(DuplicateMemoError): repo.apply(c,repo.get_capture(c)['items'])
    assert store.conn.execute('select count(*) from schedule_items').fetchone()[0]==0

def test_legacy_capture_is_preserved_and_reanalyzed(store):
    repo=OrganizerStore(store); base=date(2026,9,19)
    c=repo.capture('내일 회신',base); state=repo.load()
    state['captures'][0].pop('parser_version')
    with store.conn: repo._write(state)
    new=repo.capture('내일 회신',base)
    assert c!=new and len(repo.load()['captures'])==2

def test_duplicate_ui_cancel_does_not_register(app,store,monkeypatch):
    panel=OrganizerPanel(store); panel.base.setDate(date(2026,9,19))
    panel.input.setPlainText('내일 회신'); panel.capture_input(); panel.apply_selected()
    panel.input.setPlainText('- 내일 회신'); panel.capture_input()
    assert panel.review.item(0,0).checkState()==Qt.CheckState.Unchecked
    assert '중복' in panel.review.item(0,8).text()
    monkeypatch.setattr(QMessageBox,'question',lambda *a: QMessageBox.StandardButton.No)
    panel.review.item(0,0).setCheckState(Qt.CheckState.Checked); panel.apply_selected()
    assert store.conn.execute('select count(*) from schedule_items').fetchone()[0]==1
    monkeypatch.setattr(QMessageBox,'question',lambda *a: QMessageBox.StandardButton.Yes)
    panel.apply_selected()
    assert store.conn.execute('select count(*) from schedule_items').fetchone()[0]==2
    destroy_widget(panel,app)

def test_additional_boundary_and_counterexamples():
    base=date(2026,12,31)
    assert analyze('다음달 2일 회신',base)[0].day=='2027-01-02'
    assert analyze('다음달 31일 회신',date(2026,1,31))[0].kind=='review'
    assert analyze('999999999999일 뒤 회신',base)[0].kind=='review'
    assert analyze('정보: 버전 3.5, 주문 번호 12345',base)[0].kind=='info'
    assert analyze('아이디어: 내일 주문 자동화',base)[0].kind=='idea'
    assert analyze('10/2/2027 회신',date(2026,9,19))[0].kind=='review'
    assert analyze('2027년 10월 2일(금) 회신',base)[0].kind=='review'
    for offset in range(-31,32):
        from datetime import timedelta
        expected='D-DAY' if not offset else f'D-{offset}' if offset>0 else f'D+{-offset}'
        assert dday((base+timedelta(days=offset)).isoformat(),base)==expected
