import ctypes


ERROR_ALREADY_EXISTS = 183


class SingleInstanceGuard:
    """Windows 명명 뮤텍스로 프로그램 중복 실행을 방지한다."""

    def __init__(self, name: str):
        self.name = name
        self._handle = None
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        self._kernel32.CreateMutexW.restype = ctypes.c_void_p
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    def acquire(self) -> bool:
        if self._handle:
            return True
        ctypes.set_last_error(0)
        handle = self._kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            self._kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("이미 실행 중입니다.")
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.release()
