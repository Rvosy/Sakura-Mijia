from __future__ import annotations

import ctypes
import json
import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    """Use the current Windows user's DPAPI; never silently fall back to plaintext."""
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


class Vault:
    def __init__(self, root: Path):
        self.path = root / ("account.dpapi" if os.name == "nt" else "account.json")

    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> dict:
        if not self.exists():
            return {}
        data = self.path.read_bytes()
        if os.name == "nt":
            data = dpapi(data, decrypt=True)
        return json.loads(data)

    def save(self, value: dict) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        atomic_write(self.path, dpapi(data) if os.name == "nt" else data)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
