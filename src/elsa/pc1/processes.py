"""Procesos hijos propiedad del supervisor (ADR 0034 §6 y §7).

La propiedad es el **handle**: solo se detiene un :class:`OwnedProcess`, que
envuelve el ``Popen`` creado aquí. No hay ninguna función que detenga un
proceso por PID, por nombre de ejecutable o por puerto.

- Cada hijo nace en su **propio grupo de procesos**. El Ctrl+C del operador
  llega solo al supervisor, y el supervisor puede enviar ``CTRL_BREAK_EVENT``
  a un hijo concreto (en POSIX, solo para los tests, ``SIGINT``).
- Parada: primero la señal ordenada y una espera; solo si el plazo vence,
  ``kill`` sobre el handle propio.
- En Windows cada hijo se asigna a un **Job Object** con
  ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``: si el supervisor muere, el sistema
  operativo termina los hijos. No es una parada ordenada; solo impide
  huérfanos.
- La salida de cada hijo va a su archivo de log, nunca a la consola.
"""

from __future__ import annotations

import signal
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

__all__ = [
    "KILL_WAIT_SECONDS",
    "ChildSpec",
    "OwnedProcess",
    "ProcessJob",
    "StopOutcome",
    "create_job_object",
    "launch",
]

KILL_WAIT_SECONDS = 5.0


class StopOutcome(StrEnum):
    ALREADY_EXITED = "already_exited"
    GRACEFUL = "graceful"
    FORCED = "forced"


class ProcessJob(Protocol):
    def assign(self, pid: int) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ChildSpec:
    """Qué lanzar. ``env`` es el entorno **completo** del hijo, ya filtrado."""

    name: str
    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd: Path
    log_path: Path


class OwnedProcess:
    """Un hijo creado por este supervisor. Solo se actúa sobre su handle."""

    def __init__(self, name: str, popen: subprocess.Popen[bytes]) -> None:
        self.name = name
        self._popen = popen

    @property
    def pid(self) -> int:
        return self._popen.pid

    @property
    def argv(self) -> tuple[str, ...]:
        args = self._popen.args
        return tuple(str(a) for a in args) if isinstance(args, list | tuple) else (str(args),)

    def returncode(self) -> int | None:
        """``None`` mientras sigue vivo."""
        return self._popen.poll()

    def wait(self, timeout: float) -> bool:
        try:
            self._popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True

    def request_stop(self) -> bool:
        """Envía la señal de parada ordenada a su grupo. ``False`` si no pudo enviarse."""
        if self.returncode() is not None:
            return True
        try:
            self._popen.send_signal(_GRACEFUL_SIGNAL)
        except OSError:
            return False
        return True

    def kill(self) -> None:
        """Cierre forzado sobre el handle propio. Nunca sobre otro proceso."""
        if self.returncode() is None:
            self._popen.kill()
        self.wait(KILL_WAIT_SECONDS)

    def stop(self, graceful_timeout: float) -> StopOutcome:
        if self.returncode() is not None:
            return StopOutcome.ALREADY_EXITED
        if self.request_stop() and self.wait(graceful_timeout):
            return StopOutcome.GRACEFUL
        self.kill()
        return StopOutcome.FORCED


def launch(spec: ChildSpec, job: ProcessJob | None) -> OwnedProcess:
    """Lanza el hijo en su propio grupo, con su log, y lo asigna al job.

    Si la asignación al job falla, el hijo se termina (es propio) y se relanza
    el error: sin job, podría quedar huérfano.
    """
    with open(spec.log_path, "wb") as log:
        popen = _popen(spec, log.fileno())
    child = OwnedProcess(spec.name, popen)
    if job is not None:
        try:
            job.assign(popen.pid)
        except OSError:
            child.kill()
            raise
    return child


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _GRACEFUL_SIGNAL = signal.CTRL_BREAK_EVENT

    def _popen(spec: ChildSpec, log_fd: int) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            list(spec.argv),
            env=dict(spec.env),
            cwd=spec.cwd,
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    def _last_error() -> OSError:
        return ctypes.WinError(ctypes.get_last_error())

    class _WindowsJob:
        """Job Object anónimo que termina sus procesos al cerrarse su último handle."""

        def __init__(self) -> None:
            handle = _kernel32.CreateJobObjectW(None, None)
            if not handle:
                raise _last_error()
            info = _ExtendedLimitInformation()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not _kernel32.SetInformationJobObject(
                handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                error = _last_error()
                _kernel32.CloseHandle(handle)
                raise error
            self._handle: int | None = handle

        def assign(self, pid: int) -> None:
            if self._handle is None:
                raise OSError("the job object is closed")
            # El hijo está vivo y su Popen conserva un handle: su PID no puede
            # haberse reutilizado.
            process = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            if not process:
                raise _last_error()
            try:
                if not _kernel32.AssignProcessToJobObject(self._handle, process):
                    raise _last_error()
            finally:
                _kernel32.CloseHandle(process)

        def close(self) -> None:
            handle, self._handle = self._handle, None
            if handle is not None:
                _kernel32.CloseHandle(handle)

    def create_job_object() -> ProcessJob | None:
        return _WindowsJob()

else:
    _GRACEFUL_SIGNAL = signal.SIGINT

    def _popen(spec: ChildSpec, log_fd: int) -> subprocess.Popen[bytes]:
        # POSIX solo se usa en los tests: sesión propia para aislar el Ctrl+C.
        return subprocess.Popen(
            list(spec.argv),
            env=dict(spec.env),
            cwd=spec.cwd,
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def create_job_object() -> ProcessJob | None:
        """Sin equivalente en POSIX; el piloto solo se opera en Windows."""
        return None
