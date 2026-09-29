import hashlib
from uuid import uuid4
import pytest
from PyQt6.QtWidgets import QApplication
from alert_notes.sqlite_store import NoteReminderStore
from mobile_bridge.service import MobileService
from mobile_bridge.markdown_codec import from_markdown,to_markdown

@pytest.fixture(scope='session')
def app():return QApplication.instance() or QApplication([])
@pytest.fixture
def service(tmp_path,app):
 store=NoteReminderStore(tmp_path/'notes.db');store.create_note('기존 메모','<html><body><p><b>원본</b> 서식</p><table><tr><td>표 원본</td></tr></table></body></html>')
 yield MobileService(store)
 store.close()
def request(n,source):
 return dict(op_id=str(uuid4()),sync_id=n['sync_id'],base_revision=n['revision'],base_hash=n['base_hash'],base_content=n['base_content'],title=n['title'],markdown=source,attachments=n['attachments'])
def test_markdown_exact_roundtrip_backup_and_idempotency(service):
 n=service.snapshot()['notes'][0];source='# 제목\n\n**굵게** 그리고 `code`\n\n- [ ] 할 일\n\n```python\n# comment\n```\n'
 c=request(n,source);r=service.apply(c);assert r['markdown_backup_sync_id'];assert service.apply(c)==r
 notes=service.snapshot()['notes'];assert len(notes)==2
 changed=next(x for x in notes if x['sync_id']==n['sync_id']);assert changed['markdown']==source and changed['markdown_native']
 assert 'font-weight:700' in changed['content']
 original=next(x for x in notes if x['sync_id']==r['markdown_backup_sync_id']);assert '<table' in original['content'] and '표 원본' in original['content']
 r2=service.apply(request(changed,source+'\n추가'));assert 'markdown_backup_sync_id' not in r2;assert len(service.snapshot()['notes'])==2

def test_conflict_copies_and_remaps_image_urls_in_markdown(service):
 import base64
 n=service.snapshot()['notes'][0];aid=service.store.add_attachment(n['id'],'image/png',base64.b64encode(b'fixture').decode(),1,1)
 service.store.update_note(n['id'],content=f'<html><body><p><img src="toma-note-image://{aid}" /></p></body></html>')
 n=service.snapshot()['notes'][0];service.busy=lambda:{n['id']}
 r=service.apply(request(n,f'# 문서\n\n![이미지](toma-note-image://{aid})'));assert r['conflict']
 copied=next(x for x in service.snapshot()['notes'] if x['sync_id']==r['sync_id']);newid=copied['attachments'][0]['id'];assert newid!=aid
 assert f'toma-note-image://{newid}' in copied['markdown'];assert f'toma-note-image://{newid}' in copied['content']
 assert service.store.note(n['id'])['content']==n['content']

def test_backup_preserves_attachments(service):
 import base64
 n=service.snapshot()['notes'][0];aid=service.store.add_attachment(n['id'],'image/png',base64.b64encode(b'image').decode(),1,1)
 service.store.update_note(n['id'],content=f'<html><body><p><img src="toma-note-image://{aid}" /></p><table><tr><td>보존</td></tr></table></body></html>')
 n=service.snapshot()['notes'][0];r=service.apply(request(n,'# 새 내용'))
 backup=next(x for x in service.snapshot()['notes'] if x['sync_id']==r['markdown_backup_sync_id'])
 assert '<table' in backup['content'];assert backup['attachments'][0]['data_base64']==base64.b64encode(b'image').decode()
 assert f"toma-note-image://{backup['attachments'][0]['id']}" in backup['content']

def test_pc_edit_invalidates_raw_source(service):
 n=service.snapshot()['notes'][0];service.apply(request(n,'# 첫 내용'))
 service.store.update_note(n['id'],content='<html><body><h1>PC 변경</h1></body></html>')
 latest=next(x for x in service.snapshot()['notes'] if x['id']==n['id']);assert 'PC 변경' in latest['markdown'];assert not latest['markdown_native']
 assert service.apply(request(latest,'# 다시 수정'))['markdown_backup_sync_id']

def test_new_empty_document_and_delete_all(service):
 c=dict(op_id=str(uuid4()),sync_id=str(uuid4()),new=True,base_content='',title='새 문서',markdown='',attachments=[])
 r=service.apply(c);n=next(x for x in service.snapshot()['notes'] if x['sync_id']==r['sync_id']);assert n['markdown']=='';assert n['markdown_native']
 service.apply(request(n,'\n\n'));latest=next(x for x in service.snapshot()['notes'] if x['id']==n['id']);assert latest['markdown']=='\n\n'

def test_size_limit_does_not_write(service):
 n=service.snapshot()['notes'][0]
 with pytest.raises(ValueError):service.apply(request(n,'x'*1000001))
 assert len(service.snapshot()['notes'])==1

def test_tables_and_html_disabled(app):
 html=from_markdown('| 제목 | 값 |\n| --- | --- |\n| 토마 | 42 |\n');assert '<table' in html and '42' in html
 assert '<script>' not in from_markdown('<script>alert(1)</script>')
