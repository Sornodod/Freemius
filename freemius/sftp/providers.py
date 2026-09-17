"""Провайдеры файловых систем: локальный и удалённый (SCP)."""

import os
import shutil
import stat as stat_module
import subprocess
import tempfile
import time

from .widgets import FileEntry


def _which(name):
    return shutil.which(name)


def _human_size(n):
    if n is None:
        return ""
    units = ["B", "K", "M", "G", "T", "P"]
    f = float(n)
    for u in units:
        if f < 1024:
            return f"{f:.0f}{u}" if u == "B" else f"{f:.1f}{u}"
        f /= 1024
    return f"{f:.1f}E"


def _fmt_time(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except Exception:
        return ""


class LocalProvider:
    kind = "local"

    def __init__(self):
        self.cwd = os.path.expanduser("~")

    def listdir(self):
        entries = []
        try:
            for name in os.listdir(self.cwd):
                full = os.path.join(self.cwd, name)
                try:
                    st = os.lstat(full)
                    is_dir = stat_module.S_ISDIR(st.st_mode)
                    entries.append(FileEntry(name, is_dir, st.st_size, st.st_mtime, full))
                except OSError:
                    continue
        except OSError as e:
            raise RuntimeError(str(e))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def chdir(self, path):
        self.cwd = os.path.abspath(path)

    def cd_up(self):
        self.cwd = os.path.dirname(self.cwd.rstrip("/")) or "/"

    def mkdir(self, name):
        os.mkdir(os.path.join(self.cwd, name))

    def remove(self, entry: FileEntry):
        if entry.is_dir:
            os.rmdir(entry.path)
        else:
            os.remove(entry.path)

    def open_read(self, path):
        return open(path, "rb")

    def open_write(self, path):
        return open(path, "wb")

    def close(self):
        pass

    def label(self):
        return f"Local: {self.cwd}"


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

        self.cwd = self._remote_pwd()

    def _auth_opts(self):
        opts = [
            "-o", "LogLevel=ERROR",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "NumberOfPasswordPrompts=1",
            "-o", "IdentitiesOnly=yes",
        ]
        if self.key:
            opts += [
                "-i", self.key,
                "-o", "PreferredAuthentications=publickey",
                "-o", "PubkeyAuthentication=yes",
                "-o", "PasswordAuthentication=no",
                "-o", "KbdInteractiveAuthentication=no",
            ]
        elif self.password:
            opts += [
                "-o", "PreferredAuthentications=password,keyboard-interactive",
                "-o", "PubkeyAuthentication=no",
                "-o", "PasswordAuthentication=yes",
                "-o", "KbdInteractiveAuthentication=yes",
                "-o", "IdentityAgent=none",
            ]
        return opts

    def _ssh_base(self):
        return ["ssh", "-p", str(self.port)] + self._auth_opts()

    def _scp_base(self):
        return ["scp", "-O", "-P", str(self.port)] + self._auth_opts()

    def _askpass_env(self):
        if not self.password:
            return None, None
        fd, path = tempfile.mkstemp(prefix="freemius_askpass_", suffix=".sh")
        with os.fdopen(fd, "w") as f:
            f.write("#!/bin/sh\n")
            safe = self.password.replace("'", "'\"'\"'")
            f.write(f"printf '%s\\n' '{safe}'\n")
        os.chmod(path, 0o700)
        env = os.environ.copy()
        env["SSH_ASKPASS"] = path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env.setdefault("DISPLAY", ":0")
        return env, path

    def _run(self, cmd, timeout=60, check=False):
        env, askpass_path = self._askpass_env()
        try:
            p = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                env=env, stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Таймаут команды")
        finally:
            if askpass_path:
                try:
                    os.unlink(askpass_path)
                except Exception:
                    pass
        if check and p.returncode != 0:
            raise RuntimeError(p.stderr.strip() or f"exit code {p.returncode}")
        return p

    def _remote(self):
        return f"{self.user}@{self.host}"

    def _quote(self, s):
        return "'" + s.replace("'", "'\"'\"'") + "'"

    def _remote_pwd(self):
        cmd = self._ssh_base() + [self._remote(), "pwd"]
        p = self._run(cmd, check=True)
        for line in p.stdout.splitlines():
            line = line.strip()
            if line.startswith("/"):
                return line
        return "."

    def listdir(self):
        remote = self._remote()
        cmd = self._ssh_base() + [remote, f"ls -la {self._quote(self.cwd)}"]
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
            entries.append(FileEntry(name, is_dir, size, mtime, full))

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

        cmd = self._ssh_base() + [
            self._remote(), f"cd {self._quote(normalized)} && pwd",
        ]
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
        cmd = self._ssh_base() + [
            self._remote(),
            f"mkdir {self._quote(self.cwd.rstrip('/') + '/' + name)}",
        ]
        self._run(cmd, check=True)

    def remove(self, entry):
        cmd = self._ssh_base() + [
            self._remote(), f"rm -rf {self._quote(entry.path)}",
        ]
        self._run(cmd, check=True)

    def get_file(self, remote_path, local_path):
        src = f"{self._remote()}:{remote_path}"
        cmd = self._scp_base() + [src, local_path]
        self._run(cmd, timeout=600, check=True)

    def put_file(self, local_path, remote_path):
        dst = f"{self._remote()}:{remote_path}"
        cmd = self._scp_base() + [local_path, dst]
        self._run(cmd, timeout=600, check=True)

    def open_read(self, path):
        raise NotImplementedError("Use get_file()")

    def open_write(self, path):
        raise NotImplementedError("Use put_file()")

    def close(self):
        pass

    def label(self):
        return f"SCP: {self.cwd}"
