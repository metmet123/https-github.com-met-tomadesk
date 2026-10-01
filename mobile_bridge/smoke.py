"""Packaged executable smoke check, isolated from user data and Windows hooks."""
import json
import tempfile
from pathlib import Path
from uuid import uuid4
from PyQt6.QtGui import QPixmap
from alert_notes.sqlite_store import NoteReminderStore
from alert_notes.toma_pet_assets import asset_directory
from .service import MobileService
from .security import Auth,certificate
from .pairing import pairing_payload,pairing_qr

def run(output):
    result={}
    try:
        with tempfile.TemporaryDirectory(prefix='toma-mobile-smoke-') as d:
            root=Path(d); store=NoteReminderStore(root/'notes.db')
            store.create_note('테스트','오프라인 메모')
            service=MobileService(store); note=service.snapshot()['notes'][0]
            service.apply(dict(op_id=str(uuid4()),sync_id=note['sync_id'],base_revision=note['revision'],
                base_hash=note['base_hash'],base_content=note['base_content'],title='수정',edits=[],additions=[]))
            latest=service.snapshot()['notes'][0]
            markdown='# Markdown 시험\n\n**토마**와 함께 기록합니다.\n'
            service.apply(dict(op_id=str(uuid4()),sync_id=latest['sync_id'],base_revision=latest['revision'],
                base_hash=latest['base_hash'],base_content=latest['base_content'],title=latest['title'],markdown=markdown,attachments=[]))
            assert next(n for n in service.snapshot()['notes'] if n['sync_id']==latest['sync_id'])['markdown']==markdown
            auth=Auth(root/'auth.db'); auth.set_password('test','isolated-test-password')
            assert auth.verify(auth.login('test','isolated-test-password','test','local'))
            assert len(certificate(root)[2])==64
            qr=pairing_qr(pairing_payload('https://100.84.171.16:47831','A'*64))
            assert not qr.isNull()
            assert not QPixmap(str(asset_directory()/'spritesheet.webp')).isNull()
            result=dict(ok=True,checks=['sqlite','qt-codec','mobile-save','password-login','tls-certificate','qr-pairing','toma-assets','markdown-roundtrip'])
            from app_config import APP_VERSION
            from alert_notes.panel import AlertNotesPanel
            from PyQt6.QtCore import QEvent
            from PyQt6.QtWidgets import QApplication
            store.set_setting('memo_auto_save_enabled','false')
            panel=AlertNotesPanel(store)
            panel.editor.title_edit.setText('보존할 초안')
            panel.list_panel.search.setText('결과 없음')
            panel._refresh_search()
            assert panel.editor.title_edit.text()=='보존할 초안'
            assert panel.list_panel.row_count()==0
            panel.shutdown();panel.deleteLater()
            QApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            result['version']=APP_VERSION
            result['checks'].append('search-preserves-draft')
            auth.db.close();store.conn.close()
    except Exception as e:
        result=dict(ok=False,error=repr(e))
    Path(output).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    return 0 if result['ok'] else 1
