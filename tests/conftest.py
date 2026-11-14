"""Test environment shims.

The suite runs on Linux CI/sandboxes where the PySide6 wheels cannot even be
imported (``libGL.so.1`` is missing).  The modules under test do not need a
working Qt: they only need the module objects to exist, so PySide6 is replaced
by a minimal stub that provides ``QObject``, signals and timers.
"""
from __future__ import annotations

import sys
import types
from typing import Any, Callable

import pytest


def _make_signal() -> Any:
    class _Signal:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self._callbacks: list[Callable[..., Any]] = []

        def __get__(self, instance: Any, owner: Any = None) -> Any:
            # Signals are class attributes used as ``self.signal.connect``.
            if instance is None:
                return self
            bound = instance.__dict__.setdefault(f"__signal_{id(self)}", _BoundSignal())
            return bound

        def connect(self, callback: Callable[..., Any]) -> None:
            self._callbacks.append(callback)

        def emit(self, *args: Any, **kwargs: Any) -> None:
            for callback in list(self._callbacks):
                callback(*args, **kwargs)

    return _Signal()


class _BoundSignal:
    def __init__(self) -> None:
        self._callbacks: list[Callable[..., Any]] = []

    def connect(self, callback: Callable[..., Any]) -> None:
        self._callbacks.append(callback)

    def emit(self, *args: Any, **kwargs: Any) -> None:
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


class _QObject:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def deleteLater(self) -> None:  # noqa: N802 - Qt naming
        pass


class _QTimer:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._timeout = _BoundSignal()
        self._interval = 0
        self._active = False

    @property
    def timeout(self) -> _BoundSignal:
        return self._timeout

    def setInterval(self, interval: int) -> None:  # noqa: N802
        self._interval = interval

    def interval(self) -> int:
        return self._interval

    def setSingleShot(self, value: bool) -> None:  # noqa: N802
        self._single_shot = value

    def start(self, *_args: Any) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def isActive(self) -> bool:  # noqa: N802
        return self._active

    @staticmethod
    def singleShot(_ms: int, callback: Callable[[], None]) -> None:  # noqa: N802
        callback()


class _QColor:
    """Just enough of QColor for theme file generation."""

    def __init__(self, value: Any = "#000000") -> None:
        self.value = value

    def isValid(self) -> bool:  # noqa: N802
        return bool(self.value)

    def name(self) -> str:
        return str(self.value)

    def lighter(self, _amount: int = 100) -> "_QColor":
        return _QColor(self.value)

    def darker(self, _amount: int = 100) -> "_QColor":
        return _QColor(self.value)

    @staticmethod
    def fromRgb(*args: Any) -> "_QColor":
        return _QColor("#000000")


def _install_pyside_stub() -> None:
    try:  # pragma: no cover - only on machines with a working Qt
        import PySide6.QtCore  # noqa: F401
        import PySide6.QtGui  # noqa: F401

        return
    except Exception:
        # A failed import may leave half-initialised modules behind.
        for name in [key for key in sys.modules if key == "PySide6" or key.startswith("PySide6.")]:
            sys.modules.pop(name, None)
    pyside = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QObject = _QObject  # type: ignore[attr-defined]
    qtcore.QTimer = _QTimer  # type: ignore[attr-defined]
    qtcore.Signal = _make_signal  # type: ignore[attr-defined]
    qtcore.Qt = types.SimpleNamespace()  # type: ignore[attr-defined]
    qtgui = types.ModuleType("PySide6.QtGui")
    qtgui.QColor = _QColor  # type: ignore[attr-defined]
    pyside.QtCore = qtcore  # type: ignore[attr-defined]
    pyside.QtGui = qtgui  # type: ignore[attr-defined]
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui


_install_pyside_stub()


@pytest.fixture()
def anyio_backend() -> str:  # pragma: no cover - placeholder fixture
    return "asyncio"
