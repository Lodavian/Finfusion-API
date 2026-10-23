"""Windows user-bound key protection. Never falls back to plaintext."""
import csv
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


class SecurityError(RuntimeError):
    pass


def data_directory():
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise SecurityError("仅支持 Windows 当前用户的数据目录")
    return Path(os.environ["LOCALAPPDATA"]) / "Finfusion" / "Client"


def restrict_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        raise SecurityError("Windows 安全存储不可用")
    try:
        result = subprocess.check_output(
            ["whoami", "/user", "/fo", "csv", "/nh"], text=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        sid = next(csv.reader([result.strip()]))[1]
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                        f"*{sid}:(OI)(CI)F"], check=True, capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        raise SecurityError("无法设置用户数据目录权限") from None


class Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data, *, decrypt=False):
    if os.name != "nt":
        raise SecurityError("Windows DPAPI 不可用")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    func = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    func.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    func.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, destination = Blob(len(data), buffer), Blob()
    # Current user scope. UI_FORBIDDEN; never LOCAL_MACHINE.
    if not func(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise SecurityError("私钥保护/解密失败，请确认 Windows 用户与密钥文件")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel.LocalFree(destination.pbData)
        ctypes.memset(buffer, 0, len(data))


def validate_key(pem, password=None):
    try:
        key = serialization.load_pem_private_key(pem, password=password)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError()
        return key
    except Exception:
        raise SecurityError("需要有效的 P-256 PEM 私钥；请检查格式和密码") from None


def private_pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


class KeyStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "private.dpapi"

    def save(self, key):
        validate_key(private_pem(key))
        restrict_directory(self.directory)
        encrypted = dpapi(private_pem(key))
        temporary = self.directory / "private.dpapi.tmp"
        with temporary.open("wb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def generate(self):
        if self.path.exists():
            raise SecurityError("已有私钥；生成新密钥需要管理员重新登记，请先使用导入功能")
        key = ec.generate_private_key(ec.SECP256R1())
        self.save(key)

    def import_file(self, path, password=None):
        try:
            raw = Path(path).read_bytes()
        except OSError:
            raise SecurityError("无法读取私钥文件") from None
        self.save(validate_key(raw, password))

    def load(self):
        try:
            raw = self.path.read_bytes()
        except OSError:
            raise SecurityError("尚未配置私钥或文件无法读取") from None
        return validate_key(dpapi(raw, decrypt=True))

    def public_pem(self):
        return self.load().public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


class InstanceLock:
    def __init__(self, directory):
        self.path = Path(directory) / "instance.lock"
        self.stream = None

    def acquire(self):
        import msvcrt
        stream = self.path.open("a+b")
        stream.seek(0)
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            stream.close()
            return False
        self.stream = stream
        return True

    def release(self):
        if self.stream:
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            self.stream.close()
            self.stream = None
