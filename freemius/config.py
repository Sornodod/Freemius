"""Хранилище подключений, настройки, keyring."""

import getpass
import json
import os
from pathlib import Path

import keyring

from .themes import THEMES


KEYRING_SERVICE = "freemius"
DEFAULT_LOCALHOST_NAME = "localhost"

CONNECTIONS_PATH = Path.home() / ".config" / "freemius" / "connections.json"
SETTINGS_PATH = Path.home() / ".config" / "freemius" / "settings.json"


# ---------- keyring ----------
def keyring_get(name):
    try:
        return keyring.get_password(KEYRING_SERVICE, name)
    except Exception as e:
        print(f"[WARN] keyring.get_password({name}): {e}")
        return None


def keyring_set(name, password):
    try:
        if password:
            keyring.set_password(KEYRING_SERVICE, name, password)
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, name)
            except keyring.errors.PasswordDeleteError:
                pass
    except Exception as e:
        print(f"[WARN] keyring.set_password({name}): {e}")


def keyring_delete(name):
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except Exception:
        pass


# ---------- settings ----------
def load_settings():
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text("utf-8"))
        except Exception:
            pass
    return {}


def save_settings(data):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), "utf-8")


# ---------- connections ----------
class ConnectionStore:
    def __init__(self):
        CONNECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.path = CONNECTIONS_PATH
        self.data = {}
        self.load()
        self._ensure_localhost()

    def load(self):
        if not self.path.exists():
            self.data = {}
            return
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except Exception as e:
            print(f"[WARN] Не удалось прочитать {self.path}: {e}")
            self.data = {}
            return

        if isinstance(raw, dict):
            self.data = raw
        elif isinstance(raw, list):
            migrated = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                host = item.get("host", "")
                user = item.get("user", "")
                name = f"{user}@{host}" if user else host
                if not name:
                    continue
                migrated[name] = {
                    "host": host,
                    "port": int(item.get("port", 22)),
                    "user": user,
                    "key": item.get("key") or item.get("key_path") or "",
                }
            self.data = migrated
            if migrated:
                self.save()
        else:
            self.data = {}

    def _ensure_localhost(self):
        if DEFAULT_LOCALHOST_NAME not in self.data:
            self.data[DEFAULT_LOCALHOST_NAME] = {
                "host": "127.0.0.1",
                "port": 22,
                "user": getpass.getuser(),
                "key": "",
            }
            self.save()

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def add(self, name, host, port, user, key):
        self.data[name] = {"host": host, "port": port, "user": user, "key": key}
        self.save()

    def remove(self, name):
        if name in self.data and name != DEFAULT_LOCALHOST_NAME:
            del self.data[name]
            self.save()
        keyring_delete(name)

    def names(self):
        return sorted(self.data.keys())

    def get(self, name):
        return self.data.get(name)
