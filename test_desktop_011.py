import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PyQt6.QtCore import QObject
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QWidget,QLineEdit,QPushButton,QLabel
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.rich_text import plain_text_from_content
from mobile_bridge.ui import MobileController,mobile_url
from mobile_bridge.pairing import pairing_payload
from qt_test_support import close_alert_panel,destroy_widget

class Desktop011Test(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(); self.store=NoteReminderStore(Path(self.temp.name)/'notes.db')
  self.first=self.store.create_note('원본','저장된 본문'); self.second=self.store.create_note('다른 메모','둘째 내용')
  self.store.set_setting('memo_auto_save_enabled','false')
  self.panel=AlertNotesPanel(self.store); self.panel.show_note(self.first)
 def tearDown(self):
  close_alert_panel(self.panel,self.app);self.store.close();self.temp.cleanup()
 def test_search_keeps_manual_title_body_cursor_and_selection(self):
  e=self.panel.editor; e.title_edit.setText('아직 저장하지 않은 제목'); e.content_edit.setPlainText('아직 저장하지 않은 본문')
  cursor=e.content_edit.textCursor();cursor.setPosition(4);e.content_edit.setTextCursor(cursor)
  with patch.object(e,'set_note',wraps=e.set_note) as reload:
   self.panel.list_panel.search.setText('검색결과없음');QTest.qWait(240)
   self.assertEqual(self.panel.list_panel.row_count(),0);self.assertEqual(self.panel.current_id,self.first);reload.assert_not_called()
   self.assertEqual(e.title_edit.text(),'아직 저장하지 않은 제목');self.assertEqual(e.content_edit.toPlainText(),'아직 저장하지 않은 본문');self.assertEqual(e.content_edit.textCursor().position(),4)
  self.assertEqual(self.store.note(self.first)['title'],'원본')
 def test_typing_is_coalesced_and_does_not_refresh_other_panes(self):
  with patch.object(self.panel.list_panel,'set_rows',wraps=self.panel.list_panel.set_rows) as rows,patch.object(self.panel.calendar,'refresh') as calendar,patch.object(self.panel.summary,'refresh') as summary,patch.object(self.panel.reminder_history,'refresh') as history:
   for value in ['다','다른','다른 메모']:self.panel.list_panel.search.setText(value)
   self.assertEqual(rows.call_count,0);QTest.qWait(240);self.assertEqual(rows.call_count,1)
   self.assertEqual(self.panel.list_panel.row_count(),1);calendar.assert_not_called();summary.assert_not_called();history.assert_not_called()
 def test_search_does_not_cancel_pending_autosave(self):
  self.panel.editor.set_auto_save_enabled(True)
  self.panel.editor.content_edit.setPlainText('자동 저장될 본문');self.panel.list_panel.search.setText('다른')
  QTest.qWait(650)
  self.assertEqual(plain_text_from_content(self.store.note(self.first)['content']),'자동 저장될 본문')
 def test_selecting_same_note_does_not_replace_document(self):
  self.panel.editor.title_edit.setText('초안')
  self.panel.select_note(self.first);self.assertEqual(self.panel.editor.title_edit.text(),'초안')
 def test_tree_repaint_recovers_after_failure(self):
  tree=self.panel.list_panel.table
  with patch.object(self.panel.list_panel,'_replace_rows',side_effect=ValueError('test')):
   with self.assertRaises(ValueError):self.panel.list_panel.set_rows([],self.first)
  self.assertTrue(tree.updatesEnabled())
 def test_preview_cache_invalidates_changed_content(self):
  listing=self.panel.list_panel
  self.assertEqual(listing._preview(1,'<html><body>첫 내용</body></html>'),'첫 내용')
  self.assertEqual(listing._preview(1,'<html><body>변경 내용</body></html>'),'변경 내용')
  for i in range(600):listing._preview(i,'본문')
  self.assertLessEqual(len(listing._preview_cache),512)
 def test_search_expansion_does_not_relayout_every_row(self):
  for i in range(35):self.store.create_note(f'검색용 {i}','본문')
  self.panel.resize(1300,650);self.panel.show();self.app.processEvents()
  sql=[];self.store.conn.set_trace_callback(sql.append)
  self.panel.list_panel.search.setText('검색용');self.panel._refresh_search()
  self.store.conn.set_trace_callback(None)
  reads=[q for q in sql if 'memo_list_column_ratios_v2' in q]
  self.assertLess(len(reads),5)
 def test_list_refresh_keeps_scroll(self):
  for i in range(50):self.store.create_note(f'목록 {i}','본문')
  self.panel.resize(1300,600);self.panel.show();self.panel.refresh();self.app.processEvents()
  tree=self.panel.list_panel.table;bar=tree.verticalScrollBar();bar.setValue(bar.maximum()//2);before=bar.value()
  self.panel.list_panel.set_rows(self.store.notes(),self.panel.current_id);self.assertEqual(bar.value(),before)

class Connection011Test(unittest.TestCase):
 def test_pairing_qr_contains_only_pc_address(self):
  self.assertEqual(pairing_payload('http://100.101.102.103:47831'),
   'tomadesk://pair?address=http%3A%2F%2F100.101.102.103%3A47831')
  for bad in ['https://100.101.102.103:47831','http://127.0.0.1:47831',
              'http://100.101.102.103:80','http://100.101.102.103:47831/path']:
   with self.assertRaises(ValueError):pairing_payload(bad)
 def test_qr_is_shown_only_while_tailscale_server_is_running(self):
  app=QApplication.instance() or QApplication([]);window=QWidget()
  c=MobileController.__new__(MobileController);QObject.__init__(c,window);c.window=window;c.server=None
  with patch('mobile_bridge.ui.subprocess.run',return_value=Mock(stdout='100.101.102.103')):
   stopped=c.connection_dialog()
  self.assertTrue(stopped.findChild(QLabel,'mobilePairQr').pixmap().isNull())
  destroy_widget(stopped,app)
  c.server=Mock(server_address=('100.101.102.103',47831))
  with patch('mobile_bridge.ui.subprocess.run',return_value=Mock(stdout='100.101.102.103')):
   running=c.connection_dialog()
  self.assertFalse(running.findChild(QLabel,'mobilePairQr').pixmap().isNull())
  destroy_widget(running,app);destroy_widget(window,app)
 def test_complete_url_and_restricted_hosts(self):
  self.assertEqual(mobile_url(' 100.101.102.103 '),'http://100.101.102.103:47831')
  for host in ['0.0.0.0','127.0.0.1','::1','https://100.1.2.3','invalid']:
   with self.assertRaises(ValueError):mobile_url(host)
 def test_copy_address(self):
  app=QApplication.instance() or QApplication([]);window=QWidget()
  c=MobileController.__new__(MobileController);QObject.__init__(c,window);c.window=window;c.server=Mock(server_address=('100.101.102.103',47831))
  with patch('mobile_bridge.ui.subprocess.run',return_value=Mock(stdout='100.101.102.103')):
   d=c.connection_dialog()
  next(b for b in d.findChildren(QPushButton) if b.text()=='주소 복사').click()
  self.assertEqual(app.clipboard().text(),'http://100.101.102.103:47831')
  destroy_widget(d,app);destroy_widget(window,app)
