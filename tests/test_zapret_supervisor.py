"""Supervisor and health-tracking tests for ProcessManager.

They exercise only the parts that are platform independent: desired-state
bookkeeping, restart backoff and the UDP port rewrite.  No Windows, no
WinDivert, no real winws.exe is required.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from zapret_zen.services.components import ProcessManager


@pytest.fixture()
def manager() -> ProcessManager:
    storage = MagicMock()
    storage.paths.runtime_dir = Path("/tmp/runtime")
    storage.paths.merged_runtime_dir = Path("/tmp/runtime/merged")
    logging = MagicMock()
    logging.source_log_path.return_value = "/tmp/does-not-exist.log"
    settings = MagicMock()
    settings.get.return_value = SimpleNamespace(
        selected_service_ids=["youtube"],
        youtube_stability=True,
        zapret_block_quic=False,
        zapret_udp_exclude_ports="",
    )
    instance = ProcessManager(storage, logging, settings)
    instance.logging = logging
    # Never shell out to sc.exe/tasklist/taskkill from unit tests.
    instance._run_quiet = lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="")  # type: ignore[assignment]
    instance._service_exists = lambda name: False  # type: ignore[assignment]
    instance._cleanup_zapret_driver_services = lambda *args, **kwargs: None  # type: ignore[assignment]
    instance._kill_image = lambda name: None  # type: ignore[assignment]
    return instance


class _FakeProcess:
    def __init__(self, pid: int = 1234, returncode: int | None = None) -> None:
        self.pid = pid
        self._returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = 0

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self._returncode if self._returncode is not None else 0


# --- desired-state bookkeeping ------------------------------------------------


def test_stop_clears_desired_state_and_supervisor_never_restarts(manager: ProcessManager) -> None:
    manager._zapret_desired_running = True
    manager.stop_component("zapret")
    assert manager._zapret_desired_running is False
    assert manager.supervise_zapret(now=time.monotonic()) is None


def test_supervisor_ignores_healthy_process(manager: ProcessManager) -> None:
    manager._zapret_desired_running = True
    manager._processes["zapret"] = _FakeProcess(returncode=None)  # type: ignore[assignment]
    assert manager.supervise_zapret(now=time.monotonic()) is None


def test_supervisor_skips_diagnostics_override(manager: ProcessManager) -> None:
    manager._zapret_desired_running = True
    manager._diagnostic_runtime_override = True
    manager._processes["zapret"] = _FakeProcess(returncode=1)  # type: ignore[assignment]
    assert manager.supervise_zapret(now=time.monotonic()) is None


def test_supervisor_schedules_backoff_then_restarts(manager: ProcessManager) -> None:
    started: list[str] = []

    def fake_start(component_id: str):
        started.append(component_id)
        return SimpleNamespace(component_id=component_id, status="running", pid=999, last_error="")

    manager._start_zapret = fake_start  # type: ignore[assignment]
    manager._zapret_desired_running = True
    manager._processes["zapret"] = _FakeProcess(returncode=1)  # type: ignore[assignment]

    state = manager.supervise_zapret(now=100.0)
    assert state is not None
    assert state.status == "error"
    assert "restarting in 2s" in state.last_error
    assert manager._zapret_next_retry_at == pytest.approx(102.0)
    assert started == []

    # Too early: the supervisor stays quiet and does not start anything.
    assert manager.supervise_zapret(now=101.0) is None
    assert started == []

    # After the delay the restart actually occurs.
    state = manager.supervise_zapret(now=102.5)
    assert started == ["zapret"]
    assert state is not None and state.status == "running"


def test_supervisor_locks_after_three_crashes_in_a_minute(manager: ProcessManager) -> None:
    calls: list[str] = []

    def fake_start(component_id: str):
        calls.append(component_id)
        return SimpleNamespace(component_id=component_id, status="error", pid=None, last_error="boom")

    manager._start_zapret = fake_start  # type: ignore[assignment]
    manager._zapret_desired_running = True
    # Simulate the worker heartbeat: one tick per second, winws dead each time.
    now = 1000.0
    for _ in range(60):
        manager._processes["zapret"] = _FakeProcess(returncode=1)  # type: ignore[assignment]
        manager.supervise_zapret(now=now)
        now += 1.0
    assert manager._zapret_supervisor_locked is True
    # Backoff is honoured: 2 s, 5 s, 15 s and then no fourth automatic attempt.
    assert len(calls) == 3
    state = manager._states["zapret"]
    assert "crashed repeatedly" in state.last_error
    # Once locked, further calls are no-ops until the user presses Start.
    assert manager.supervise_zapret(now=now) is None


def test_start_component_resets_supervisor_lock(manager: ProcessManager) -> None:
    manager._zapret_supervisor_locked = True
    manager._zapret_restart_attempts.append(1.0)
    manager._start_zapret = lambda component_id: SimpleNamespace(  # type: ignore[assignment]
        component_id=component_id, status="running", pid=1, last_error=""
    )
    manager.list_components = lambda: [  # type: ignore[assignment]
        SimpleNamespace(id="zapret", enabled=True, autostart=True)
    ]
    manager.start_component("zapret")
    assert manager._zapret_supervisor_locked is False
    assert list(manager._zapret_restart_attempts) == []
    assert manager._zapret_desired_running is True


# --- owned process handling ---------------------------------------------------


def test_force_stop_only_touches_owned_process(manager: ProcessManager) -> None:
    process = _FakeProcess(returncode=None)
    manager._processes["zapret"] = process  # type: ignore[assignment]
    killed_images: list[str] = []
    manager._kill_image = lambda name: killed_images.append(name)  # type: ignore[assignment]
    manager._cleanup_zapret_driver_services = lambda *args, **kwargs: None  # type: ignore[assignment]

    assert manager._force_stop_zapret_runtime() is True
    assert process.terminated is True
    assert killed_images == []
    assert "zapret" not in manager._processes


def test_force_stop_reports_failure_when_child_survives(manager: ProcessManager) -> None:
    process = _FakeProcess(returncode=None)
    process.terminate = lambda: None  # type: ignore[assignment]
    process.kill = lambda: None  # type: ignore[assignment]
    manager._processes["zapret"] = process  # type: ignore[assignment]
    manager._run_quiet = lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr="")  # type: ignore[assignment]
    manager._cleanup_zapret_driver_services = lambda *args, **kwargs: None  # type: ignore[assignment]

    assert manager._force_stop_zapret_runtime() is False


def test_stop_component_marks_error_when_stop_fails(manager: ProcessManager) -> None:
    manager._force_stop_zapret_runtime = lambda: False  # type: ignore[assignment]
    manager._current_zapret_runtime = None
    state = manager.stop_component("zapret")
    assert state.status == "error"
    assert "Failed to stop" in state.last_error


def test_readiness_helper_marks_process_dead_on_exit(manager: ProcessManager) -> None:
    process = _FakeProcess(pid=42, returncode=7)
    assert manager._wait_for_owned_winws(process, grace=0.05) is False  # type: ignore[arg-type]
    assert manager._zapret_last_exit_code == 7


def test_readiness_helper_accepts_silent_but_alive_process(manager: ProcessManager) -> None:
    process = _FakeProcess(pid=42, returncode=None)
    assert manager._wait_for_owned_winws(process, grace=0.05) is True  # type: ignore[arg-type]
    assert manager._zapret_ready is False


def test_readiness_helper_clears_stale_ready_flag(manager: ProcessManager) -> None:
    manager._zapret_ready = True
    process = _FakeProcess(pid=42, returncode=0)
    manager._wait_for_owned_winws(process, grace=0.05)  # type: ignore[arg-type]
    assert manager._zapret_ready is False


# --- configuration rewriting --------------------------------------------------


def test_udp_exclusion_never_leaves_port_12(manager: ProcessManager) -> None:
    command = ["--wf-tcp=443", "--wf-udp=443,50000-50100", "--filter-udp=443", "--dpi-desync=fake"]
    result = manager._exclude_udp_ports_from_command(command, [(443, 443), (50000, 50100)])
    assert not any(arg.endswith("=12") for arg in result)
    assert "--wf-tcp=443" in result


def test_youtube_guard_respects_selected_services(manager: ProcessManager, tmp_path: Path) -> None:
    settings = MagicMock()
    settings.get.return_value = SimpleNamespace(
        selected_service_ids=["telegram-desktop"],
        youtube_stability=True,
        zapret_block_quic=False,
    )
    manager.settings = settings
    command = ["--wf-udp=443", "--filter-udp=443", "--dpi-desync=fake"]
    assert manager._apply_youtube_stability(command, lists_dir=tmp_path, bin_dir=tmp_path) == command


def test_youtube_guard_applied_for_youtube_service(manager: ProcessManager, tmp_path: Path) -> None:
    command = ["--wf-udp=443", "--filter-udp=443", "--dpi-desync=fake", "--dpi-desync-repeats=6"]
    result = manager._apply_youtube_stability(command, lists_dir=tmp_path, bin_dir=tmp_path)
    assert "--filter-l7=quic" in result
    assert f"--hostlist={tmp_path / 'list-youtube.txt'}" in result


# --- connectivity probes ------------------------------------------------------


def test_check_target_repeats_probe_for_every_attempt(manager: ProcessManager) -> None:
    calls: list[list[str]] = []

    def fake_curl(url: str, extra_args: list[str], *, ranged: bool = False) -> int:
        calls.append(extra_args)
        return 200

    manager._curl_status = fake_curl  # type: ignore[assignment]
    manager._quic_probe_blocked = lambda host: False  # type: ignore[assignment]
    assert manager._check_target({"type": "url", "url": "https://x/y", "repeat": "3"}) == "ok"
    assert len(calls) == 3


def test_check_target_fails_when_any_repetition_fails(manager: ProcessManager) -> None:
    results = iter([200, 0, 0, 0, 0])

    def fake_curl(url: str, extra_args: list[str], *, ranged: bool = False) -> int:
        return next(results, 0)

    manager._curl_status = fake_curl  # type: ignore[assignment]
    manager._quic_probe_blocked = lambda host: False  # type: ignore[assignment]
    assert manager._check_target({"type": "url", "url": "https://x/y", "repeat": "3"}) == "failed"


def test_check_target_reports_blocked_on_451(manager: ProcessManager) -> None:
    manager._curl_status = lambda url, extra, ranged=False: 451  # type: ignore[assignment]
    manager._quic_probe_blocked = lambda host: False  # type: ignore[assignment]
    assert manager._check_target({"type": "url", "url": "https://x/y"}) == "blocked"


def test_check_target_range_uses_get_request(manager: ProcessManager) -> None:
    seen: list[bool] = []

    def fake_curl(url: str, extra_args: list[str], *, ranged: bool = False) -> int:
        seen.append(ranged)
        return 206

    manager._curl_status = fake_curl  # type: ignore[assignment]
    manager._quic_probe_blocked = lambda host: False  # type: ignore[assignment]
    assert manager._check_target({"type": "url", "url": "https://x/y", "range": "1"}) == "ok"
    assert seen and all(seen)


def test_convert_test_target_parses_stability_syntax(manager: ProcessManager) -> None:
    target = manager._convert_test_target("YouTube CDN", "REPEAT3:RANGE:https://i.ytimg.com/vi/x/hq.jpg")
    assert target["type"] == "url"
    assert target["repeat"] == "3"
    assert target["range"] == "1"
    assert target["host"] == "i.ytimg.com"
    assert target["url"] == "https://i.ytimg.com/vi/x/hq.jpg"


def test_convert_test_target_plain_ping_unchanged(manager: ProcessManager) -> None:
    target = manager._convert_test_target("DNS", "PING:8.8.8.8")
    assert target == {"name": "DNS", "type": "ping", "host": "8.8.8.8"}


def test_convert_test_target_clamps_repeat(manager: ProcessManager) -> None:
    assert manager._convert_test_target("x", "REPEAT99:https://a.b")["repeat"] == "10"
    assert "repeat" not in manager._convert_test_target("x", "REPEAT1:https://a.b")


def test_readiness_warning_respects_grace_period(manager: ProcessManager) -> None:
    logged: list[str] = []
    manager.logging.log = lambda level, message, **kwargs: logged.append(message)  # type: ignore[assignment]
    process = _FakeProcess(pid=7, returncode=None)
    manager._zapret_started_at = 100.0
    manager._zapret_ready = False
    # Inside the grace window nothing is reported: stdout may still be buffered.
    manager._note_zapret_ready_state(process, now=105.0)  # type: ignore[arg-type]
    assert logged == []
    # After the grace window a live-but-idle winws is reported exactly once.
    manager._note_zapret_ready_state(process, now=130.0)  # type: ignore[arg-type]
    manager._note_zapret_ready_state(process, now=140.0)  # type: ignore[arg-type]
    assert len(logged) == 1 and "did not report WinDivert capture" in logged[0]


# --- fatal start errors: no endless "restarting in Ns" -----------------------

def test_config_error_locks_supervisor_instead_of_restarting(manager: ProcessManager) -> None:
    """A rejected command line can never be fixed by restarting it."""
    manager._zapret_desired_running = True
    manager._processes["zapret"] = _FakeProcess(returncode=1)  # type: ignore[assignment]
    manager._zapret_last_start_error = (
        "winws отклонил параметры запуска или не смог захватить трафик (код 1). "
        "Лог: unknown option --dpi-desync"
    )
    state = manager.supervise_zapret(now=100.0)
    assert state is not None
    assert manager._zapret_supervisor_locked is True
    assert "restarting in" not in state.last_error
    assert "отклонил параметры" in state.last_error


def test_transient_crash_still_gets_regular_backoff(manager: ProcessManager) -> None:
    manager._zapret_desired_running = True
    manager._processes["zapret"] = _FakeProcess(returncode=0)  # type: ignore[assignment]
    manager._zapret_last_start_error = ""
    state = manager.supervise_zapret(now=100.0)
    assert state is not None
    assert "restarting in 2s" in state.last_error
    assert manager._zapret_supervisor_locked is False


def test_exit_code_explanations_are_actionable() -> None:
    explain = ProcessManager._explain_zapret_exit_code
    assert "0xC0000135" in explain(-1073741515)
    assert "0xC0000005" in explain(-1073741819)
    assert "администратора" in explain(5)
    assert explain(None) == ""
