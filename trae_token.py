"""Extract TRAE Work (Solo Lite) auth tokens from local storage.

The AHA-encrypted iCubeAuthInfo blobs are self-contained AES-CBC (key embedded
in the blob, derived via SHA-512), so they decrypt fully in pure Python.
"""
import json
import base64
import hashlib
import os
import sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# byteCrypto.js constants (hardcoded XOR masks + format params)
Gte = [82,9,106,213,48,54,165,56,191,64,163,158,129,243,215,251,124,227,57,130,155,47,255,135,52,142,67,68,196,222,233,203,84,123,148,50,166,194,35,61,238,76,149,11,66,250,195,78,8,46,161,102,40,217,36,178,118,91,162,73,109,139,209,37]
Jte = [31,221,168,51,136,7,199,49,177,18,16,89,39,128,236,95,96,81,127,169,25,181,74,13,45,229,122,159,147,201,156,239,160,224,59,77,174,42,245,176,200,235,187,60,131,83,153,97,23,43,4,126,186,119,214,38,225,105,20,99,85,33,12,125]

AES128 = 16
cP = 16
Zd = 64
Tw = 32
lP = 64
vm = 6


def find_storage_json():
    """Locate TRAE's global storage.json on this machine (auto-detected).

    Checks the most common install layouts under %APPDATA% so the script works
    on any computer, no hardcoded usernames.
    """
    appdata = os.environ.get("APPDATA", "")
    candidates = [
        r"TRAE SOLO CN\User\globalStorage\storage.json",
        r"TRAE SOLO CN\User\globalStorage\storage.json",
        r"TRAE\User\globalStorage\storage.json",
        r"TRAE SOLO\User\globalStorage\storage.json",
    ]
    for rel in candidates:
        p = Path(appdata) / rel
        if p.exists():
            return p
    # Fallback: scan APPDATA subdirs for any globalStorage/storage.json
    if appdata:
        for d in Path(appdata).iterdir():
            p = d / "User" / "globalStorage" / "storage.json"
            if p.exists():
                return p
    raise FileNotFoundError(
        "Could not find TRAE storage.json under %APPDATA%. "
        "Is TRAE Work installed and logged in on this machine?"
    )


STORAGE_JSON = str(find_storage_json())


def _sha512(b):
    return hashlib.sha512(b).digest()


def _xor_aes(length):
    return bytes([Gte[r] ^ Jte[r] for r in range(length)])


def _fte(key, e, i):
    s = Zd + lP
    n = bytearray(s)
    o = _sha512(key)
    a = _xor_aes(lP)
    n[0:64] = o
    n[64:128] = a
    c = _sha512(bytes(n))
    n[0:64] = c
    return bytes(n[0:e]), bytes(n[e:e + i])


def _aes_cbc_dec(key, iv, data):
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return dec.update(data) + dec.finalize()


def aha_decrypt_b64(v):
    """Decrypt an AHA-encrypted base64 value, returns plaintext bytes."""
    raw = base64.b64decode(v)
    key = raw[vm:vm + Tw]
    aeskey, iv = _fte(key, AES128, cP)
    plain = _aes_cbc_dec(aeskey, iv, raw[Tw + vm:])
    return plain[Zd:]


def load_auth_info():
    store = json.load(open(STORAGE_JSON, encoding="utf-8"))
    result = {}
    for k, v in store.items():
        if k.startswith("iCubeAuthInfo:"):
            try:
                dec = aha_decrypt_b64(v).decode("utf-8", errors="replace")
                # strip PKCS7-ish padding trailing bytes (0x01..0x10)
                dec = dec.rstrip("\x00")
                result[k] = dec
            except Exception as e:
                result[k] = f"<decrypt error: {e}>"
    return result


if __name__ == "__main__":
    info = load_auth_info()
    if "--raw" in sys.argv:
        for k, v in info.items():
            print("=====", k)
            print(v)
        sys.exit(0)

    # Convenience: print compact summary
    for k, v in info.items():
        if k.endswith("icube.cloudide"):
            try:
                d = json.loads(v.strip("\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"))
                print("host:", d.get("host"))
                print("userId:", d.get("userId"))
                print("region:", (d.get("userRegion") or {}).get("region"))
                print("scope:", (d.get("account") or {}).get("scope"))
                print("token exp:", d.get("expiredAt"))
                print("refresh exp:", d.get("refreshExpiredAt"))
                print("has refreshToken:", bool(d.get("refreshToken")))
            except Exception as e:
                print("parse err", e)
