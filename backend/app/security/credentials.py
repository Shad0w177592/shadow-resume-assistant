from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Protocol

TARGET = "ShadowResumeAssistant/OpenAI"


class CredentialStore(Protocol):
    def get(self) -> str | None: ...
    def set(self, secret: str) -> None: ...
    def delete(self) -> None: ...


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self.value: str | None = None

    def get(self) -> str | None:
        return self.value

    def set(self, secret: str) -> None:
        self.value = secret

    def delete(self) -> None:
        self.value = None


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self, target: str = TARGET) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows Credential Manager is only available on Windows")
        self.target = target
        self.advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)

    def get(self) -> str | None:
        pointer = ctypes.POINTER(CREDENTIALW)()
        ok = self.advapi32.CredReadW(
            self.target, self.CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
        )
        if not ok:
            if ctypes.get_last_error() == self.ERROR_NOT_FOUND:
                return None
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            credential = pointer.contents
            blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return blob.decode("utf-16-le")
        finally:
            self.advapi32.CredFree(pointer)

    def set(self, secret: str) -> None:
        encoded = secret.encode("utf-16-le")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = CREDENTIALW()
        credential.Type = self.CRED_TYPE_GENERIC
        credential.TargetName = self.target
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "ShadowResumeAssistant"
        if not self.advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def delete(self) -> None:
        if self.advapi32.CredDeleteW(self.target, self.CRED_TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != self.ERROR_NOT_FOUND:
            raise ctypes.WinError(error)
