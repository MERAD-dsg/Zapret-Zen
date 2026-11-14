"""Build a portable, source-based Zapret-Zen distribution for Windows x64.

The official release pipeline needs Windows + MSVC (Nuitka). This script builds a
"portable" folder that runs from source with the *official* Windows embeddable
CPython plus the pinned win_amd64 wheels, so it can be produced on any machine:

    python.cmd (pythonw.exe)  ->  src/ (zapret_zen)  ->  site-packages/ (wheels)
                                    runtime/ (zapret bundle, tg-ws-proxy)
                                    ui_assets/ themes/ sample_data/

Inputs are the artefacts already cached by the session:
  .release_cache/python-3.11.9-embed-amd64.zip (or the extracted directory
  .release_cache/python-3.11.9-embed-amd64 with size-verified files)
  .release_cache/wheels/*.whl

Both can be recreated with:  python scripts/setup_portable_cache.py

Usage:
    python scripts/build_portable.py [--out dist_portable] [--zip ../Zapret-Zen-portable.zip]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".release_cache"
EMBED_ZIP = CACHE / "python-3.11.9-embed-amd64.zip"
EMBED_DIR = CACHE / "python-3.11.9-embed-amd64"
WHEELS = CACHE / "wheels"

# Heavy Qt pieces the application never links against; dropping them keeps the
# archive download-friendly. Everything the UI needs (QtCore/QtGui/QtWidgets/
# QtNetwork/QtSvg + the platform plugin) is kept explicitly below.
QT_KEEP_FILES = {
    "PySide6/__init__.py",
    "PySide6/_config.py",
    "PySide6/_git_pyside_version.py",
    "PySide6/py.typed",
    "PySide6/QtCore.pyd",
    "PySide6/QtGui.pyd",
    "PySide6/QtWidgets.pyd",
    "PySide6/QtNetwork.pyd",
    "PySide6/QtSvg.pyd",
    "PySide6/Qt6Core.dll",
    "PySide6/Qt6Gui.dll",
    "PySide6/Qt6Widgets.dll",
    "PySide6/Qt6Network.dll",
    "PySide6/Qt6Svg.dll",
    "PySide6/pyside6.abi3.dll",
    "PySide6/msvcp140.dll",
    "PySide6/msvcp140_1.dll",
    "PySide6/msvcp140_2.dll",
    "PySide6/msvcp140_codecvt_ids.dll",
    "PySide6/vcruntime140.dll",
    "PySide6/vcruntime140_1.dll",
    "PySide6/concrt140.dll",
}
QT_KEEP_DIRS = (
    "PySide6/plugins/platforms/qwindows",
    "PySide6/plugins/platforms/qminimal",
    "PySide6/plugins/styles/",
    "PySide6/plugins/imageformats/qgif",
    "PySide6/plugins/imageformats/qico",
    "PySide6/plugins/imageformats/qjpeg",
    "PySide6/plugins/imageformats/qsvg",
    "PySide6/plugins/imageformats/qwebp",
    "PySide6/plugins/iconengines/",
    "PySide6/plugins/networkinformation/",
    "PySide6/plugins/tls/",
)

SHIBOKEN_KEEP_FILES = {
    "shiboken6/__init__.py",
    "shiboken6/_config.py",
    "shiboken6/Shiboken.pyd",
    "shiboken6/shiboken6.abi3.dll",
    "shiboken6/msvcp140.dll",
    "shiboken6/msvcp140_1.dll",
    "shiboken6/msvcp140_2.dll",
    "shiboken6/msvcp140_codecvt_ids.dll",
    "shiboken6/vcruntime140.dll",
    "shiboken6/vcruntime140_1.dll",
    "shiboken6/concrt140.dll",
    "shiboken6/vcamp140.dll",
    "shiboken6/vccorlib140.dll",
    "shiboken6/vcomp140.dll",
}

# Trimmed packages: docs/tests/changelogs are not needed at runtime.
TRIM_DIR_PARTS = ("/tests/", "/test/", "/include/", "/lib/cmake/", ".dist-info/")


PORTABLE_README = """Zapret-Zen 2.1e - portable build (Windows x64)
================================================

Как запустить
1. Распакуйте архив целиком в любую папку, куда есть права записи (не в Program Files).
   Не запускайте прямо из ZIP-архива.
