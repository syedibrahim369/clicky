"""The Unix socket behind `python -m clicky --trigger`.

Lets a desktop shortcut start and stop recording on Wayland, where global hotkeys are
not available. Access control is the socket file's 0600 mode inside $XDG_RUNTIME_DIR:
that keeps out other users, but not other programs running as this same user.
"""

import errno
import os
import socket
import stat
import threading
from pathlib import Path
from typing import Callable

SOCKET_FILE_NAME = "clicky-trigger.sock"
TOGGLE_REQUEST = b"toggle\n"
MAXIMUM_REQUEST_BYTES = 32
CLIENT_TIMEOUT_SECONDS = 2.0
ACCEPT_POLL_SECONDS = 0.5


class TriggerSocketError(Exception):
    """Raised with a message suitable for showing to the user."""


def default_trigger_socket_path() -> Path:
    runtime_directory = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_directory:
        # Deliberately no fallback to /tmp, which every user on the machine can reach.
        raise TriggerSocketError("XDG_RUNTIME_DIR is not set, so the trigger socket has nowhere safe to live.")
    return Path(runtime_directory) / SOCKET_FILE_NAME


def is_socket_accepting_connections(socket_path: Path) -> bool:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe_socket:
        probe_socket.settimeout(CLIENT_TIMEOUT_SECONDS)
        try:
            probe_socket.connect(str(socket_path))
        except OSError as connect_error:
            if connect_error.errno in (errno.ECONNREFUSED, errno.ENOENT):
                return False
            raise
    return True


class TriggerSocketServer:
    def __init__(self, socket_path: Path, handle_toggle: Callable[[], str]):
        self.socket_path = socket_path
        self.handle_toggle = handle_toggle
        self.server_socket: socket.socket | None = None
        self.accept_thread: threading.Thread | None = None
        self.should_stop = threading.Event()

    def start(self) -> None:
        self.remove_stale_socket_file()

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # Setting the umask before bind means the file is never briefly world-accessible,
        # which a chmod after bind could not promise.
        previous_umask = os.umask(0o177)
        try:
            self.server_socket.bind(str(self.socket_path))
        finally:
            os.umask(previous_umask)

        socket_mode = stat.S_IMODE(os.stat(self.socket_path).st_mode)
        if socket_mode != 0o600:
            self.stop()
            raise TriggerSocketError(f"Trigger socket has mode {socket_mode:o}, expected 600.")

        self.server_socket.listen(1)
        self.server_socket.settimeout(ACCEPT_POLL_SECONDS)
        self.accept_thread = threading.Thread(target=self.accept_connections, daemon=True)
        self.accept_thread.start()

    def remove_stale_socket_file(self) -> None:
        if not os.path.lexists(self.socket_path):
            return
        if not stat.S_ISSOCK(os.lstat(self.socket_path).st_mode):
            raise TriggerSocketError(f"{self.socket_path} exists and is not a socket; not touching it.")
        if is_socket_accepting_connections(self.socket_path):
            raise TriggerSocketError("Clicky is already running.")
        # A crash leaves the file behind, and bind would fail on it forever.
        self.socket_path.unlink()

    def accept_connections(self) -> None:
        while not self.should_stop.is_set():
            try:
                client_socket, _ = self.server_socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with client_socket:
                self.serve_client(client_socket)

    def serve_client(self, client_socket: socket.socket) -> None:
        client_socket.settimeout(CLIENT_TIMEOUT_SECONDS)
        try:
            request = client_socket.recv(MAXIMUM_REQUEST_BYTES)
            if request == TOGGLE_REQUEST:
                client_socket.sendall(self.handle_toggle().encode() + b"\n")
            elif request:
                client_socket.sendall(b"error: unknown request\n")
        except OSError:
            # A client vanishing mid-request must not take the listener down with it.
            return

    def stop(self) -> None:
        self.should_stop.set()
        if self.server_socket is not None:
            self.server_socket.close()
        if self.accept_thread is not None:
            self.accept_thread.join(timeout=ACCEPT_POLL_SECONDS * 2)
        self.socket_path.unlink(missing_ok=True)


def send_toggle_request(socket_path: Path) -> str:
    """Asks the running app to toggle, returning its reply such as "recording"."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client_socket:
        client_socket.settimeout(CLIENT_TIMEOUT_SECONDS)
        try:
            client_socket.connect(str(socket_path))
        except (FileNotFoundError, ConnectionRefusedError) as connect_error:
            raise TriggerSocketError("Clicky is not running.") from connect_error
        client_socket.sendall(TOGGLE_REQUEST)
        return client_socket.recv(MAXIMUM_REQUEST_BYTES).decode().strip()
