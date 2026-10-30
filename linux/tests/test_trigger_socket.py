import os
import socket
import stat
import threading

import pytest

from clicky.core.trigger_socket import (
    TriggerSocketError,
    TriggerSocketServer,
    default_trigger_socket_path,
    send_toggle_request,
)


@pytest.fixture
def socket_path(tmp_path):
    return tmp_path / "t.sock"


@pytest.fixture
def running_server(socket_path):
    server = TriggerSocketServer(socket_path, lambda: "recording")
    server.start()
    yield server
    server.stop()


def test_socket_file_is_private_to_this_user(socket_path, running_server):
    assert stat.S_IMODE(os.stat(socket_path).st_mode) == 0o600


def test_binding_leaves_the_process_umask_unchanged(socket_path):
    umask_before = os.umask(0o022)
    server = TriggerSocketServer(socket_path, lambda: "recording")
    server.start()
    server.stop()
    assert os.umask(umask_before) == 0o022


def test_toggle_round_trip(socket_path, running_server):
    assert send_toggle_request(socket_path) == "recording"


def test_unknown_requests_do_not_toggle(socket_path):
    toggle_was_called = threading.Event()

    def handle_toggle():
        toggle_was_called.set()
        return "recording"

    server = TriggerSocketServer(socket_path, handle_toggle)
    server.start()
    with socket.socket(socket.AF_UNIX) as client_socket:
        client_socket.connect(str(socket_path))
        client_socket.sendall(b"start recording\n")
        assert client_socket.recv(64).startswith(b"error")
    server.stop()
    assert not toggle_was_called.is_set()


def test_a_second_instance_is_refused_and_leaves_the_first_working(socket_path, running_server):
    second_server = TriggerSocketServer(socket_path, lambda: "second")
    with pytest.raises(TriggerSocketError, match="already running"):
        second_server.start()
    assert send_toggle_request(socket_path) == "recording"


def test_stale_socket_from_a_crash_is_replaced(socket_path):
    with socket.socket(socket.AF_UNIX) as crashed_socket:
        crashed_socket.bind(str(socket_path))
    server = TriggerSocketServer(socket_path, lambda: "recording")
    server.start()
    assert send_toggle_request(socket_path) == "recording"
    server.stop()


def test_a_regular_file_at_the_path_is_never_deleted(socket_path):
    socket_path.write_text("precious")
    with pytest.raises(TriggerSocketError, match="not a socket"):
        TriggerSocketServer(socket_path, lambda: "recording").start()
    assert socket_path.read_text() == "precious"


def test_stop_removes_the_socket_file(socket_path):
    server = TriggerSocketServer(socket_path, lambda: "recording")
    server.start()
    server.stop()
    assert not socket_path.exists()


def test_trigger_with_nothing_running_says_so(socket_path):
    with pytest.raises(TriggerSocketError, match="not running"):
        send_toggle_request(socket_path)


def test_missing_runtime_directory_refuses_rather_than_using_tmp(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with pytest.raises(TriggerSocketError, match="XDG_RUNTIME_DIR"):
        default_trigger_socket_path()
