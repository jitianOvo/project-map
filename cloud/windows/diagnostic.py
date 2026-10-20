from pathlib import Path
import ctypes
import json
import sys


def probe():
    root=Path(sys._MEIPASS)
    ctypes.windll.kernel32.GetModuleHandleW.restype=ctypes.c_void_p
    ctypes.windll.kernel32.GetModuleHandleW.argtypes=[ctypes.c_wchar_p]
    ctypes.windll.kernel32.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint]
    modules=[]
    for name in ("python311.dll","python3.dll","VCRUNTIME140.dll","VCRUNTIME140_1.dll","MSVCP140.dll"):
        handle=ctypes.windll.kernel32.GetModuleHandleW(name)
        if handle:
            path=ctypes.create_unicode_buffer(4096)
            ctypes.windll.kernel32.GetModuleFileNameW(handle,path,len(path))
            modules.append({"name":name,"loaded":path.value})
    for relative in ("python3.dll","shiboken6/shiboken6.abi3.dll","PySide6/Qt6Core.dll","PySide6/pyside6.abi3.dll","PySide6/QtCore.pyd"):
        try:
            ctypes.WinDLL(str(root/relative))
            modules.append({"file":relative,"ok":True})
        except OSError as error:
            modules.append({"file":relative,"error":str(error)})
    print(json.dumps(modules,ensure_ascii=False))
