from __future__ import annotations
import ipaddress
import queue
import socket
import threading
from PyQt6.QtCore import QObject,QTimer,Qt
from PyQt6.QtWidgets import QApplication,QDialog,QFormLayout,QLineEdit,QPushButton,QLabel,QMessageBox,QVBoxLayout,QHBoxLayout,QSizePolicy
from .pairing import pairing_payload,pairing_qr
from .service import MobileService
from .server import BridgeServer,dispatch


def mobile_url(host: str) -> str:
    ip = ipaddress.ip_address(host.strip())
    if ip.version != 4 or ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        raise ValueError('휴대폰에서 접근할 수 있는 PC IPv4 주소를 찾지 못했습니다.')
    return f'http://{ip}:47831'


def pairing_host() -> str:
    """Prefer the PC's active local network; use Tailscale only as a fallback."""
    local_networks = tuple(ipaddress.IPv4Network(cidr) for cidr in
                           ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    candidates = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(('1.1.1.1', 53))
            active = connection.getsockname()[0]
            if any(ipaddress.IPv4Address(active) in network for network in local_networks):
                mobile_url(active)
                return active
            candidates.append(active)
    except (OSError, ValueError):
        pass
    try:
        candidates.extend(address[0] for _family,_type,_protocol,_name,address in
                          socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET))
    except OSError:
        pass
    for candidate in candidates:
        try:
            if any(ipaddress.IPv4Address(candidate) in network for network in local_networks):
                mobile_url(candidate)
                return candidate
        except ValueError:
            continue
    for candidate in candidates:
        try:
            mobile_url(candidate)
            return candidate
        except ValueError:
            continue
    raise ValueError('PC IPv4 주소를 찾지 못했습니다. PC와 휴대폰을 같은 Wi-Fi 또는 Tailscale에 연결하세요.')


class MobileController(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window; self.panel=window.alert_panel; self.server=None
        self.service=MobileService(window.note_store,self.busy)
        self.timer=QTimer(self); self.timer.setInterval(80); self.timer.timeout.connect(self.process)
        button=QPushButton('휴대폰연결',window); button.setObjectName('workspaceUtilityButton'); button.setToolTip('휴대폰 연결 QR 표시')
        button.setAccessibleName('휴대폰 연결'); button.setSizePolicy(QSizePolicy.Policy.Maximum,QSizePolicy.Policy.Fixed); button.clicked.connect(self.settings)
        # Keep connection with the always-visible top tools.  It sits immediately
        # left of Settings and uses the exact same button styling and height.
        settings_button=window.workspace_settings_button
        window.workspace_mode_layout.insertWidget(window.workspace_mode_layout.indexOf(settings_button),button)
        button.setFixedHeight(settings_button.sizeHint().height())
        self.button=button
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
        dispatch(req,self.service)
        if req.path=='/sync' and req.result[0]==200 and req.body.get('changes'):
            p=self.panel
            p.list_panel.set_rows(p.store.notes(p.list_panel.search.text()),p.current_id)
            if p.current_id and p.current_id not in self.busy(): p.editor.set_note(p.store.note(p.current_id))
            if p.standalone_window and p.standalone_window.note_id not in self.busy():
                p.standalone_window.editor.set_note(p.store.note(p.standalone_window.note_id))

    def settings(self):
        try:
            self.start()
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self.window,'휴대폰 연결',str(exc))
            return
        self.connection_dialog().exec()

    def start(self):
        if self.server:
            return
        host=pairing_host()
        self.server=BridgeServer((host,47831))
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.timer.start()

    def connection_dialog(self):
        dialog=QDialog(self.window); dialog.setObjectName('mobileConnectionDialog'); dialog.setWindowTitle('토마 모바일 연결'); dialog.resize(560,500)
        layout=QVBoxLayout(dialog)
        layout.setContentsMargins(24,20,24,20); layout.setSpacing(12)
        title=QLabel('내 메모를 휴대폰에서도'); title.setObjectName('mobileConnectionTitle'); layout.addWidget(title)
        hint=QLabel('휴대폰으로 QR을 인식하면 바로 연결됩니다. 같은 Wi-Fi 또는 Tailscale에 연결되어 있어야 합니다.'); hint.setObjectName('mobileConnectionHint'); hint.setWordWrap(True); layout.addWidget(hint)
        form=QFormLayout(); layout.addLayout(form)
        url=QLineEdit(); url.setReadOnly(True); url.setObjectName('mobileConnectionUrl'); url.setPlaceholderText('올바른 PC IP를 입력하면 주소가 표시됩니다.')
        url_copy=QPushButton('주소 복사'); url_copy.setObjectName('primaryButton'); url_copy.clicked.connect(lambda: QApplication.clipboard().setText(url.text()))
        url_row=QHBoxLayout(); url_row.addWidget(url); url_row.addWidget(url_copy); form.addRow('휴대폰에 입력할 주소',url_row)
        qr_row=QHBoxLayout(); layout.addLayout(qr_row)
        qr=QLabel('연결을 시작하면 QR이 표시됩니다.'); qr.setObjectName('mobilePairQr'); qr.setFixedSize(228,228)
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter); qr.setWordWrap(True); qr_row.addWidget(qr)
        qr_help=QLabel('기본 카메라가 토마 앱 열기를 제안하면 선택하세요.\n열리지 않으면 토마 모바일의 “PC QR 스캔” 또는 갤러리 사진 선택을 사용하면 됩니다.\n아이디·비밀번호·인증서 입력은 없습니다.')
        qr_help.setWordWrap(True); qr_row.addWidget(qr_help,1)
        def update_url():
            try:
                host=self.server.server_address[0] if self.server else pairing_host()
                url.setText(mobile_url(host)); url_copy.setEnabled(True)
            except ValueError:
                url.clear(); url_copy.setEnabled(False)
            if self.server:
                try:
                    qr.setPixmap(pairing_qr(pairing_payload(url.text())))
                    qr.setText('')
                    return
                except (ImportError, ValueError):
                    pass
            qr.clear(); qr.setText('QR을 표시할 수 없습니다.')
        update_url()
        status=QLabel(f'연결 중: {url.text()}\nPC 프로그램을 종료하면 동기화가 중단됩니다.'); status.setWordWrap(True); layout.addWidget(status)
        stop_button=QPushButton('연결 중지'); stop_button.clicked.connect(lambda:(self.stop(),dialog.accept())); layout.addWidget(stop_button)
        return dialog

    def stop(self):
        self.timer.stop()
        if self.server:
            self.server.shutdown(); self.server.server_close(); self.server=None
