"""Local emulator test server. Only synthetic data; never uses the user's DB."""
import json
import secrets
import sys
import threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from alert_notes.sqlite_store import NoteReminderStore
from mobile_bridge.security import Auth,certificate
from mobile_bridge.service import MobileService
from mobile_bridge.server import BridgeServer,dispatch

root=Path(sys.argv[1]); root.mkdir(parents=True,exist_ok=True)
app=QApplication([])
store=NoteReminderStore(root/'fixture.db')
if not store.notes():
    store.create_note('연동 시험','<html><head></head><body><h1>접기 시험</h1><p>둘째 줄</p><p>PC와 모바일의 자료를 안전하게 연결합니다.</p></body></html>')
auth=Auth(root/'auth.db'); password=secrets.token_urlsafe(24); auth.set_password('qa',password)
cert,key,pin=certificate(root)
(root/'fixture.json').write_text(json.dumps(dict(pin=pin,password=password)),encoding='utf-8')
server=BridgeServer(('127.0.0.1',int(sys.argv[2]) if len(sys.argv)>2 else 47832),str(cert),str(key)); threading.Thread(target=server.serve_forever,daemon=True).start()
service=MobileService(store)
if '--legacy' in sys.argv:
    snapshot=service.snapshot
    def legacy_snapshot():
        data=snapshot(); data.pop('capabilities',None)
        for n in data['notes']:
            n.pop('markdown',None);n.pop('markdown_native',None)
        return data
    service.snapshot=legacy_snapshot
def process():
    import queue
    try:r=server.requests.get_nowait()
    except queue.Empty:return
    dispatch(r,auth,service)
timer=QTimer(); timer.timeout.connect(process); timer.start(30)
app.exec()
