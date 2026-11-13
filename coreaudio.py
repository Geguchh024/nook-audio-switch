"""Windows Core Audio through ctypes: no pywin32 or comtypes needed.

Lists render/capture endpoints, reads and sets the default device per role
(through the undocumented but long-stable IPolicyConfig interface that the
Sound control panel uses), reads/sets endpoint volume and mute, reads live
peak levels, and lists the per-app sessions of an endpoint with their own
volume, mute and level (the Volume Mixer).

All calls must come from the thread that called init()."""

import ctypes
import os
from ctypes import (POINTER, byref, c_float, c_int, c_uint, c_ulong, c_ushort, c_void_p,
                    c_wchar_p)

RENDER, CAPTURE = 0, 1
CONSOLE, MULTIMEDIA, COMMUNICATIONS = 0, 1, 2
ROLES = (CONSOLE, MULTIMEDIA, COMMUNICATIONS)
DEVICE_STATE_ACTIVE = 1
CLSCTX_ALL = 0x17
STGM_READ = 0
SESSION_EXPIRED = 2

ole32 = ctypes.WinDLL("ole32")
ole32.CoTaskMemFree.argtypes = [c_void_p]
ole32.PropVariantClear.argtypes = [c_void_p]
kernel32 = ctypes.WinDLL("kernel32")
kernel32.OpenProcess.restype = c_void_p
kernel32.OpenProcess.argtypes = [c_ulong, c_int, c_ulong]
kernel32.QueryFullProcessImageNameW.argtypes = [c_void_p, c_ulong, c_wchar_p, POINTER(c_ulong)]
kernel32.CloseHandle.argtypes = [c_void_p]
version = ctypes.WinDLL("version")
version.GetFileVersionInfoSizeW.argtypes = [c_wchar_p, c_void_p]
version.GetFileVersionInfoW.argtypes = [c_wchar_p, c_ulong, c_ulong, c_void_p]
version.VerQueryValueW.argtypes = [c_void_p, c_wchar_p, POINTER(c_void_p), POINTER(c_uint)]


class GUID(ctypes.Structure):
    _fields_ = [("d1", c_ulong), ("d2", c_ushort), ("d3", c_ushort), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        super().__init__()
        ole32.CLSIDFromString(c_wchar_p("{" + text.strip("{}") + "}"), byref(self))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_ulong)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                ("ptr", c_void_p), ("extra", c_void_p)]


CLSID_MMDeviceEnumerator = GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioEndpointVolume = GUID("5CDF2C82-841E-4546-9722-0CF74078229A")
IID_IAudioMeterInformation = GUID("C02216F6-8C67-4B5B-9D00-D008E73E0064")
IID_IAudioSessionManager2 = GUID("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")
IID_IAudioSessionControl2 = GUID("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")
IID_ISimpleAudioVolume = GUID("87CE5498-68D6-44E5-9215-6DA47EF883D8")
CLSID_PolicyConfig = GUID("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")
IID_IPolicyConfig = GUID("F8679F50-850A-41CF-9C72-430F290290C8")


def _key(fmtid, pid):
    k = PROPERTYKEY()
    k.fmtid = GUID(fmtid)
    k.pid = pid
    return k


PKEY_FriendlyName = _key("A45C254E-DF1C-4EFD-8020-67D146A850E0", 14)
PKEY_DeviceDesc = _key("A45C254E-DF1C-4EFD-8020-67D146A850E0", 2)
PKEY_InterfaceName = _key("026E516E-B814-414B-83CD-856D6FEF4822", 2)


def _call(ptr, index, *args, argtypes=()):
    """Calls method `index` of a COM object's vtable; raises OSError on failure."""
    vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtbl[index])
    return fn(ptr, *args)


def _release(ptr):
    if ptr:
        vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p)))[0]
        ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtbl[2])(ptr)


def _create(clsid, iid):
    p = c_void_p()
    ole32.CoCreateInstance(byref(clsid), None, CLSCTX_ALL, byref(iid), byref(p))
    return p


def _query(ptr, iid):
    out = c_void_p()
    _call(ptr, 0, byref(iid), byref(out), argtypes=(POINTER(GUID), POINTER(c_void_p)))
    return out


def _wstr_out(ptr, index):
    """A method that returns a CoTaskMem string through its only argument."""
    s = c_void_p()
    _call(ptr, index, byref(s), argtypes=(POINTER(c_void_p),))
    try:
        return ctypes.wstring_at(s.value) if s.value else ""
    finally:
        ole32.CoTaskMemFree(s)


_enum = None


def init():
    global _enum
    ole32.CoInitializeEx(None, 2)  # apartment threaded; S_FALSE if already done
    _enum = _create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)


def _device_id(dev):
    return _wstr_out(dev, 5)


