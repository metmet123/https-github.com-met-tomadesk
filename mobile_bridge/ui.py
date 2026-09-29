from __future__ import annotations
import ipaddress
import json
import queue
import subprocess
import threading
from pathlib import Path
from PyQt6.QtCore import QObject,QTimer
from PyQt6.QtWidgets import QApplication,QDialog,QFormLayout,QLineEdit,QPushButton,QLabel,QMessageBox,QVBoxLayout,QHBoxLayout
from .security import Auth,certificate
from .service import MobileService
from .server import BridgeServer,dispatch


def mobile_url(host: str) -> str:
    ip = ipaddress.ip_address(host.strip())
    if ip.version != 4 or not (ip.is_loopback or ip in ipaddress.ip_network('100.64.0.0/10')):
        raise ValueError('PC의 Tailscale IPv4 주소를 입력하세요.')
    return f'https://{ip}:47831'


class MobileController(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window; self.panel=window.alert_panel; self.server=None
        # Device credentials must not be placed in the shared/backup data folder.
        from storage_config import user_storage_root
        self.root=user_storage_root()/'mobile-security'; self.root.mkdir(parents=True,exist_ok=True)
        self.auth=Auth(self.root/'auth.db')
        self.cert,self.key,self.fingerprint=certificate(self.root)
        self.service=MobileService(window.note_store,self.busy)
        self.timer=QTimer(self); self.timer.setInterval(80); self.timer.timeout.connect(self.process)
        button=QPushButton('휴대폰 연결 · 로그인'); button.setObjectName('mobileConnectButton'); button.clicked.connect(self.settings)
        window.statusBar().addPermanentWidget(button)
        QApplication.instance().aboutToQuit.connect(self.stop)

    def busy(self):
        p=self.panel; result=set()
        editors=[(p.current_id,p.editor)]
        if p.standalone_window: editors.append((p.standalone_window.note_id,p.standalone_window.editor))
        for nid,e in editors:
            row=p.store.note(nid) if nid else None
            if nid and (e.save_timer.isActive() or e.content_edit.document().isModified() or (row and e.title_edit.text()!=row['title'])): result.add(nid)
        # Open post-its can contain edits outside the main editor. Preserve both copies.
        result.update(p.postits.keys())
        return result

    def process(self):
        if not self.server: return
        try: req=self.server.requests.get_nowait()
        except queue.Empty: return
        dispatch(req,self.auth,self.service)
        if req.path=='/sync' and req.result[0]==200 and req.body.get('changes'):
            p=self.panel
            p.list_panel.set_rows(p.store.notes(p.list_panel.search.text()),p.current_id)
            if p.current_id and p.current_id not in self.busy(): p.editor.set_note(p.store.note(p.current_id))
            if p.standalone_window and p.standalone_window.note_id not in self.busy():
                p.standalone_window.editor.set_note(p.store.note(p.standalone_window.note_id))

    def settings(self):
        self.connection_dialog().exec()

    def connection_dialog(self):
        dialog=QDialog(self.window); dialog.setObjectName('mobileConnectionDialog'); dialog.setWindowTitle('토마 모바일 연결 · 0.1.2'); dialog.resize(720,580)
        layout=QVBoxLayout(dialog)
        layout.setContentsMargins(24,20,24,20); layout.setSpacing(12)
        title=QLabel('내 메모를 휴대폰에서도'); title.setObjectName('mobileConnectionTitle'); layout.addWidget(title)
        hint=QLabel('두 기기에서 Tailscale을 켠 뒤 계정을 설정하고 연결을 시작하세요.'); hint.setObjectName('mobileConnectionHint'); hint.setWordWrap(True); layout.addWidget(hint)
        form=QFormLayout(); layout.addLayout(form)
        address=QLineEdit('127.0.0.1')
        try:
            binary=Path('C:/Program Files/Tailscale/tailscale.exe')
            if binary.exists():
                out=subprocess.run([str(binary),'ip','-4'],capture_output=True,text=True,timeout=3,creationflags=0x08000000)
                address.setText(out.stdout.strip().splitlines()[0])
        except (OSError,subprocess.SubprocessError,IndexError): pass
        if self.server: address.setText(self.server.server_address[0])
        username=QLineEdit(); password=QLineEdit(); password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('PC Tailscale IPv4',address); form.addRow('로그인 아이디',username); form.addRow('새 비밀번호 (12자 이상)',password)
        fp=QLineEdit(self.fingerprint); fp.setReadOnly(True)
        fp_row=QHBoxLayout(); fp_row.addWidget(fp); fp_copy=QPushButton('지문 복사'); fp_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.fingerprint)); fp_row.addWidget(fp_copy); form.addRow('인증서 지문',fp_row)
        url=QLineEdit(); url.setReadOnly(True); url.setObjectName('mobileConnectionUrl'); url.setPlaceholderText('올바른 PC IP를 입력하면 주소가 표시됩니다.')
        url_copy=QPushButton('주소 복사'); url_copy.setObjectName('primaryButton'); url_copy.clicked.connect(lambda: QApplication.clipboard().setText(url.text()))
        url_row=QHBoxLayout(); url_row.addWidget(url); url_row.addWidget(url_copy); form.addRow('휴대폰에 입력할 주소',url_row)
        def update_url():
            try:
                host=self.server.server_address[0] if self.server else address.text()
                url.setText(mobile_url(host)); url_copy.setEnabled(True)
            except ValueError:
                url.clear(); url_copy.setEnabled(False)
        address.textChanged.connect(update_url); update_url()
        help_text=QLabel('위 주소를 https://부터 포트 번호까지 그대로 입력하세요.\n127.0.0.1은 PC 내부 시험 전용이며, 휴대폰에는 PC의 100.x.x.x 주소를 사용합니다.'); help_text.setWordWrap(True); help_text.setObjectName('mobileConnectionHint'); layout.addWidget(help_text)
        status=QLabel('연결 중' if self.server else '연결 꺼짐 · 계정 설정됨' if self.auth.configured() else '계정 설정 필요'); status.setWordWrap(True); layout.addWidget(status)
        def reset():
            try:
                self.auth.set_password(username.text(),password.text()); password.clear()
                status.setText('계정을 저장했습니다. 기존 휴대폰 로그인은 해제되었습니다.')
            except ValueError as e: QMessageBox.warning(dialog,'계정 설정',str(e))
        def start():
            try:
                host=address.text().strip(); mobile_url(host)
                if not self.auth.configured(): raise ValueError('먼저 로그인 계정을 설정하세요.')
                self.stop(); self.server=BridgeServer((host,47831),str(self.cert),str(self.key))
                threading.Thread(target=self.server.serve_forever,daemon=True).start(); self.timer.start(); update_url()
                status.setText(f'연결 중: https://{host}:47831\nPC를 종료하면 동기화가 중단됩니다. 다음 실행 시 연결을 다시 켜세요.')
            except (OSError,ValueError) as e: QMessageBox.warning(dialog,'연결 시작',str(e))
        for label,callback in [('계정 저장 / 비밀번호 변경',reset),('연결 시작',start),('모든 휴대폰 로그아웃',lambda:(self.auth.revoke(),status.setText('모든 접속 토큰을 취소했습니다.'))),('연결 중지',lambda:(self.stop(),update_url(),status.setText('연결 꺼짐')))]:
            b=QPushButton(label); b.clicked.connect(callback); layout.addWidget(b)
        return dialog

    def stop(self):
        self.timer.stop()
        if self.server:
            self.server.shutdown(); self.server.server_close(); self.server=None
