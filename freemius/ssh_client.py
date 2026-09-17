import logging
import threading

import paramiko

log = logging.getLogger("ssh")


class SSHClient:
    """Асинхронный SSH-клиент с колбэками для GUI."""

    def __init__(self, on_data=None, on_error=None, on_close=None):
        self.client = None
        self.channel = None
        self._on_data = on_data
        self._on_error = on_error
        self._on_close = on_close
        self._reader_thread = None
        self._running = False

    def connect(self, host, port, username, password=None, key_filename=None,
                cols=80, rows=24):
        log.info(f"Подключение к {username}@{host}:{port} "
                 f"(key={key_filename!r}, password={'yes' if password else 'no'})")

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs = dict(hostname=host, port=port, username=username, timeout=10)
        if key_filename:
            kwargs["key_filename"] = key_filename
            kwargs["password"] = password or None
            kwargs["look_for_keys"] = False
            kwargs["allow_agent"] = False
        elif password:
            kwargs["password"] = password
            kwargs["look_for_keys"] = False
            kwargs["allow_agent"] = False
        else:
            kwargs["look_for_keys"] = True
            kwargs["allow_agent"] = False

        try:
            self.client.connect(**kwargs)
        except paramiko.AuthenticationException as e:
            log.error(f"Аутентификация не удалась: {e}")
            raise
        except Exception as e:
            log.error(f"Ошибка соединения: {e}")
            raise

        log.info("TCP-соединение установлено, открываю shell…")

        # Устанавливаем env ДО открытия shell, чтобы сервер не подставил
        # свои LC_ALL/LANG и не было warning от setlocale.
        transport = self.client.get_transport()
        try:
            transport.set_keepalive(30)
        except Exception:
            pass
        try:
            # не все серверы разрешают — молча игнорируем
            transport.global_request(
                "env", False,
                LC_ALL="C.UTF-8", LANG="C.UTF-8", LANGUAGE="C",
            )
        except Exception as e:
            log.warning(f"env request failed: {e}")

        self.channel = self.client.invoke_shell(
            term="xterm-256color", width=cols, height=rows
        )
        self.channel.settimeout(0.0)
        self._running = True

        # ещё раз попробуем через update_environment (для тех серверов,
        # что поддерживают sshd AcceptEnv)
        try:
            self.channel.update_environment({
                "LC_ALL": "C.UTF-8",
                "LANG": "C.UTF-8",
                "LANGUAGE": "C",
            })
        except Exception as e:
            log.debug(f"update_environment: {e}")

        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="ssh-reader"
        )
        self._reader_thread.start()
        log.info("Shell открыт, поток чтения запущен")

    def _read_loop(self):
        try:
            while self._running:
                if self.channel.recv_ready():
                    data = self.channel.recv(4096)
                    if not data:
                        log.info("Сервер закрыл поток (EOF)")
                        break
                    if self._on_data:
                        self._on_data(data)
                elif self.channel.exit_status_ready() and not self.channel.recv_ready():
                    log.info("Удалённый процесс завершён")
                    break
                else:
                    threading.Event().wait(0.01)
        except Exception as e:
            log.error(f"Ошибка чтения: {e}")
            if self._on_error:
                self._on_error(str(e))
        finally:
            self._running = False
            log.info("Соединение закрыто")
            if self._on_close:
                self._on_close()

    def send(self, data: bytes):
        if self.channel and self.channel.send_ready():
            self.channel.send(data)

    def resize(self, cols, rows):
        if self.channel:
            try:
                self.channel.resize_pty(width=cols, height=rows)
                log.info(f"PTY resize -> {cols}x{rows}")
            except Exception as e:
                log.warning(f"resize failed: {e}")

    def disconnect(self):
        log.info("Отключение…")
        self._running = False
        try:
            if self.channel:
                self.channel.close()
            if self.client:
                self.client.close()
        except Exception as e:
            log.warning(f"Ошибка при закрытии: {e}")
