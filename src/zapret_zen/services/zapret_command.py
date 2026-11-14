"""Pure helpers for transforming parsed winws command lines.

The upstream ``general*.bat`` files remain the source of the TLS strategy.  These
helpers only add a narrowly scoped QUIC profile for YouTube/YT Music and make UDP
port exclusions lossless.  Keeping the logic pure makes it testable without
WinDivert or a Windows driver.
"""
from __future__ import annotations

import re
from pathlib import Path

YOUTUBE_STABILITY_DOMAINS: tuple[str, ...] = (
    "googlevideo.com",
    "www.googlevideo.com",
    "youtube.com",
    "music.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "youtube.googleapis.com",
    "youtubei.googleapis.com",
    "youtubeembeddedplayer.googleapis.com",
    "youtubekids.com",
    "ytimg.com",
    "ytimg.l.google.com",
    "yt3.ggpht.com",
    "yt4.ggpht.com",
    "yt3.googleusercontent.com",
    "wide-youtube.l.google.com",
    "youtube-ui.l.google.com",
    "yt-video-upload.l.google.com",
    "jnn-pa.googleapis.com",
)

_GLOBAL_PREFIXES = (
    "--wf-", "--debug", "--ctrack-", "--ssid", "--nlm", "--daemon", "--pidfile",
)
_FILE_ARG_PREFIXES = (
    "--hostlist=", "--hostlist-exclude=", "--ipset=",
    "--ipset-exclude=", "--dpi-desync-fake-quic=", "--dpi-desync-fake-tls=",
    "--dpi-desync-fake-http=", "--dpi-desync-fake-discord=", "--dpi-desync-fake-stun=",
    "--dpi-desync-fake-unknown=", "--dpi-desync-fake-unknown-udp=",
    "--dpi-desync-split-seqovl-pattern=", "--dpi-desync-split-seqovl-pattern=",
)


def _is_global(arg: str) -> bool:
    return any(arg.startswith(prefix) for prefix in _GLOBAL_PREFIXES)


def split_profiles(command: list[str]) -> tuple[list[str], list[list[str]]]:
    """Return global arguments and ordered desync profiles (without ``--new``)."""
    global_args: list[str] = []
    profiles: list[list[str]] = []
    current: list[str] = []
    for arg in command:
        if arg == "--new":
            if current:
                profiles.append(current)
                current = []
            continue
        if _is_global(arg):
            global_args.append(arg)
        else:
            current.append(arg)
    if current:
        profiles.append(current)
    return global_args, profiles


def join_profiles(global_args: list[str], profiles: list[list[str]]) -> list[str]:
    result = list(global_args)
    for index, profile in enumerate(profiles):
        if index:
            result.append("--new")
        result.extend(profile)
    return result


def _port_ranges(value: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for token in re.split(r"[\s,;]+", value.strip()):
        if not token:
            continue
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", token)
        if not match:
            continue
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start > end:
            start, end = end, start
        if 1 <= start <= end <= 65535:
            ranges.append((start, end))
    return ranges


def _format_ranges(ranges: list[tuple[int, int]]) -> str:
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)


