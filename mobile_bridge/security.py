from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


class Auth:
    """One locally provisioned owner; only token digests are persisted."""
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS owner(name TEXT,salt BLOB,digest BLOB)')
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions(digest TEXT PRIMARY KEY,device TEXT,expires REAL)')
        self.failures = {}

    def configured(self):
        return self.db.execute('SELECT 1 FROM owner').fetchone() is not None

    def set_password(self, name, password):
        if not name.strip() or len(password) < 12 or len(password) > 256:
            raise ValueError('아이디와 12~256자 비밀번호를 입력하세요.')
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
        with self.db:
            self.db.execute('DELETE FROM owner')
            self.db.execute('INSERT INTO owner VALUES(?,?,?)', (name.strip(), salt, digest))
            self.db.execute('DELETE FROM sessions')

    def login(self, name, password, device, address):
        now = time.time()
        # Single owner: global limit also stops distributed password guessing.
        recent = [t for t in self.failures.get('all', []) if now-t < 60]
        self.failures['all'] = recent
        if len(recent) >= 5:
            raise PermissionError('로그인 시도가 많습니다. 1분 후 다시 시도하세요.')
        row = self.db.execute('SELECT name,salt,digest FROM owner').fetchone()
        digest = hashlib.scrypt(str(password).encode(), salt=row[1] if row else b'0'*16, n=16384,r=8,p=1)
        if not row or not hmac.compare_digest(str(name).encode(), row[0].encode()) or not hmac.compare_digest(digest,row[2]):
            recent.append(now)
            raise PermissionError('아이디 또는 비밀번호를 확인하세요.')
        token = secrets.token_urlsafe(32)
        with self.db:
            self.db.execute('DELETE FROM sessions WHERE expires < ?', (now,))
            self.db.execute('INSERT INTO sessions VALUES(?,?,?)', (self.digest(token),str(device)[:100],now+30*86400))
        return token

    @staticmethod
    def digest(token):
        return hashlib.sha256(str(token).encode()).hexdigest()

    def verify(self, token):
        return self.db.execute('SELECT device FROM sessions WHERE digest=? AND expires>?',
                               (self.digest(token),time.time())).fetchone() is not None

    def revoke(self, token=None):
        with self.db:
            if token is None:
                self.db.execute('DELETE FROM sessions')
            else:
                self.db.execute('DELETE FROM sessions WHERE digest=?',(self.digest(token),))


def certificate(directory: Path):
    cert_path, key_path = directory/'server.pem', directory/'server-key.pem'
    if not cert_path.exists() or not key_path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'TomaDesk Mobile')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
                .not_valid_after(now+timedelta(days=3650)).sign(key,hashes.SHA256()))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return cert_path,key_path,cert.fingerprint(hashes.SHA256()).hex().upper()
