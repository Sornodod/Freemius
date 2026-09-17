"""SCP-провайдер: использует системный scp/ssh, обходит SFTP-подсистему.

Работает и по ключу, и по паролю (через sshpass).
Позволяет листинг, копирование в обе стороны, mkdir, rm.
"""

import os
import shutil
import stat as stat_module
import subprocess
import time


def _which(name):
    return shutil.which(name)


def _entry(name, is_dir, size, mtime, path):
    from sftp_panel import FileEntry
    return FileEntry(name, is_dir, size, mtime, path)


class SCPProvider:
    kind = "scp"

    def __init__(self, host, port, user, password=None, key=None):
        if not _which("scp"):
            raise RuntimeError("Не найден `scp`. Установи openssh-client.")
        if not _which("ssh"):
            raise RuntimeError("Не найден `ssh`. Установи openssh-client.")

        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password or None
        self.key = key or None

        if self.password and not self.key and not _which("sshpass"):
            raise RuntimeError(
                "Для подключения по паролю нужен `sshpass`.\n"
                "Установи: sudo apt install sshpass\n"
                "Или укажи путь к ключу при редактировании хоста."
            )

        self.cwd = self._remote_pwd()

    # --- низкоуровневое ---
    def _ssh_base(self):
        cmd = ["ssh", "-p", str(self.port), "-o", "LogLevel=ERROR",
               "-o", "StrictHostKeyChecking=accept-new"]
        if self.key:
            cmd += ["-i", self.key, "-o", "IdentitiesOnly=yes"]
        return cmd

    def _scp_base(self):
        cmd = ["scp", "-O", "-P", str(self.port), "-o", "LogLevel=ERROR",
               "-o", "StrictHostKeyChecking=accept-new"]
        if self.key:
            cmd += ["-i", self.key, "-o", "IdentitiesOnly=yes"]
        return cmd

    def _wrap(self, cmd):
        if self.password and not self.key:
            return ["sshpass", "-p", self.password] + cmd
        return cmd

    def _run(self, cmd, timeout=60, check=False):
        try:
            p = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Таймаут команды")
        if check and p.returncode != 0:
            raise RuntimeError(p.stderr.strip() or f"exit code {p.returncode}")
        return p

    def _remote(self):
        return f"{self.user}@{self.host}"

    def _quote(self, s):
        return "'" + s.replace("'", "'\"'\"'") + "'"

    def _remote_pwd(self):
        cmd = self._wrap(self._ssh_base() + [self._remote(), "pwd"])
        p = self._run(cmd, check=True)
        for line in p.stdout.splitlines():
            line = line.strip()
            if line.startswith("/"):
                return line
        return "."

    # --- публичный API ---
    def listdir(self):
        remote = self._remote()
        cmd = self._wrap(self._ssh_base() + [
            remote, f"ls -la {self._quote(self.cwd)}"
        ])
        p = self._run(cmd, check=True)

        entries = []
        for line in p.stdout.splitlines():
            line = line.rstrip("\n")
            if not line or line.startswith("total "):
                continue
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            perms = parts[0]
            if not perms or perms[0] not in "-dlbcps":
                continue
            try:
                size = int(parts[4])
            except ValueError:
                continue
            name = parts[8]
            if " -> " in name:
                name = name.split(" -> ", 1)[0]
            if name in (".", ".."):
                continue

            is_dir = perms.startswith("d")
            mtime = 0
            try:
                tstr = f"{parts[5]} {parts[6]} {parts[7]}"
                for fmt in ("%b %d %H:%M", "%b %d %Y"):
                    try:
                        t = time.strptime(tstr, fmt)
                        year = time.localtime().tm_year if "%H" in fmt else t.tm_year
                        mtime = time.mktime((
                            year, t.tm_mon, t.tm_mday,
                            t.tm_hour, t.tm_min, t.tm_sec, 0, 0, -1
                        ))
                        break
                    except Exception:
                        continue
            except Exception:
                pass

            full = self.cwd.rstrip("/") + "/" + name
            entries.append(_entry(name, is_dir, size, mtime, full))

        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def chdir(self, path):
        if not path.startswith("/"):
            base = self.cwd.rstrip("/")
            path = f"{base}/{path}"
        parts = []
        for p in path.split("/"):
            if p in ("", "."):
                continue
            if p == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(p)
        normalized = "/" + "/".join(parts)

        cmd = self._wrap(self._ssh_base() + [
            self._remote(),
            f"cd {self._quote(normalized)} && pwd",
        ])
        p = self._run(cmd, check=True)
        for line in p.stdout.splitlines():
            line = line.strip()
            if line.startswith("/"):
                self.cwd = line
                return
        raise RuntimeError(f"Не удалось перейти в {path}")

    def cd_up(self):
        parent = self.cwd.rstrip("/").rsplit("/", 1)[0] or "/"
        try:
            self.chdir(parent)
        except Exception:
            self.cwd = parent

    def mkdir(self, name):
        cmd = self._wrap(self._ssh_base() + [
            self._remote(),
            f"mkdir {self._quote(self.cwd.rstrip('/') + '/' + name)}",
        ])
        self._run(cmd, check=True)

    def remove(self, entry):
        cmd = self._wrap(self._ssh_base() + [
            self._remote(),
            f"rm -rf {self._quote(entry.path)}",
        ])
        self._run(cmd, check=True)

    def get_file(self, remote_path, local_path):
        src = f"{self._remote()}:{remote_path}"
        cmd = self._wrap(self._scp_base() + [src, local_path])
        self._run(cmd, timeout=600, check=True)

    def put_file(self, local_path, remote_path):
        dst = f"{self._remote()}:{remote_path}"
        cmd = self._wrap(self._scp_base() + [local_path, dst])
        self._run(cmd, timeout=600, check=True)

    def open_read(self, path):
        raise NotImplementedError("Use get_file()")

    def open_write(self, path):
        raise NotImplementedError("Use put_file()")

    def close(self):
        pass

    def label(self):
        return f"SCP: {self.cwd}"
