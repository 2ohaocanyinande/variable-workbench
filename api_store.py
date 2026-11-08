"""Current-user Windows DPAPI storage. Never writes a plaintext fallback."""
import ctypes
from ctypes import wintypes
import json
import os


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    if os.name != 'nt': raise ValueError('加密保存目前只支持 Windows')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p if decrypt else wintypes.LPCWSTR,
                         ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    description = None if decrypt else 'VariableWorkbench API settings'
    if not function(ctypes.byref(source), description, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('Windows 无法加密／解密此设置，请在原 Windows 账户下重试；不会明文保存 Key')
    free = ctypes.WinDLL('kernel32').LocalFree
    free.argtypes = [ctypes.c_void_p]; free.restype = ctypes.c_void_p
    try: return ctypes.string_at(target.data, target.size)
    finally: free(ctypes.cast(target.data, ctypes.c_void_p))


def save(path, settings):
    encoded = crypt(json.dumps(settings, ensure_ascii=False).encode('utf-8'))
    if len(encoded) > 65536: raise ValueError('API 设置过长，无法保存')
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(encoded)
    os.replace(temporary, path)


def load(path):
    if not path.is_file(): return {}
    if path.stat().st_size > 65536: raise ValueError('加密设置文件过大，请清除后重新配置')
    result = json.loads(crypt(path.read_bytes(), decrypt=True).decode('utf-8'))
    if not isinstance(result, dict) or not all(isinstance(result.get(k), str) for k in ('url','model','key')):
        raise ValueError('加密设置格式无效，请重新配置')
    return result
