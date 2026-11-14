"""本地数据加密：DPAPI 保护随机主密钥，AES-256-GCM 加密配置与历史字段。

安全边界：
- 主密钥 32 字节随机数，只以 Windows DPAPI 密文保存在 `secret.key`；
- 配置整体加密为 `config.dat`，不再出现明文 `config.json`；
- 历史数据库中的会话标题、消息正文、工具参数、文件路径等字段逐条加密；
- 数据绑定当前 Windows 账户与电脑。复制到其他账户/电脑时 DPAPI 无法解密，
  程序会备份旧数据并重新初始化，不会静默覆盖。
"""
from __future__ import annotations

import base64
import ctypes
import logging
import os
import secrets as _secrets
import tempfile
from ctypes import wintypes
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("nexus.secret")

_ENTROPY = b"Nexus.Secret.v1"
KEY_MAGIC = b"NXKEY1"
CONFIG_MAGIC = b"NXCFG1"
FIELD_PREFIX = "enc:v1:"
_KEY_LEN = 32
_NONCE_LEN = 12


class SecretError(Exception):
    """DPAPI 或数据解密失败。"""


class KeyUnreadable(SecretError):
    """密钥文件存在，但不属于当前 Windows 账户/电脑。"""


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def dpapi_encrypt(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecretError("DPAPI 仅支持 Windows")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in, _keep = _blob(data)
    blob_ent, _keep2 = _blob(_ENTROPY)
    blob_out = _BLOB()
    fn = crypt32.CryptProtectData
    fn.argtypes = [
        ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB),
    ]
    fn.restype = wintypes.BOOL
    ok = fn(ctypes.byref(blob_in), None, ctypes.byref(blob_ent),
            None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise SecretError("系统加密失败（DPAPI）")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def dpapi_decrypt(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecretError("DPAPI 仅支持 Windows")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in, _keep = _blob(data)
    blob_ent, _keep2 = _blob(_ENTROPY)
    blob_out = _BLOB()
    fn = crypt32.CryptUnprotectData
    fn.argtypes = [
        ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB),
    ]
    fn.restype = wintypes.BOOL
    ok = fn(ctypes.byref(blob_in), None, ctypes.byref(blob_ent),
            None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise SecretError("系统解密失败（DPAPI）")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


class SecretBox:
    """主密钥容器。密钥文件只保存 DPAPI 密文。"""

    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.key_path = self.dir / "secret.key"
        self._key = self._load_or_create()

    def _load_or_create(self) -> bytes:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise SecretError(f"无法创建数据目录：{e}") from e
        if self.key_path.exists():
            raw = self.key_path.read_bytes()
            if not raw.startswith(KEY_MAGIC):
                raise KeyUnreadable("密钥文件格式不正确")
            try:
                key = dpapi_decrypt(raw[len(KEY_MAGIC):])
            except SecretError as e:
                raise KeyUnreadable("密钥不属于当前 Windows 账户或电脑") from e
            if len(key) != _KEY_LEN:
                raise KeyUnreadable("密钥长度异常")
            return key
        key = _secrets.token_bytes(_KEY_LEN)
        self._write_key(key)
        return key

    def _write_key(self, key: bytes) -> None:
        blob = KEY_MAGIC + dpapi_encrypt(key)
        fd, tmp = tempfile.mkstemp(dir=str(self.dir), prefix=".key-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
            os.replace(tmp, self.key_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # ---------- 通用加解密 ----------
    def encrypt_bytes(self, raw: bytes, magic: bytes = CONFIG_MAGIC) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        ct = AESGCM(self._key).encrypt(nonce, raw, magic)
        return magic + nonce + ct

    def decrypt_bytes(self, blob: bytes, magic: bytes = CONFIG_MAGIC) -> bytes:
        if not blob.startswith(magic):
            raise SecretError("加密文件格式不正确")
        body = blob[len(magic):]
        if len(body) <= _NONCE_LEN:
            raise SecretError("加密文件已损坏")
        nonce, ct = body[:_NONCE_LEN], body[_NONCE_LEN:]
        try:
            return AESGCM(self._key).decrypt(nonce, ct, magic)
        except Exception as e:  # InvalidTag 等
            raise SecretError("数据解密失败，文件可能被篡改或损坏") from e

    # ---------- 字段加解密 ----------
    def encrypt_text(self, text: str | None) -> str | None:
        if text is None:
            return None
        raw = str(text).encode("utf-8")
        nonce = os.urandom(_NONCE_LEN)
        ct = AESGCM(self._key).encrypt(nonce, raw, None)
        return FIELD_PREFIX + base64.b64encode(nonce + ct).decode("ascii")

    def decrypt_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value)
        if not text.startswith(FIELD_PREFIX):
            return text  # 兼容早期明文数据
        try:
            body = base64.b64decode(text[len(FIELD_PREFIX):])
            nonce, ct = body[:_NONCE_LEN], body[_NONCE_LEN:]
            return AESGCM(self._key).decrypt(nonce, ct, None).decode("utf-8")
        except Exception:
            log.warning("历史字段解密失败，已用占位符代替")
            return "（此条数据无法解密）"

    @staticmethod
    def is_encrypted(value) -> bool:
        return isinstance(value, str) and value.startswith(FIELD_PREFIX)
