"""Unit tests for the pure winws command helpers.

These run on any platform: they never touch WinDivert, winws.exe or the network.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from zapret_zen.services.zapret_command import (
    apply_youtube_quic_guard,
    exclude_udp_ports,
    join_profiles,
    missing_command_files,
    split_profiles,
)


def _base_command(tmp_path: Path) -> list[str]:
    lists = tmp_path / "lists"
    bin_dir = tmp_path / "bin"
    lists.mkdir()
    bin_dir.mkdir()
    (lists / "list-general.txt").write_text("youtube.com\n", encoding="utf-8")
    (bin_dir / "quic_initial_www_google_com.bin").write_bytes(b"\x00" * 4)
    return [
        "--wf-tcp=80,443",
        "--wf-udp=443,50000-50100",
        "--filter-tcp=80,443",
        f"--hostlist={lists / 'list-general.txt'}",
        "--dpi-desync=split2",
        "--new",
        "--filter-udp=443",
        "--hostlist-exclude=/tmp/exclude.txt",
        "--dpi-desync=fake",
        "--dpi-desync-repeats=6",
        f"--dpi-desync-fake-quic={bin_dir / 'quic_initial_www_google_com.bin'}",
        "--new",
        "--filter-udp=50000-50100",
        "--dpi-desync=fake",
    ]


class TestSplitJoin:
    def test_roundtrip_is_lossless(self, tmp_path: Path) -> None:
        command = _base_command(tmp_path)
        global_args, profiles = split_profiles(command)
        assert global_args == ["--wf-tcp=80,443", "--wf-udp=443,50000-50100"]
        assert len(profiles) == 3
        assert join_profiles(global_args, profiles) == command

    def test_global_flags_are_not_placed_inside_profiles(self) -> None:
        global_args, profiles = split_profiles(["--wf-tcp=443", "--debug=1", "--filter-tcp=443", "--dpi-desync=fake"])
        assert global_args == ["--wf-tcp=443", "--debug=1"]
        assert profiles == [["--filter-tcp=443", "--dpi-desync=fake"]]

    def test_consecutive_new_markers_do_not_create_empty_profiles(self) -> None:
        global_args, profiles = split_profiles(["--wf-tcp=443", "--new", "--new", "--filter-tcp=443"])
        assert global_args == ["--wf-tcp=443"]
        assert profiles == [["--filter-tcp=443"]]


class TestExcludeUdpPorts:
    def test_partial_exclusion_keeps_remaining_ports(self, tmp_path: Path) -> None:
        command = _base_command(tmp_path)
        result = exclude_udp_ports(command, [(50000, 50050)])
        assert "--wf-udp=443,50051-50100" in result
        assert "--filter-udp=50051-50100" in result
        assert any(arg == "--filter-udp=443" for arg in result)

    def test_no_port_12_sentinel_is_ever_produced(self, tmp_path: Path) -> None:
        command = _base_command(tmp_path)
        result = exclude_udp_ports(command, [(443, 443), (50000, 50100)])
        assert not any(arg.endswith("=12") for arg in result)
        # The fully excluded profile is dropped and the empty capture filter too.
        assert not any(arg.startswith("--wf-udp=") for arg in result)
        assert not any(arg.startswith("--filter-udp=443") for arg in result)

    def test_fully_excluded_profile_is_removed(self, tmp_path: Path) -> None:
        command = _base_command(tmp_path)
        result = exclude_udp_ports(command, [(50000, 50100)])
        global_args, profiles = split_profiles(result)
        assert global_args == ["--wf-tcp=80,443", "--wf-udp=443"]
        assert [profile[0] for profile in profiles] == ["--filter-tcp=80,443", "--filter-udp=443"]

    def test_empty_exclusion_returns_copy(self, tmp_path: Path) -> None:
        command = _base_command(tmp_path)
        result = exclude_udp_ports(command, [])
        assert result == command
        assert result is not command


class TestYoutubeQuicGuard:
    def test_guard_is_inserted_before_generic_udp_profile(self, tmp_path: Path) -> None:
        command = _base_command(tmp_path)
        result = apply_youtube_quic_guard(
            command,
            lists_dir=tmp_path / "lists",
            bin_dir=tmp_path / "bin",
            enabled=True,
        )
        global_args, profiles = split_profiles(result)
        assert global_args == ["--wf-tcp=80,443", "--wf-udp=443,50000-50100"]
        guard = profiles[1]
        assert "--filter-udp=443" in guard
        assert "--filter-l7=quic" in guard
        assert f"--hostlist={tmp_path / 'lists' / 'list-youtube.txt'}" in guard
        assert "--dpi-desync-cutoff=n6" in guard
        # Repeats are raised to the upstream ALT value, never lowered below it.
        assert "--dpi-desync-repeats=11" in guard
        # Exclusions of the strategy are inherited so VPN/user excludes survive.
        assert "--hostlist-exclude=/tmp/exclude.txt" in guard
        # TLS backbone untouched.
        assert profiles[0] == split_profiles(command)[1][0]

    def test_disabled_setting_returns_unchanged_command(self, tmp_path: Path) -> None:
        command = _base_command(tmp_path)
        assert apply_youtube_quic_guard(command, lists_dir=tmp_path, bin_dir=tmp_path, enabled=False) == command

    def test_quic_blocked_returns_unchanged_command(self, tmp_path: Path) -> None:
        command = _base_command(tmp_path)
        assert (
            apply_youtube_quic_guard(command, lists_dir=tmp_path, bin_dir=tmp_path, enabled=True, quic_blocked=True)
            == command
        )

    def test_idempotent_when_guard_already_present(self, tmp_path: Path) -> None:
        command = _base_command(tmp_path)
        once = apply_youtube_quic_guard(command, lists_dir=tmp_path / "lists", bin_dir=tmp_path / "bin", enabled=True)
        twice = apply_youtube_quic_guard(once, lists_dir=tmp_path / "lists", bin_dir=tmp_path / "bin", enabled=True)
        assert once == twice

    def test_no_guard_without_udp_443_capture(self, tmp_path: Path) -> None:
        command = [arg for arg in _base_command(tmp_path) if not arg.startswith("--wf-udp=")]
        assert apply_youtube_quic_guard(command, lists_dir=tmp_path, bin_dir=tmp_path, enabled=True) == command

    def test_no_guard_without_udp_443_profile(self, tmp_path: Path) -> None:
        command = [
            "--wf-tcp=443",
            "--wf-udp=50000-50100",
            "--filter-tcp=443",
            "--dpi-desync=split2",
            "--new",
            "--filter-udp=50000-50100",
            "--dpi-desync=fake",
        ]
        assert apply_youtube_quic_guard(command, lists_dir=tmp_path, bin_dir=tmp_path, enabled=True) == command

    def test_repeats_follow_strategy_when_higher(self, tmp_path: Path) -> None:
        command = _base_command(tmp_path)
        command = ["--dpi-desync-repeats=13" if arg == "--dpi-desync-repeats=6" else arg for arg in command]
        result = apply_youtube_quic_guard(command, lists_dir=tmp_path / "lists", bin_dir=tmp_path / "bin", enabled=True)
        assert "--dpi-desync-repeats=13" in result


class TestMissingCommandFiles:
    def test_reports_missing_list_and_payload(self, tmp_path: Path) -> None:
        command = [
            "winws.exe",
            f"--hostlist={tmp_path / 'nope.txt'}",
            f"--dpi-desync-fake-quic={tmp_path / 'nope.bin'}",
            "--dpi-desync=fake",
        ]
        missing = missing_command_files(command)
        assert len(missing) == 2

    def test_ignores_existing_files_and_inline_payloads(self, tmp_path: Path) -> None:
        existing = tmp_path / "list.txt"
        existing.write_text("a\n", encoding="utf-8")
        command = [
            "winws.exe",
            f"--hostlist={existing}",
            "--dpi-desync-fake-tls=0x00ff00",
            "--dpi-desync-fake-quic=0xdeadbeef",
            "--filter-udp=443",
        ]
        assert missing_command_files(command) == []

    def test_handles_quoted_paths_and_offset_syntax(self, tmp_path: Path) -> None:
        payload = tmp_path / "payload.bin"
        payload.write_bytes(b"\x00")
        command = [
            "winws.exe",
            '--hostlist="%s"' % (tmp_path / "missing.txt"),
            f"--dpi-desync-fake-tls=16@{payload}",
        ]
        missing = missing_command_files(command)
        assert missing == [str(tmp_path / "missing.txt")]


def test_youtube_domains_cover_music_and_cdn() -> None:
    from zapret_zen.services.zapret_command import YOUTUBE_STABILITY_DOMAINS

    for domain in ("googlevideo.com", "music.youtube.com", "ytimg.com", "youtubei.googleapis.com"):
        assert domain in YOUTUBE_STABILITY_DOMAINS


@pytest.mark.parametrize("value", ["", "--wf-udp=", "--filter-udp=abc"])
def test_exclude_udp_ports_is_robust(value: str, tmp_path: Path) -> None:
    command = ["--wf-tcp=443", value, "--filter-tcp=443"] if value else ["--wf-tcp=443", "--filter-tcp=443"]
    assert exclude_udp_ports(command, [(443, 443)]) is not None
