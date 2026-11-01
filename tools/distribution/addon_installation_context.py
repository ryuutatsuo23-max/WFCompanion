"""Read-only Windows identity checks for the isolated configuration authority.

The current process account is the only supported intended user. Elevated setup,
impersonation and delegation require a separate reviewed handoff, not a guess at
the desktop owner. No profile contents, ACLs or environment strings prove identity.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re


class UserContextError(ValueError):
    def __init__(self, code='user_unverified'):
        self.code = code
        super().__init__('Windows user context could not be verified.' if code == 'user_unverified'
                         else 'Windows user context conflicts with the confirmed configuration.')


@dataclass(frozen=True)
class WindowsUserContext:
    sid: str = field(repr=False)
    local_app_data: Path = field(repr=False)
    elevated: bool
    session_id: int


def current_windows_context():
    """Query token and Known Folder APIs only; never create/open Companion data.

    Reject any thread impersonation, including same-account impersonation. The
    known folder is queried with DONT_VERIFY (not CREATE); filesystem validation
    is performed separately against the pinned directory by configuration code.
    """
    if os.name != 'nt':
        raise UserContextError()
    import ctypes as c
    from ctypes import wintypes as w
    import uuid
    kernel = c.WinDLL('kernel32', use_last_error=True)
    advapi = c.WinDLL('advapi32', use_last_error=True)
    shell = c.WinDLL('shell32', use_last_error=True)
    ole = c.WinDLL('ole32')
    kernel.GetCurrentProcess.restype = kernel.GetCurrentThread.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    kernel.LocalFree.argtypes = [c.c_void_p]
    kernel.LocalFree.restype = c.c_void_p
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    advapi.OpenProcessToken.restype = w.BOOL
    advapi.OpenThreadToken.argtypes = [w.HANDLE, w.DWORD, w.BOOL, c.POINTER(w.HANDLE)]
    advapi.OpenThreadToken.restype = w.BOOL
    advapi.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    advapi.GetTokenInformation.restype = w.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(w.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = w.BOOL
    shell.SHGetKnownFolderPath.argtypes = [c.c_void_p, w.DWORD, w.HANDLE, c.POINTER(w.LPWSTR)]
    shell.SHGetKnownFolderPath.restype = c.c_long
    ole.CoTaskMemFree.argtypes = [c.c_void_p]
    ole.CoTaskMemFree.restype = None
    token = w.HANDLE()
    thread = w.HANDLE()
    if advapi.OpenThreadToken(kernel.GetCurrentThread(), 8, True, c.byref(thread)):
        kernel.CloseHandle(thread)
        raise UserContextError()
    if c.get_last_error() != 1008:  # ERROR_NO_TOKEN is the only accepted absence.
        raise UserContextError()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, c.byref(token)):
        raise UserContextError()
    try:
        def information(kind):
            length = w.DWORD()
            advapi.GetTokenInformation(token, kind, None, 0, c.byref(length))
            # Fixed-size classes can report ERROR_BAD_LENGTH rather than
            # ERROR_INSUFFICIENT_BUFFER during the initial size query.
            if c.get_last_error() not in (24, 122) or not 4 <= length.value <= 65536:
                raise UserContextError()
            data = c.create_string_buffer(length.value)
            if not advapi.GetTokenInformation(token, kind, data, len(data), c.byref(length)):
                raise UserContextError()
            return data
        user = information(1)  # TOKEN_USER begins with SID_AND_ATTRIBUTES.Sid.
        if len(user) < c.sizeof(c.c_void_p):
            raise UserContextError()
        sid = w.LPWSTR()
        if not advapi.ConvertSidToStringSidW(c.c_void_p.from_buffer(user), c.byref(sid)):
            raise UserContextError()
        try:
            sid_text = sid.value
        finally:
            kernel.LocalFree(c.cast(sid, c.c_void_p))
        elevated = bool(w.DWORD.from_buffer(information(20)).value)
        session = w.DWORD.from_buffer(information(12)).value
        folder = w.LPWSTR()
        guid = c.create_string_buffer(uuid.UUID('F1B32785-6FBA-4FCF-9D55-7B8E7F157091').bytes_le)
        try:
            if shell.SHGetKnownFolderPath(guid, 0x4000, None, c.byref(folder)) < 0:
                raise UserContextError()
            path = Path(folder.value)
        finally:
            ole.CoTaskMemFree(c.cast(folder, c.c_void_p))
        return WindowsUserContext(sid_text, path, elevated, session)
    finally:
        kernel.CloseHandle(token)


def validate_context(context, *, intended_sid=None, launch_context='current_user'):
    """The caller supplies intent; no setup/alternate-user inference is allowed."""
    if (launch_context != 'current_user' or not isinstance(context, WindowsUserContext)
            or not re.fullmatch(r'S-1-\d+(?:-\d+){1,15}', context.sid)
            or context.sid in ('S-1-5-18', 'S-1-5-19', 'S-1-5-20')
            or type(context.elevated) is not bool or context.elevated
            or type(context.session_id) is not int or context.session_id <= 0
            or not context.local_app_data.is_absolute()):
        raise UserContextError()
    if intended_sid is not None and context.sid != intended_sid:
        raise UserContextError('user_conflict')
    return context