2. Запустите run_zapret_zen.cmd.
3. Приложение само запросит права администратора (нужны драйверу WinDivert).
4. Выберите сервисы (YouTube / YT Music уже отмечен) и нажмите
   «Подобрать настройки» или «Запустить».

Если что-то не стартует
* run_zapret_zen_console.cmd — тот же запуск, но с консолью: видно версии
  Python и PySide6 и текст ошибки.
* Логи: папка logs рядом с приложением.
* Антивирус может ругаться на winws.exe / WinDivert — это компоненты zapret,
  добавьте папку в исключения.

Что внутри
* python.exe / python311.zip — официальный Windows embeddable Python 3.11.9.
* site-packages — зафиксированные колёса: PySide6 6.12, cryptography 50, httpx/h2,
  pydivert, pypresence (лишние части Qt вырезаны для размера).
* src\\zapret_zen — исходники приложения (версия 2.1e).
* runtime\\zapret-discord-youtube — стратегии general*.bat и winws.exe.
* runtime\\tg-ws-proxy — TG WS Proxy (запускается из исходников).
* portable.flag — включает портативный режим (настройки и логи рядом).

Только Windows x64. Сборка проверена статически; интерфейс и обход
блокировок требуют запуска на вашей машине с вашим провайдером.
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Files of the official python-3.11.9-embed-amd64 distribution (with sizes), used
# to verify a re-assembled copy when the original zip is not available.
EMBED_FILES = {
    "LICENSE.txt": 36235, "_asyncio.pyd": 65304, "_bz2.pyd": 84760, "_ctypes.pyd": 124696,
    "_decimal.pyd": 255768, "_elementtree.pyd": 128792, "_hashlib.pyd": 65304,
    "_lzma.pyd": 159512, "_msi.pyd": 44824, "_multiprocessing.pyd": 34584,
    "_overlapped.pyd": 51480, "_queue.pyd": 32024, "_socket.pyd": 79640,
    "_sqlite3.pyd": 120600, "_ssl.pyd": 178456, "_uuid.pyd": 25368, "_zoneinfo.pyd": 45848,
    "libcrypto-3.dll": 5191960, "libffi-8.dll": 39696, "libssl-3.dll": 787224,
    "pyexpat.pyd": 199448, "python.cat": 643161, "python.exe": 103192, "python3.dll": 67352,
    "python311.dll": 5800216, "python311.zip": 4285636, "pythonw.exe": 101656,
    "select.pyd": 30488, "sqlite3.dll": 1540888, "unicodedata.pyd": 1140504,
    "vcruntime140.dll": 119192, "vcruntime140_1.dll": 49528, "winsound.pyd": 31512,
}


def _extract_embed(target: Path) -> str:
    """Materialise the embeddable CPython runtime and say where it came from."""
    if EMBED_ZIP.exists():
        with zipfile.ZipFile(EMBED_ZIP) as archive:
            archive.extractall(target)
        return str(EMBED_ZIP)
    if not EMBED_DIR.exists():
        raise SystemExit(f"missing embeddable python: {EMBED_ZIP} or {EMBED_DIR}")
    missing = []
    for name, expected_size in EMBED_FILES.items():
        source = EMBED_DIR / name
        if not source.exists():
            missing.append(f"{name} (missing)")
            continue
        actual = source.stat().st_size
        if actual != expected_size:
            missing.append(f"{name} ({actual} != {expected_size})")
            continue
        shutil.copy2(source, target / name)
    if missing:
        raise SystemExit("embeddable python is incomplete: " + ", ".join(missing[:6]))
    return str(EMBED_DIR)


def _skip_wheel_member(name: str) -> bool:
    if name.endswith("/"):
        return False
    if "/" not in name:
        # Top-level *extensions* (e.g. _cffi_backend.cp311-win_amd64.pyd) must be
        # kept: they are imported by cryptography/httpx. Only stray top-level
        # data files are dropped.
        return not name.endswith((".pyd", ".pth", ".dll"))
    if any(part in name for part in TRIM_DIR_PARTS):
        return True
    if name.startswith("PySide6/"):
        if name in QT_KEEP_FILES:
            return False
        return not any(name.startswith(keep) for keep in QT_KEEP_DIRS)
    if name.startswith("shiboken6/"):
        return name not in SHIBOKEN_KEEP_FILES
    if name.startswith("pydivert/tests/"):
        return True
    # .pyi stubs are typing metadata only; the app never reads them at runtime.
    if name.endswith(".pyi"):
        return True
    return False


