"""Провайдеры файловых систем: локальный и удалённый (SCP/ssh)."""

import os
import re
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

    def size_of(self, path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def close(self):
        pass

    def label(self):
        return f"Local: {self.cwd}"


class SCPProvider:
    kind = "scp"

    def __init__(self, host, port, user, password=None, key=None):
        if not _which("ssh"):
            raise RuntimeError("Не найден `ssh`. Установи openssh-client.")

        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password or None
        self.key = key or None

        self.cwd = self._remote_pwd()
        print(f"[SFTP] подключение к {user}@{host}, cwd={self.cwd!r}")

    # ---------- очистка stderr ----------
    @staticmethod
    def _clean_stderr(text: str) -> str:
        if not text:
            return ""
        out = []
        for line in text.splitlines():
            low = line.lower()
            if "setlocale" in low and "warning" in low:
                continue
            if "cannot change locale" in low:
                continue
            if line.strip().startswith("in function 'cd'"):
                continue
            if "builtin cd $argv" in line:
                continue
            if line.strip() == "^":
                continue
            line = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line)
            line = re.sub(r"\\033\[[0-9;?]*[A-Za-z]", "", line)
            line = re.sub(r"\\e\[[0-9;?]*[A-Za-z]", "", line)
            if not line.strip():
                continue
            out.append(line)
        return "\n".join(out).strip()

    # ---------- аутентификация ----------
    def _auth_opts(self):
        opts = [
            "-o", "LogLevel=ERROR",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "NumberOfPasswordPrompts=1",
            "-o", "IdentitiesOnly=yes",
            "-o", "SendEnv=none",
            "-o", "RequestTTY=no",
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

    # ---------- SSH_ASKPASS ----------
    def _askpass_env(self):
        env = os.environ.copy()
        env["LC_ALL"] = "C.UTF-8"
        env["LANG"] = "C.UTF-8"
        env["LANGUAGE"] = "C"

        if not self.password:
            return env, None

        fd, path = tempfile.mkstemp(prefix="freemius_askpass_", suffix=".sh")
        with os.fdopen(fd, "w") as f:
            f.write("#!/bin/sh\n")
            safe = self.password.replace("'", "'\"'\"'")
            f.write(f"printf '%s\\n' '{safe}'\n")
        os.chmod(path, 0o700)
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
            msg = self._clean_stderr(p.stderr) or f"exit code {p.returncode}"
            raise RuntimeError(msg)
        return p

    # ---------- вспомогательное ----------
    def _remote(self):
        return f"{self.user}@{self.host}"

    def _quote(self, s):
        return "'" + s.replace("'", "'\"'\"'") + "'"

    def _sh(self, script: str) -> str:
        """Оборачивает shell-скрипт в /bin/sh -c '<script>'."""
        return f"/bin/sh -c {self._quote(script)}"

    def _remote_pwd(self):
        """Определяем домашний каталог на сервере.

        Пробуем несколько вариантов. НЕ возвращаем '.', потому что от
        этого ломается chdir. Если ничего не вышло — предполагаем
        /home/<user>.
        """
        candidates = [
            "cd ~ && pwd",
            "echo $HOME",
            "cd && pwd",
            "pwd",
        ]
        for script in candidates:
            cmd = self._ssh_base() + [self._remote(), self._sh(script)]
            p = self._run(cmd, check=False, timeout=20)
            for line in p.stdout.splitlines():
                line = line.strip()
                # валидный абсолютный путь, не "/" в одиночку
                if line.startswith("/") and len(line) > 1:
                    print(f"[SFTP] _remote_pwd: {script!r} → {line}")
                    return line

        # совсем не смогли — используем стандартную догадку
        guess = f"/home/{self.user}"
        print(f"[SFTP] _remote_pwd: все попытки провалились, использую {guess}")
        return guess

    def size_of(self, path):
        cmd = self._ssh_base() + [
            self._remote(),
            self._sh(f"stat -c %s {self._quote(path)} 2>/dev/null || echo 0"),
        ]
        try:
            p = self._run(cmd, check=False, timeout=15)
            return int((p.stdout or "0").strip().splitlines()[-1])
        except Exception:
            return 0

    # ---------- публичный API ----------
    def listdir(self):
        remote = self._remote()
        cmd = self._ssh_base() + [
            remote,
            self._sh(f"ls -la {self._quote(self.cwd)}"),
        ]
        p = self._run(cmd, check=False)
        if p.returncode != 0:
            err = self._clean_stderr(p.stderr) or f"exit code {p.returncode}"
            raise RuntimeError(f"Не удалось прочитать {self.cwd}: {err}")

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
        # защита: если cwd невалиден (не начинается с /), сбрасываем его
        if not self.cwd.startswith("/"):
            print(f"[SFTP] chdir: cwd={self.cwd!r} невалиден, сбрасываю на /home/{self.user}")
            self.cwd = f"/home/{self.user}"

        # нормализуем путь
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

        print(f"[SFTP] chdir: cwd={self.cwd!r}, target={normalized!r}")

        inner = f"cd {self._quote(normalized)} && pwd"
        cmd = self._ssh_base() + [self._remote(), self._sh(inner)]
        p = self._run(cmd, check=False)

        # если сервер без /bin/sh — fallback на прямой вызов
        if p.returncode != 0 and "not found" in (p.stderr or "").lower():
            cmd2 = self._ssh_base() + [self._remote(), inner]
            p = self._run(cmd2, check=False)

        if p.returncode != 0:
            err = self._clean_stderr(p.stderr) or p.stdout.strip() or f"exit code {p.returncode}"
            first = next((l for l in err.splitlines() if l.strip()), err)
            raise RuntimeError(f"{normalized}: {first}")

        for line in p.stdout.splitlines():
            line = line.strip()
            if line.startswith("/") and len(line) > 1:
                self.cwd = line
                return
        self.cwd = normalized

    def cd_up(self):
        if not self.cwd.startswith("/"):
            self.cwd = f"/home/{self.user}"
            return
        parent = self.cwd.rstrip("/").rsplit("/", 1)[0] or "/"
        try:
            self.chdir(parent)
        except Exception:
            self.cwd = parent

    def mkdir(self, name):
        cmd = self._ssh_base() + [
            self._remote(),
            self._sh(f"mkdir {self._quote(self.cwd.rstrip('/') + '/' + name)}"),
        ]
        self._run(cmd, check=True)

    def remove(self, entry):
        cmd = self._ssh_base() + [
            self._remote(),
            self._sh(f"rm -rf {self._quote(entry.path)}"),
        ]
        self._run(cmd, check=True)

    # ---------- передача файлов через ssh+cat ----------
    def stream_download(self, remote_path, local_path, progress_cb=None):
        inner = f"cat {self._quote(remote_path)}"
        cmd = self._ssh_base() + [self._remote(), self._sh(inner)]
        env, askpass_path = self._askpass_env()
        try:
            p = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, stdin=subprocess.DEVNULL,
            )
            total = self.size_of(remote_path) or 0
            got = 0
            with open(local_path, "wb") as fout:
                while True:
                    chunk = p.stdout.read(64 * 1024)
                    if not chunk:
                        break
                    fout.write(chunk)
                    got += len(chunk)
                    if progress_cb:
                        progress_cb(got, total)
            p.wait(timeout=30)
            if p.returncode != 0:
                err = (p.stderr.read() or b"").decode("utf-8", "replace")
                raise RuntimeError(self._clean_stderr(err) or f"exit code {p.returncode}")
        finally:
            if askpass_path:
                try:
                    os.unlink(askpass_path)
                except Exception:
                    pass

    def stream_upload(self, local_path, remote_path, progress_cb=None):
        inner = f"cat > {self._quote(remote_path)}"
        cmd = self._ssh_base() + [self._remote(), self._sh(inner)]
        env, askpass_path = self._askpass_env()
        try:
            p = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env,
            )
            try:
                total = os.path.getsize(local_path)
            except OSError:
                total = 0
            sent = 0
            with open(local_path, "rb") as fin:
                while True:
                    chunk = fin.read(64 * 1024)
                    if not chunk:
                        break
                    p.stdin.write(chunk)
                    sent += len(chunk)
                    if progress_cb:
                        progress_cb(sent, total)
            p.stdin.close()
            p.wait(timeout=30)
            if p.returncode != 0:
                err = (p.stderr.read() or b"").decode("utf-8", "replace")
                raise RuntimeError(self._clean_stderr(err) or f"exit code {p.returncode}")
        finally:
            if askpass_path:
                try:
                    os.unlink(askpass_path)
                except Exception:
                    pass

    # --- совместимость со старым API ---
    def get_file(self, remote_path, local_path):
        self.stream_download(remote_path, local_path)

    def put_file(self, local_path, remote_path):
        self.stream_upload(local_path, remote_path)

    def open_read(self, path):
        raise NotImplementedError

    def open_write(self, path):
        raise NotImplementedError

    def close(self):
        pass

    def label(self):
        return f"SCP: {self.cwd}"