def _string_prop(store, key):
    pv = PROPVARIANT()
    try:
        _call(store, 5, byref(key), byref(pv), argtypes=(POINTER(PROPERTYKEY), POINTER(PROPVARIANT)))
    except OSError:
        return ""
    try:
        return ctypes.wstring_at(pv.ptr) if pv.vt == 31 and pv.ptr else ""  # VT_LPWSTR
    finally:
        ole32.PropVariantClear(byref(pv))


def _names(dev):
    store = c_void_p()
    try:
        _call(dev, 4, STGM_READ, byref(store), argtypes=(c_ulong, POINTER(c_void_p)))
    except OSError:
        return "Unknown device", "", ""
    try:
        return (_string_prop(store, PKEY_FriendlyName), _string_prop(store, PKEY_DeviceDesc),
                _string_prop(store, PKEY_InterfaceName))
    finally:
        _release(store)


def default_id(flow, role=CONSOLE):
    dev = c_void_p()
    try:
        _call(_enum, 4, flow, role, byref(dev), argtypes=(c_uint, c_uint, POINTER(c_void_p)))
    except OSError:  # no device of this kind
        return None
    try:
        return _device_id(dev)
    finally:
        _release(dev)


def devices(flow):
    """Active endpoints: [{"id", "name", "desc", "adapter", "default", "calls"}].
    "default" is the console/media default, "calls" the communications one."""
    coll = c_void_p()
    _call(_enum, 3, flow, DEVICE_STATE_ACTIVE, byref(coll), argtypes=(c_uint, c_ulong, POINTER(c_void_p)))
    out = []
    try:
        n = c_uint()
        _call(coll, 3, byref(n), argtypes=(POINTER(c_uint),))
        for i in range(n.value):
            dev = c_void_p()
            _call(coll, 4, i, byref(dev), argtypes=(c_uint, POINTER(c_void_p)))
            try:
                name, desc, adapter = _names(dev)
                out.append({"id": _device_id(dev), "name": name or desc or "Audio device",
                            "desc": desc, "adapter": adapter})
            finally:
                _release(dev)
    finally:
        _release(coll)
    default, calls = default_id(flow), default_id(flow, COMMUNICATIONS)
    for d in out:
        d["default"] = d["id"] == default
        d["calls"] = d["id"] == calls
    return out


def set_default(device_id, roles=ROLES):
    """Makes the endpoint the default for the given roles (all by default)."""
    pc = _create(CLSID_PolicyConfig, IID_IPolicyConfig)
    try:
        for role in roles:
            _call(pc, 13, c_wchar_p(device_id), role, argtypes=(c_wchar_p, c_uint))
    finally:
        _release(pc)


def _activate(device_id, iid):
    dev = c_void_p()
    _call(_enum, 5, c_wchar_p(device_id), byref(dev), argtypes=(c_wchar_p, POINTER(c_void_p)))
    out = c_void_p()
    try:
        _call(dev, 3, byref(iid), CLSCTX_ALL, None, byref(out),
              argtypes=(POINTER(GUID), c_ulong, c_void_p, POINTER(c_void_p)))
    finally:
        _release(dev)
    return out


def get_volume(device_id):
    """(level 0..1, muted) or None if the device has no volume control."""
    try:
        vol = _activate(device_id, IID_IAudioEndpointVolume)
    except OSError:
        return None
    try:
        level, mute = c_float(), c_int()
        _call(vol, 9, byref(level), argtypes=(POINTER(c_float),))
        _call(vol, 15, byref(mute), argtypes=(POINTER(c_int),))
        return level.value, bool(mute.value)
    except OSError:
        return None
    finally:
        _release(vol)


def set_volume(device_id, level):
    vol = _activate(device_id, IID_IAudioEndpointVolume)
    try:
        _call(vol, 7, c_float(max(0.0, min(1.0, level))), None, argtypes=(c_float, c_void_p))
    finally:
        _release(vol)


def set_mute(device_id, muted):
    vol = _activate(device_id, IID_IAudioEndpointVolume)
    try:
        _call(vol, 14, int(bool(muted)), None, argtypes=(c_int, c_void_p))
    finally:
        _release(vol)


def _peak_of(meter):
    v = c_float()
    _call(meter, 3, byref(v), argtypes=(POINTER(c_float),))
    return max(0.0, min(1.0, v.value))


def peak(device_id):
    """The endpoint's current peak level 0..1 (what the Sound panel's meter
    shows), or None. For a capture device it reads 0 while nothing records."""
    try:
        meter = _activate(device_id, IID_IAudioMeterInformation)
    except OSError:
        return None
    try:
        return _peak_of(meter)
    except OSError:
        return None
    finally:
        _release(meter)


# Per-app sessions -------------------------------------------------------------------

_names_by_path = {}