def _extract_wheels(target: Path) -> list[str]:
    target.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for wheel in sorted(WHEELS.glob("*.whl")):
        installed.append(wheel.name)
        with zipfile.ZipFile(wheel) as archive:
            for info in archive.infolist():
                if _skip_wheel_member(info.filename):
                    continue
                destination = target / info.filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
    return installed


def _copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log", "*.zip", "*.7z", "docs"),
        dirs_exist_ok=True,
    )


def _write_launchers(root: Path) -> None:
    # pythonw.exe, not python.exe: the old launcher spawned a console window that
    # stayed open for the whole session next to the main window.
    run_cmd = """@echo off
setlocal
cd /d "%~dp0"
rem Zapret-Zen portable launcher. The app requests elevation itself.
"%~dp0pythonw.exe" -m zapret_zen.main %*
exit /b %errorlevel%
"""
    (root / "run_zapret_zen.cmd").write_text(run_cmd.replace("\n", "\r\n"), encoding="ascii")
    debug = """@echo off
setlocal
cd /d "%~dp0"
echo ==== Zapret-Zen portable (console) ====
"%~dp0python.exe" -c "import sys; print(sys.version)"
"%~dp0python.exe" -c "import PySide6, zapret_zen; print('PySide6', PySide6.__version__, 'Zapret-Zen', zapret_zen.__version__)"
"%~dp0python.exe" -m zapret_zen.main
echo ==== exit code: %errorlevel% ====
pause
"""
    (root / "run_zapret_zen_console.cmd").write_text(debug.replace("\n", "\r\n"), encoding="ascii")
    (root / "portable.flag").write_text("portable\n", encoding="ascii")


def _install_native_launcher(root: Path) -> str:
    """Place Zapret-Zen.exe (native GUI launcher) next to pythonw.exe.

    The launcher is committed as a build artefact of `scripts/build_installer.py`;
    a plain archive build without it still works through run_zapret_zen.cmd, so a
    missing binary is a warning, not an error.
    """
    source = ROOT / "native" / "launcher" / "Zapret-Zen.exe"
    if not source.exists():
        return "missing"
    shutil.copy2(source, root / "Zapret-Zen.exe")
    return "copied"


def _write_pth(root: Path) -> None:
    (root / "python311._pth").write_text(
        "python311.zip\r\n.\r\nsrc\r\nsite-packages\r\nimport site\r\n", encoding="ascii"
    )


def build(out: Path, zip_path: Path | None, zip_prefix: str = "") -> dict[str, object]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    embed_source = _extract_embed(out)
    _write_pth(out)
    _copy_tree(ROOT / "src", out / "src")
    for name in ("runtime", "ui_assets", "themes", "sample_data"):
        _copy_tree(ROOT / name, out / name)
    installed = _extract_wheels(out / "site-packages")
    _write_launchers(out)
    _install_native_launcher(out)
    (out / "VERSION.txt").write_text(
        f"Zapret-Zen portable (source build)\nbuilt from {ROOT.name}\n", encoding="utf-8"
    )
    (out / "ПРОЧТИ_МЕНЯ.txt").write_text(PORTABLE_README, encoding="utf-8-sig")
    manifest: dict[str, object] = {
        "wheels": installed,
        "python_embed_source": embed_source,
        "python_embed_sha256": _sha256(Path(embed_source)) if Path(embed_source).is_file() else "",
    }
    (out / "BUILD_INFO.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if zip_path is not None:
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(out.rglob("*")):
                if path.is_dir():
                    continue
                archive.write(path, Path(zip_prefix or out.name) / path.relative_to(out))
        manifest["zip"] = str(zip_path)
        manifest["zip_bytes"] = zip_path.stat().st_size
        manifest["zip_sha256"] = _sha256(zip_path)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "dist_portable"))
    parser.add_argument("--zip", default="")
    parser.add_argument("--no-zip", action="store_true")
    parser.add_argument("--zip-prefix", default="", help="top-level folder name inside the archive")
    args = parser.parse_args(argv)
    zip_path = None if args.no_zip else Path(args.zip) if args.zip else None
    manifest = build(Path(args.out), zip_path, args.zip_prefix)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
