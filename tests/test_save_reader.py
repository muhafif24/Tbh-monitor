import os
import json
import hashlib
import tempfile
import unittest

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from src.save_reader import decrypt_save, get_owned_counts, save_exists, SaveReadError, _ES3_PASSWORD


def _make_es3(payload: dict, password: str = _ES3_PASSWORD) -> bytes:
    """Build a synthetic .es3 file the same way the game does."""
    plaintext = json.dumps(payload).encode("utf-8")
    iv = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha1", password.encode(), iv, 100, dklen=16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return iv + cipher.encrypt(pad(plaintext, 16))


def _write_temp(data: bytes) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".es3", delete=False)
    f.write(data)
    f.close()
    return f.name


class TestDecryptSave(unittest.TestCase):

    def _payload(self, player: dict) -> dict:
        return {"PlayerSaveData": {"__type": "string", "value": json.dumps(player)}}

    def test_roundtrip(self):
        path = _write_temp(_make_es3(self._payload({"itemSaveDatas": []})))
        try:
            player = decrypt_save(path)
            self.assertEqual(player, {"itemSaveDatas": []})
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(SaveReadError):
            decrypt_save(r"C:\nonexistent\nope.es3")

    def test_too_small_raises(self):
        path = _write_temp(b"tiny")
        try:
            with self.assertRaises(SaveReadError):
                decrypt_save(path)
        finally:
            os.unlink(path)

    def test_wrong_password_raises(self):
        path = _write_temp(_make_es3(self._payload({}), password="benar"))
        try:
            with self.assertRaises(SaveReadError):
                decrypt_save(path, password="salah")
        finally:
            os.unlink(path)

    def test_save_exists_false_for_missing(self):
        self.assertFalse(save_exists(r"C:\nonexistent\nope.es3"))


class TestGetOwnedCounts(unittest.TestCase):

    def _make_save(self, item_keys: list) -> str:
        player = {"itemSaveDatas": [{"ItemKey": k, "UniqueId": i} for i, k in enumerate(item_keys)]}
        payload = {"PlayerSaveData": {"__type": "string", "value": json.dumps(player)}}
        return _write_temp(_make_es3(payload))

    def test_counts_duplicates(self):
        path = self._make_save([190001, 190001, 190001, 141001])
        try:
            counts = get_owned_counts(path)
            self.assertEqual(counts, {190001: 3, 141001: 1})
        finally:
            os.unlink(path)

    def test_stack_key_normalized(self):
        # 9-digit stack-encoded keys collapse to base key via // 1000
        path = self._make_save([110005900, 110005])
        try:
            counts = get_owned_counts(path)
            self.assertEqual(counts, {110005: 2})
        finally:
            os.unlink(path)

    def test_ignores_invalid_keys(self):
        path = self._make_save([0, -5, 141001])
        try:
            counts = get_owned_counts(path)
            self.assertEqual(counts, {141001: 1})
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
