"""Guards for the Windows artefacts built by scripts/build_installer.py.

The 2.1f build shipped a launcher whose assembly manifest said "2.1f.0.0".
Windows requires four *numeric* parts there and refused to start the exe with
"parallel configuration is incorrect", so the version strings are pinned here.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_installer.py"


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("build_installer_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_assembly_version_is_four_numeric_parts(builder) -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+", builder.VERSION_ASSEMBLY)


def test_rc_version_quad_is_comma_separated(builder) -> None:
    parts = builder.VERSION_QUAD.split(",")
    assert len(parts) == 4
    assert all(part.strip().isdigit() for part in parts)


def test_shipped_binaries_carry_no_assembly_manifest() -> None:
    """No RT_MANIFEST in our exes: SxS loading broke the app on a real machine.

    2.1f..2.1h embedded an assembly manifest and Windows refused to start the
    binary with "parallel configuration is incorrect" (0xc0150004).  The
    installer now elevates itself at runtime instead of via requireAdministrator.
    """
    root = Path(__file__).resolve().parents[1]
    binary = root / "native" / "launcher" / "Zapret-Zen.exe"
    if not binary.exists():
        pytest.skip("launcher binary is not built in this checkout")
    data = binary.read_bytes()
    assert b"requestedExecutionLevel" not in data
    assert b"<assembly xmlns=" not in data


def test_launcher_has_no_console_subsystem() -> None:
    import struct

    binary = Path(__file__).resolve().parents[1] / "native" / "launcher" / "Zapret-Zen.exe"
    if not binary.exists():
        pytest.skip("launcher binary is not built in this checkout")
    data = binary.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe + 24
    subsystem = struct.unpack_from("<H", data, optional + 68)[0]
    assert subsystem == 2, "launcher must be a GUI (windows) subsystem binary"


def test_launcher_has_icon_and_version_resources() -> None:
    import struct

    binary = Path(__file__).resolve().parents[1] / "native" / "launcher" / "Zapret-Zen.exe"
    if not binary.exists():
        pytest.skip("launcher binary is not built in this checkout")
    data = binary.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    dirs = optional + (112 if magic == 0x20B else 96)
    resource_rva = struct.unpack_from("<II", data, dirs + 16)[0]
    assert resource_rva, "launcher lost its .rsrc section (icon/version info)"
