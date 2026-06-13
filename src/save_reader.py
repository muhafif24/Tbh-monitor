"""
Savegame reader — decrypt the local Task Bar Hero save file (Easy Save 3).

STRICTLY READ-ONLY: the save file is only ever opened for reading, never written.
Zero network requests — everything happens locally.

File location (Windows):
  %USERPROFILE%\\AppData\\LocalLow\\TesseractStudio\\TaskbarHero\\SaveFile_Live.es3

ES3 format (as implemented by taskbarhero.wiki/save-inspector, verified locally):
  - bytes[0:16]  = IV (also used as the PBKDF2 salt)
  - bytes[16:]   = ciphertext
  - key          = PBKDF2-HMAC-SHA1(password, salt=IV, iterations=100, dklen=16)
  - cipher       = AES-128-CBC, PKCS7 padding
  - plaintext    = UTF-8 JSON: {"PlayerSaveData": {"__type": "string", "value": "<json>"}}

The password below is a public constant shipped in the game client and in
taskbarhero.wiki's frontend JS — it is not a user credential. It may change
after a game update; pass `password=` to override.
"""
import os
import json
import hashlib
import logging
from collections import Counter
from typing import Dict, Optional

from Crypto.Cipher import AES

log = logging.getLogger(__name__)

_ES3_PASSWORD = "emuMqG3bLYJ938ZDCfieWJ"

SAVE_PATH = os.path.join(
    os.path.expanduser("~"),
    "AppData", "LocalLow", "TesseractStudio", "TaskbarHero", "SaveFile_Live.es3",
)


class SaveReadError(Exception):
    """Raised when the save file is missing, corrupt, or the password is wrong."""


def save_exists(path: Optional[str] = None) -> bool:
    return os.path.exists(path or SAVE_PATH)


def _unpad_pkcs7(data: bytes) -> bytes:
    if not data:
        raise SaveReadError("Decrypted data is empty.")
    pad = data[-1]
    if pad < 1 or pad > 16 or data[-pad:] != bytes([pad]) * pad:
        raise SaveReadError(
            "Decryption failed — wrong password or not a TaskbarHero save. "
            "(The password can change after a game update.)"
        )
    return data[:-pad]


def decrypt_save(path: Optional[str] = None, password: str = _ES3_PASSWORD) -> dict:
    """
    Decrypt the .es3 file and return the parsed PlayerSaveData dict.
    Raises SaveReadError on any failure.
    """
    path = path or SAVE_PATH
    if not os.path.exists(path):
        raise SaveReadError(f"Save file not found: {path}")

    with open(path, "rb") as f:
        raw = f.read()

    if len(raw) <= 16:
        raise SaveReadError("File is too small to be a valid .es3 save.")

    iv, ciphertext = raw[:16], raw[16:]
    key = hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), iv, 100, dklen=16)

    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = _unpad_pkcs7(cipher.decrypt(ciphertext))

    try:
        outer = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SaveReadError(f"Decrypted data is not valid JSON: {exc}") from exc

    player_raw = outer.get("PlayerSaveData", {})
    # ES3 wraps values: {"__type": "string", "value": "<nested json string>"}
    value = player_raw.get("value") if isinstance(player_raw, dict) else None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise SaveReadError(f"PlayerSaveData is not valid JSON: {exc}") from exc
    if isinstance(player_raw, dict) and "value" not in player_raw:
        return player_raw

    raise SaveReadError("PlayerSaveData not found in the save file.")


def get_owned_counts(path: Optional[str] = None) -> Dict[int, int]:
    """
    Return {ItemKey: count} for every item instance in the save's item pool.
    Stack-encoded keys (9+ digits, e.g. 110005900) are normalized to their
    base ItemKey via // 1000.
    """
    player = decrypt_save(path)
    items = player.get("itemSaveDatas", [])

    counts: Counter = Counter()
    for entry in items:
        key = entry.get("ItemKey")
        if not isinstance(key, int) or key <= 0:
            continue
        if key >= 100_000_000:   # stack/variant encoding observed in real saves
            key = key // 1000
        counts[key] += 1

    log.info("Save read: %d item instances, %d distinct keys.", len(items), len(counts))
    return dict(counts)
