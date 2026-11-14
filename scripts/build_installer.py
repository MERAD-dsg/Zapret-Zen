"""Build the Windows launcher (`Zapret-Zen.exe`) and the installer.

Both artefacts are cross-compiled with Zig, so a Linux/CI host without the
Windows SDK can produce them:

    python scripts/build_installer.py --prepare      # launcher + payload only
    python scripts/build_installer.py                # + setup exe (embedded zip)

Zig is fetched from PyPI (`pip install ziglang`) when it is not on PATH; the
result is a genuinely native Windows binary, not a script wrapper.

Why a native launcher: with the portable layout the taskbar button, tray
balloon and task manager entry belong to the *hosting* executable, so users saw
"Python" beside "Zapret-Zen" (and, when elevating through python.exe, an extra
console window stayed alive).  `Zapret-Zen.exe` starts `pythonw.exe` hidden and
returns immediately, so one window is all the user ever sees.
"""
from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
LAUNCHER_C = NATIVE / "launcher" / "launcher.c"
INSTALLER_ZIG = NATIVE / "installer" / "installer.zig"
ICON = ROOT / "ui_assets" / "icons" / "app.ico"

APP_NAME = "Zapret-Zen"
VERSION = "2.1i"
# Windows assembly identities need four *numeric* parts: "2.1f.0.0" makes the
# loader reject the exe with "parallel configuration is incorrect" (0xc0150004).
VERSION_ASSEMBLY = "2.1.3.0"
VERSION_QUAD = VERSION_ASSEMBLY.replace(".", ",")


def _find_zig() -> str:
    env = os.environ.get("ZIG")
    if env and Path(env).exists():
        return env
    for name in ("zig", "zig.exe"):
        found = shutil.which(name)
        if found:
            return found
    try:
        import ziglang  # type: ignore

        candidate = Path(ziglang.__file__).parent / "zig"
        if candidate.exists():
            candidate.chmod(0o755)
            return str(candidate)
    except Exception:
        pass
    raise SystemExit(
        "Zig not found. Install it with `pip install ziglang` (or put zig on PATH)."
    )


def _write_rc(path: Path, exe_name: str, description: str) -> Path:
    """Emit a .rc script (icon + version info) and compile it with `zig rc`.

    Deliberately no RT_MANIFEST: an embedded assembly manifest makes Windows run
    the side-by-side (SxS) loader, and the "parallel configuration is incorrect"
    dialog appeared on a real machine even with a valid manifest.  Nothing here
    needs SxS - the controls are classic USER32 widgets - so the manifest is
    dropped and the installer raises UAC itself (see installer.zig).
    """
    icon = ICON.as_posix()
    rc_path = path.with_suffix(".rc")
    rc_path.write_text(
        f'#include <winver.h>\n'
        f'1 ICON "{icon}"\n\n'
        f'VS_VERSION_INFO VERSIONINFO\n'
        f' FILEVERSION {VERSION_QUAD}\n'
        f' PRODUCTVERSION {VERSION_QUAD}\n'
        f' FILEFLAGSMASK 0x3fL\n FILEFLAGS 0x0L\n FILEOS 0x40004L\n FILETYPE 0x1L\n FILESUBTYPE 0x0L\n'
        f'BEGIN\n'
        f'    BLOCK "StringFileInfo"\n    BEGIN\n        BLOCK "041904B0"\n        BEGIN\n'
        f'            VALUE "CompanyName", "Zapret-Zen"\n'
        f'            VALUE "FileDescription", "{description}"\n'
        f'            VALUE "FileVersion", "{VERSION_ASSEMBLY}"\n'
        f'            VALUE "InternalName", "{exe_name}"\n'
        f'            VALUE "OriginalFilename", "{exe_name}.exe"\n'
        f'            VALUE "ProductName", "Zapret-Zen"\n'
        f'            VALUE "ProductVersion", "{VERSION_ASSEMBLY}"\n'
        f'        END\n    END\n'
        f'    BLOCK "VarFileInfo"\n    BEGIN\n        VALUE "Translation", 0x419, 1200\n    END\n'
        f'END\n',
        encoding="utf-8",
    )
    res_path = path.with_suffix(".res")
    subprocess.run([_find_zig(), "rc", f"/fo", str(res_path), "--", str(rc_path)], check=True, cwd=ROOT)
    return res_path


def _build_launcher(zig: str, out: Path) -> None:
    res_path = _write_rc(out, APP_NAME, "Zapret-Zen — обход DPI для YouTube и Discord")
    cmd = [
        zig, "cc", "-target", "x86_64-windows-gnu", "-municode",
        "-Wl,--subsystem,windows", "-O2", "-static",
        "-o", str(out), str(LAUNCHER_C), str(res_path),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)
    out.with_suffix(".pdb").unlink(missing_ok=True)
    res_path.unlink(missing_ok=True)
    out.with_suffix(".rc").unlink(missing_ok=True)


def _write_build_options(path: Path, *, embed: bool) -> None:
    path.write_text(
        'pub const embed_payload = %s;\npub const app_version = "%s";\npub const ascii_ui = false;\n'
        % ("true" if embed else "false", VERSION)
    )


def _build_installer(zig: str, out: Path, payload: Path | None, workdir: Path) -> None:
    # A .res compiled from our own icon and version info (no manifest, see
    # _write_rc) is linked into the setup exe.
    res_path = _write_rc(out, f"{APP_NAME}-setup", "Установщик Zapret-Zen")
    options = workdir / "build_options.zig"
    _write_build_options(options, embed=payload is not None)
    cmd = [
        zig, "build-exe", "-target", "x86_64-windows-gnu", "-municode",
        "--subsystem", "windows", "-O", "ReleaseSmall", "-static",
        "-femit-bin=" + str(out),
        str(res_path),
        "--dep", "build_options",
        "--dep", "payload",
        f"-Mroot={INSTALLER_ZIG}",
        f"-Mbuild_options={options}",
        f"-Mpayload={workdir / 'payload_mod.zig'}",
    ]
    subprocess.run(cmd, check=True, cwd=workdir)
    res_path.unlink(missing_ok=True)
    out.with_suffix(".rc").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", default="", help="portable zip to embed into the setup exe")
    parser.add_argument("--out", default=str(ROOT / "dist_native"))
    parser.add_argument("--prepare", action="store_true", help="only build Zapret-Zen.exe")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    zig = _find_zig()

    launcher = out_dir / f"{APP_NAME}.exe"
    _build_launcher(zig, launcher)
    print(f"launcher  -> {launcher} ({launcher.stat().st_size} bytes)")
    if args.prepare:
        return 0

    payload = Path(args.payload) if args.payload else None
    if payload is not None and not payload.exists():
        raise SystemExit(f"payload not found: {payload}")

    with tempfile.TemporaryDirectory(prefix="zz-installer-") as tmp:
        workdir = Path(tmp)
        if payload is not None:
            shutil.copy2(payload, workdir / "payload.zip")
        else:
            # Without --payload the setup exe looks for the archive next to
            # itself; the module still needs a real (empty) zip to link against.
            with zipfile.ZipFile(workdir / "payload.zip", "w") as archive:
                archive.writestr("README.txt", "payload is read from disk\n")
        (workdir / "payload_mod.zig").write_text('pub const bytes = @embedFile("payload.zip");\n')
        setup = out_dir / f"{APP_NAME}-{VERSION}-setup.exe"
        _build_installer(zig, setup, payload, workdir)
        print(f"installer -> {setup} ({setup.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
