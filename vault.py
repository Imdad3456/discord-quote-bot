"""Keeps the bot's saved files encrypted, so a copied file or backup is unreadable
without QUOTES_KEY. Keep the key out of this repository and away from the backups."""
import json
import os

from cryptography.fernet import Fernet

MARKER = "_encrypted"


def cipher():
    key = os.getenv("QUOTES_KEY", "").strip()
    if not key:
        raise RuntimeError("QUOTES_KEY is not set.")
    return Fernet(key)


def write_atomically(path, content):
    # These files can be the only copy of a deleted quote, so a crash mid-write
    # must never leave one truncated.
    temporary = f"{path}.tmp"
    with open(temporary, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
    except FileNotFoundError:
        return default
    if isinstance(value, dict) and MARKER in value:
        return json.loads(cipher().decrypt(value[MARKER].encode("ascii")))
    # Saved before encryption: readable once, and the next write encrypts it.
    return value


def write_json(path, value):
    plain = json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8")
    token = cipher().encrypt(plain).decode("ascii")
    # Still valid JSON, so the backup job's check of each file keeps working.
    write_atomically(path, json.dumps({MARKER: token}).encode("ascii"))


def read_bytes(path):
    with open(path, "rb") as f:
        return cipher().decrypt(f.read())


def write_bytes(path, content):
    write_atomically(path, cipher().encrypt(content))