def _subtract(ranges: list[tuple[int, int]], excluded: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result = list(ranges)
    for ex_start, ex_end in excluded:
        next_result: list[tuple[int, int]] = []
        for start, end in result:
            if ex_end < start or ex_start > end:
                next_result.append((start, end))
                continue
            if start < ex_start:
                next_result.append((start, ex_start - 1))
            if ex_end < end:
                next_result.append((ex_end + 1, end))
        result = next_result
    return result


def _filter_value(profile: list[str], key: str) -> str:
    prefix = f"--filter-{key}="
    return ",".join(arg[len(prefix):] for arg in profile if arg.startswith(prefix))


def _profile_matches_udp(profile: list[str], port: int) -> bool:
    return any(start <= port <= end for start, end in _port_ranges(_filter_value(profile, "udp")))


def exclude_udp_ports(command: list[str], excluded: list[tuple[int, int]]) -> list[str]:
    """Remove excluded UDP ports without the old ``port 12`` sentinel hack.

    If a profile's UDP filter becomes empty, the whole profile is removed.  If
    the capture filter becomes empty, ``--wf-udp`` is removed as well.
    """
    if not command or not excluded:
        return list(command)
    global_args, profiles = split_profiles(command)
    new_global: list[str] = []
    capture_ranges: list[tuple[int, int]] = []
    for arg in global_args:
        if arg.startswith("--wf-udp="):
            capture_ranges = _subtract(_port_ranges(arg.split("=", 1)[1]), excluded)
            if capture_ranges:
                new_global.append(f"--wf-udp={_format_ranges(capture_ranges)}")
        else:
            new_global.append(arg)
    new_profiles: list[list[str]] = []
    for profile in profiles:
        udp_value = _filter_value(profile, "udp")
        if not udp_value:
            new_profiles.append(profile)
            continue
        remaining = _subtract(_port_ranges(udp_value), excluded)
        if not remaining:
            continue
        updated = [
            f"--filter-udp={_format_ranges(remaining)}" if arg.startswith("--filter-udp=") else arg
            for arg in profile
        ]
        new_profiles.append(updated)
    return join_profiles(new_global, new_profiles)


def udp_443_profile_count(command: list[str]) -> int:
    """How many desync profiles target UDP 443 at all."""
    _global_args, profiles = split_profiles(command)
    return sum(1 for profile in profiles if _profile_matches_udp(profile, 443))


def uses_quic_bypass_data(command: list[str], *, excluded_domains: tuple[str, ...] = YOUTUBE_STABILITY_DOMAINS) -> bool:
    """True when a UDP-443 profile bypasses traffic *outside* YouTube.

    Blocking QUIC machine-wide is the most reliable cure for hanging YouTube
    playback, but it breaks Discord voice and games that rely on QUIC.  A
    strategy that already desyncs every UDP-443 flow (no host/IP restriction)
    makes the global block redundant — in that case we keep QUIC untouched.
    """
    _global_args, profiles = split_profiles(command)
    for profile in profiles:
        if not _profile_matches_udp(profile, 443):
            continue
        if not any(arg.startswith("--filter-l7=") and "quic" in arg.lower() for arg in profile):
            continue
        restrictions = [
            arg for arg in profile
            if arg.startswith(("--hostlist=", "--hostlist-domains=", "--ipset=", "--filter-host="))
        ]
        if not restrictions:
            return True
        if all(any(domain in arg.lower() for domain in excluded_domains) for arg in restrictions):
            continue
        return False
    return False


def apply_youtube_quic_guard(
    command: list[str],
    *,
    lists_dir: Path,
    bin_dir: Path,
    enabled: bool,
    quic_blocked: bool = False,
) -> list[str]:
    """Insert a YouTube-only QUIC Initial profile before the generic UDP profile.

    The guard reuses the selected strategy's exclusions and fake QUIC payload,
    raises only the Initial repeat count to the upstream ALT value (11), and
    stops touching the flow after six packets.  TLS profiles and non-YouTube UDP
    traffic are left untouched.  If the user disabled UDP 443 capture or blocked
    QUIC globally, no guard is added.
    """
    if not enabled or not command:
        return list(command)
    # With a machine-wide QUIC block the YouTube guard would be dead weight:
    # no QUIC Initial ever leaves the machine.
    if quic_blocked:
        return list(command)
    global_args, profiles = split_profiles(command)
    if not any(arg.startswith("--wf-udp=") and _profile_matches_udp([arg.replace("--wf-", "--filter-", 1)], 443) for arg in global_args):
        return list(command)
    target_index = next((i for i, profile in enumerate(profiles) if _profile_matches_udp(profile, 443)), None)
    if target_index is None:
        return list(command)
    hostlist = str(lists_dir / "list-youtube.txt")
    if any(hostlist in arg for profile in profiles for arg in profile):
        return list(command)
    udp_profiles = [profile for profile in profiles if _profile_matches_udp(profile, 443)]
    exclusions: list[str] = []
    seen: set[str] = set()
    repeats = 11
    payload = str(bin_dir / "quic_initial_www_google_com.bin")
    for profile in udp_profiles:
        for arg in profile:
            if arg.startswith(("--hostlist-exclude=", "--ipset-exclude=", "--filter-l3=")) and arg not in seen:
                seen.add(arg)
                exclusions.append(arg)
            if arg.startswith("--dpi-desync-repeats="):
                try:
                    repeats = max(repeats, min(16, int(arg.split("=", 1)[1])))
                except ValueError:
                    pass
            if arg.startswith("--dpi-desync-fake-quic="):
                payload = arg.split("=", 1)[1]
    guard = [
        "--filter-udp=443",
        "--filter-l7=quic",
        f"--hostlist={hostlist}",
        *exclusions,
        "--dpi-desync=fake",
        f"--dpi-desync-repeats={repeats}",
        f"--dpi-desync-fake-quic={payload}",
        "--dpi-desync-cutoff=n6",
    ]
    profiles.insert(target_index, guard)
    return join_profiles(global_args, profiles)


def split_windows_command_line(text: str) -> list[str]:
    """Split a Windows command line the way CommandLineToArgvW does.

    ``shlex.split(..., posix=False)`` looks like the obvious tool, but it breaks
    the single most common argument in these scripts: a quoted path that contains
    a space (``--hostlist="C:\\Program Files\\Zapret-Zen\\lists\\x.txt"``)
    becomes ``--hostlist="C:\\Program`` + ``Files\\...\\x.txt"``.  winws then
    receives a truncated hostlist path and refuses to start.

    This parser follows the Windows rules instead:
      * backslashes are literal unless they precede a double quote;
      * a double quote toggles quoting and is removed, except for the special
        ``""`` empty-argument case;
      * unquoted whitespace separates arguments.
    """
    args: list[str] = []
    current: list[str] = []
    in_quotes = False
    has_token = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            run_start = index
            while index < length and text[index] == "\\":
                index += 1
            run_length = index - run_start
            if index < length and text[index] == '"':
                # 2n backslashes + quote -> n backslashes and a literal quote;
                # 2n+1 backslashes + quote -> n backslashes and a quote toggle.
                current.append("\\" * (run_length // 2))
                has_token = True
                if run_length % 2:
                    current.append('"')
                    index += 1  # consume the escaped quote
                else:
                    in_quotes = not in_quotes
                    index += 1  # consume the delimiter quote
                continue
            current.append("\\" * run_length)
            has_token = True
            continue
        if char == '"':
            if in_quotes and index + 1 < length and text[index + 1] == '"':
                current.append('"')
                has_token = True
                index += 2
                continue
            in_quotes = not in_quotes
            has_token = True
            index += 1
            continue
        if char in " \t" and not in_quotes:
            if has_token:
                args.append("".join(current))
                current = []
                has_token = False
            index += 1
            continue
        current.append(char)
        has_token = True
        index += 1
    if has_token:
        args.append("".join(current))
    return args

def missing_command_files(command: list[str]) -> list[str]:
    """Return missing file arguments that would make winws exit at startup."""
    missing: list[str] = []
    seen: set[str] = set()
    for arg in command[1:]:
        for prefix in _FILE_ARG_PREFIXES:
            if not arg.startswith(prefix):
                continue
            value = arg[len(prefix):].strip().strip('"')
            # winws supports inline hex payloads and +offset@file syntax.
            if not value or value.startswith("0x"):
                continue
            if "@" in value and not Path(value).exists():
                value = value.split("@", 1)[1]
            if value in seen:
                continue
            seen.add(value)
            if not Path(value).is_file():
                missing.append(value)
    return missing
