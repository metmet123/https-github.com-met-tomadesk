import hashlib
import json
import ssl
import threading
import time
import urllib.request
from uuid import uuid4

import pytest
from PyQt6.QtWidgets import QApplication
from alert_notes.sqlite_store import NoteReminderStore
from mobile_bridge.codec import decode,patch
from mobile_bridge.security import Auth,certificate
from mobile_bridge.service import MobileService
from mobile_bridge.server import BridgeServer,dispatch,Request


@pytest.fixture(scope='session')
def app():
    app=QApplication.instance() or QApplication([])
    yield app

@pytest.fixture
def service(tmp_path,app):
    store=NoteReminderStore(tmp_path/'notes.db')
    store.create_note('PC 메모','첫 줄\n둘째 줄')
    yield MobileService(store)
    store.conn.close()

def change(note,text='모바일 수정'):
    return dict(op_id=str(uuid4()),sync_id=note['sync_id'],base_revision=note['revision'],
                base_hash=note['base_hash'],base_content=note['base_content'],title=note['title'],
                edits=[dict(id=note['blocks'][0]['id'],text=text)],additions=[],attachments=note['attachments'])

def test_auth_no_plaintext_revoke_expiry_throttle(tmp_path):
    auth=Auth(tmp_path/'auth.db'); auth.set_password('owner','a-long-password-42')
    token=auth.login('owner','a-long-password-42','phone','test')
    assert auth.verify(token)
    assert token not in str(auth.db.execute('SELECT * FROM sessions').fetchall())
    assert b'a-long-password-42' not in (tmp_path/'auth.db').read_bytes()
    auth.revoke(token); assert not auth.verify(token)
    for _ in range(5):
        with pytest.raises(PermissionError):auth.login('owner','wrong','p','test')
    with pytest.raises(PermissionError,match='1분'):auth.login('owner','a-long-password-42','p','test')

def test_patch_preserves_unedited_rich_text_and_ids(app):
    html='<html><head></head><body><h1>제목</h1><p>본문</p><p><b>굵은 글씨</b></p><p>▾ 토글</p><p style="-qt-block-indent:1">자식</p></body></html>'
    canonical,b=decode(html)
    result=patch(canonical,[dict(id=b[1]['id'],text='바뀐 본문'),dict(id=b[0]['id'],closed=True)],[])
    _,after=decode(result)
    assert [r['id'] for r in after]==[r['id'] for r in b]
    assert after[1]['text']=='바뀐 본문' and after[2]['text']=='굵은 글씨'
    assert 'font-weight:700' in result
    assert after[0]['closed']
    assert after[4]['indent']==1

def test_sync_roundtrip_idempotency_conflict(service):
    n=service.snapshot()['notes'][0]; c=change(n)
    r=service.apply(c); assert not r['conflict']
    assert service.apply(c)==r
    assert service.store.conn.execute('SELECT COUNT(*) FROM notes').fetchone()[0]==1
    assert service.snapshot()['notes'][0]['blocks'][0]['text']=='모바일 수정'
    conflict=service.apply(change(n,'오프라인 변경'))
    assert conflict['conflict']
    assert service.store.conn.execute('SELECT COUNT(*) FROM notes').fetchone()[0]==2
    assert {n['blocks'][0]['text'] for n in service.snapshot()['notes']}=={'모바일 수정','오프라인 변경'}

def test_busy_pc_creates_copy(service):
    n=service.snapshot()['notes'][0]; service.busy=lambda:{n['id']}
    assert service.apply(change(n))['conflict']

def test_deleted_pc_note_recovers_mobile_copy(service):
    n=service.snapshot()['notes'][0]
    service.store.conn.execute('DELETE FROM notes WHERE id=?',(n['id'],)); service.store.conn.commit()
    result=service.apply(change(n,'삭제 중 작성한 내용'))
    assert result['conflict'] and result['sync_id']!=n['sync_id']
    assert service.snapshot()['notes'][0]['blocks'][0]['text']=='삭제 중 작성한 내용'

def test_image_and_table_are_readonly_and_attachment_copies(service):
    import base64
    nid=service.store.conn.execute('SELECT id FROM notes').fetchone()[0]
    aid=service.store.add_attachment(nid,'image/png',base64.b64encode(b'image-fixture').decode(),1,1)
    service.store.update_note(nid,content=f'<html><head></head><body><p>Text</p><p><img src="toma-note-image://{aid}" /></p><table><tr><td>cell</td></tr></table></body></html>')
    n=service.snapshot()['notes'][0]
    assert any(b['readonly'] and b['images'] for b in n['blocks'])
    service.busy=lambda:{nid}
    r=service.apply(change(n))
    assert r['conflict']
    copy=next(n for n in service.snapshot()['notes'] if n['sync_id']==r['sync_id'])
    assert len(copy['attachments'])==1 and copy['attachments'][0]['id']!=aid
    assert f"toma-note-image://{copy['attachments'][0]['id']}" in copy['content']

def test_duplicate_op_cannot_change_payload(service):
    n=service.snapshot()['notes'][0]; c=change(n); service.apply(c)
    c['title']='changed'
    with pytest.raises(ValueError):service.apply(c)

def test_no_auth_no_data_and_wrong_server_no_write(service,tmp_path):
    auth=Auth(tmp_path/'auth.db'); auth.set_password('owner','password-long-enough')
    req=Request('/sync',{},'bad','test'); dispatch(req,auth,service); assert req.result[0]==401
    token=auth.login('owner','password-long-enough','phone','test')
    req=Request('/sync',dict(server_id='wrong',changes=[change(service.snapshot()['notes'][0])]),token,'test')
    dispatch(req,auth,service); assert req.result[0]==400
    assert service.store.conn.execute('SELECT revision FROM notes').fetchone()[0]==1

def test_https_end_to_end(service,tmp_path):
    auth=Auth(tmp_path/'auth.db'); auth.set_password('owner','password-long-enough')
    cert,key,pin=certificate(tmp_path)
    assert len(pin)==64
    server=BridgeServer(('127.0.0.1',0),str(cert),str(key))
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    results=[]
    def client():
        context=ssl.create_default_context(cafile=str(cert)); context.check_hostname=False
        address=f'https://127.0.0.1:{server.server_port}'
        def post(path,body,token=''):
            req=urllib.request.Request(address+path,json.dumps(body).encode(),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            with urllib.request.urlopen(req,context=context,timeout=10) as r:return json.load(r)
        token=post('/login',dict(username='owner',password='password-long-enough'))['token']
        snapshot=post('/sync',{},token)
        result=post('/sync',{'changes':[change(snapshot['notes'][0])]},token)
        results.append(result)
    worker=threading.Thread(target=client); worker.start()
    deadline=time.time()+20
    while worker.is_alive() and time.time()<deadline:
        try: req=server.requests.get(timeout=.1)
        except Exception:continue
        dispatch(req,auth,service)
    worker.join(timeout=1); server.shutdown(); server.server_close()
    assert results and results[0]['notes'][0]['blocks'][0]['text']=='모바일 수정'