def _exe_path(pid):
    h = kernel32.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = c_ulong(len(buf))
        return buf.value if kernel32.QueryFullProcessImageNameW(h, 0, buf, byref(n)) else ""
    finally:
        kernel32.CloseHandle(h)


def _file_description(path):
    """The exe's FileDescription ("Spotify", "Google Chrome"), or ""."""
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ""
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, data):
        return ""
    ptr, n = c_void_p(), c_uint()
    langs = [(0x0409, 0x04B0)]
    if version.VerQueryValueW(data, "\\VarFileInfo\\Translation", byref(ptr), byref(n)) and n.value >= 4:
        pairs = ctypes.cast(ptr, POINTER(c_ushort))
        langs = [(pairs[i], pairs[i + 1]) for i in range(0, n.value // 2, 2)] + langs
    for lang, cp in langs:
        if version.VerQueryValueW(data, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileDescription",
                                  byref(ptr), byref(n)) and n.value > 1:
            return ctypes.wstring_at(ptr.value).strip()
    return ""


def app_name(pid):
    """(display name, exe path) for a process id; cached per exe."""
    path = _exe_path(pid)
    if not path:
        return "", ""
    if path not in _names_by_path:
        base = os.path.splitext(os.path.basename(path))[0]
        desc = _file_description(path)
        # Some descriptions are a sentence ("Windows Explorer extension host"):
        # prefer the exe name then.
        _names_by_path[path] = desc if desc and len(desc) <= 32 else base[:1].upper() + base[1:]
    return _names_by_path[path], path


def _each_session(device_id, fn):
    """Calls fn(control2) for every session on the endpoint that hasn't expired."""
    mgr = _activate(device_id, IID_IAudioSessionManager2)
    try:
        en = c_void_p()
        _call(mgr, 5, byref(en), argtypes=(POINTER(c_void_p),))
        try:
            n = c_int()
            _call(en, 3, byref(n), argtypes=(POINTER(c_int),))
            for i in range(n.value):
                ctl = c_void_p()
                try:
                    _call(en, 4, i, byref(ctl), argtypes=(c_int, POINTER(c_void_p)))
                except OSError:
                    continue
                try:
                    st = c_int()
                    _call(ctl, 3, byref(st), argtypes=(POINTER(c_int),))
                    if st.value == SESSION_EXPIRED:
                        continue
                    ctl2 = _query(ctl, IID_IAudioSessionControl2)
                    try:
                        fn(ctl2, st.value)
                    finally:
                        _release(ctl2)
                except OSError:
                    continue
                finally:
                    _release(ctl)
        finally:
            _release(en)
    finally:
        _release(mgr)


def _simple_volume(ctl2):
    return _query(ctl2, IID_ISimpleAudioVolume)


def sessions(device_id):
    """The endpoint's app sessions: [{"sid", "pid", "name", "path", "system",
    "active", "level", "muted", "peak"}]. Several can belong to one app."""
    out = []

    def read(ctl2, state):
        sid = _wstr_out(ctl2, 13)
        pid = c_ulong()
        try:
            _call(ctl2, 14, byref(pid), argtypes=(POINTER(c_ulong),))
        except OSError:
            pid.value = 0
        system = _call(ctl2, 15) == 0  # S_OK: the system sounds session
        name, path = ("System sounds", "") if system else app_name(pid.value)
        if not name:
            name = _wstr_out(ctl2, 4)
            if name.startswith("@"):  # an unresolved resource string
                name = ""
        if not name and not pid.value:
            return
        level, mute = c_float(), c_int()
        vol = _simple_volume(ctl2)
        try:
            _call(vol, 4, byref(level), argtypes=(POINTER(c_float),))
            _call(vol, 6, byref(mute), argtypes=(POINTER(c_int),))
        finally:
            _release(vol)
        pk = None
        try:
            meter = _query(ctl2, IID_IAudioMeterInformation)
            try:
                pk = _peak_of(meter)
            finally:
                _release(meter)
        except OSError:
            pass
        out.append({"sid": sid, "pid": pid.value, "name": name or f"Process {pid.value}",
                    "path": path, "system": system, "active": state == 1,
                    "level": level.value, "muted": bool(mute.value), "peak": pk})

    _each_session(device_id, read)
    return out


def set_session(device_id, sids, level=None, muted=None):
    """Sets the volume and/or mute of the sessions whose ids are in `sids`."""
    sids = set(sids)

    def apply(ctl2, _state):
        if _wstr_out(ctl2, 13) not in sids:
            return
        vol = _simple_volume(ctl2)
        try:
            if level is not None:
                _call(vol, 3, c_float(max(0.0, min(1.0, level))), None, argtypes=(c_float, c_void_p))
            if muted is not None:
                _call(vol, 5, int(bool(muted)), None, argtypes=(c_int, c_void_p))
        finally:
            _release(vol)

    _each_session(device_id, apply)
