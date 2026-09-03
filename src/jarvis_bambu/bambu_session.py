from __future__ import annotations

import json
import os
import re
import subprocess
import time
import logging
import shutil
import ctypes
from dataclasses import dataclass
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WindowInfo:
    hwnd: int
    pid: int
    process_name: str
    title: str
    visible: bool


class BambuSession:
    def __init__(self, executable: Path, title_regex: str, backup_folder: Path, timeout: int = 30):
        self.executable = executable
        self.title_regex = title_regex
        self.backup_folder = backup_folder
        self.timeout = timeout
        self.window = None

    def _find_executable(self) -> Path:
        candidates = [self.executable]
        found = shutil.which("bambu-studio") or shutil.which("BambuStudio")
        if found:
            candidates.append(Path(found))
        if os.name == "nt":
            candidates.extend([
                Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "Bambu Studio" / "bambu-studio.exe",
                Path(os.environ.get("LOCALAPPDATA", ""))
                / "Programs" / "Bambu Studio" / "bambu-studio.exe",
            ])
            try:
                import winreg
                for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    for key_name in (
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\bambu-studio.exe",
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\BambuStudio.exe",
                    ):
                        try:
                            with winreg.OpenKey(root, key_name) as key:
                                candidates.append(Path(winreg.QueryValue(key, None)))
                        except OSError:
                            pass
            except ImportError:
                pass
        for candidate in candidates:
            if candidate and candidate.is_file():
                self.executable = candidate.resolve()
                return self.executable
        raise RuntimeError("No encuentro el ejecutable de Bambu Studio; configúralo en bambu_studio.executable")

    @staticmethod
    def _process_name(pid: int) -> str:
        try:
            import psutil
            return psutil.Process(pid).name()
        except Exception:
            pass
        if os.name == "nt":
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                try:
                    size = wintypes.DWORD(32768)
                    buffer = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(
                        handle, 0, buffer, ctypes.byref(size)
                    ):
                        return Path(buffer.value).name
                finally:
                    kernel32.CloseHandle(handle)
        return "<unavailable>"

    @staticmethod
    def _process_matches(name: str) -> bool:
        normalized = name.casefold().replace("_", "-")
        return normalized in {
            "bambu-studio.exe", "bambustudio.exe", "bambu-studio", "bambustudio"
        }

    @staticmethod
    def _title_matches(title: str) -> bool:
        folded = title.casefold()
        return "bambu studio" in folded or "bambustudio" in folded

    @staticmethod
    def _is_failure_dialog(title: str) -> bool:
        folded = title.casefold()
        return any(token in folded for token in (
            "initialization failed", "gui initialization", "fatal error",
        ))

    @classmethod
    def _is_bambu_window(cls, info: WindowInfo) -> bool:
        if (not info.visible or not cls._title_matches(info.title)
                or cls._is_failure_dialog(info.title)):
            return False
        # El título es la señal primaria. Si Windows permite leer el proceso,
        # se usa además para descartar navegadores que mencionen Bambu Studio.
        return info.process_name == "<unavailable>" or cls._process_matches(info.process_name)

    @classmethod
    def _enum_windows(cls) -> list[WindowInfo]:
        """Enumera directamente todas las ventanas top-level con título."""
        if os.name != "nt":
            return []
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [enum_callback, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        windows: list[WindowInfo] = []

        @enum_callback
        def callback(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if not title:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            info = WindowInfo(
                int(hwnd), int(pid.value), cls._process_name(int(pid.value)),
                title, bool(user32.IsWindowVisible(hwnd)),
            )
            windows.append(info)
            logger.debug(
                "[BAMBU] Top-level window HWND=%s PID=%s process=%s title=%r visible=%s",
                info.hwnd, info.pid, info.process_name, info.title, info.visible,
            )
            return True

        if not user32.EnumWindows(callback, 0):
            error = ctypes.get_last_error()
            if error:
                raise ctypes.WinError(error)
        return windows

    @classmethod
    def _find_bambu_window(cls) -> tuple[WindowInfo | None, list[WindowInfo]]:
        candidates = [
            info for info in cls._enum_windows()
            if cls._title_matches(info.title) or cls._process_matches(info.process_name)
        ]
        return next((info for info in candidates if cls._is_bambu_window(info)), None), candidates

    @staticmethod
    def _wrap_window(info: WindowInfo):
        from pywinauto import Desktop
        return Desktop(backend="uia").window(handle=info.hwnd)

    @staticmethod
    def _bambu_process_exists() -> bool:
        try:
            import psutil
            return any(
                process.info.get("name", "").lower()
                in {"bambu-studio.exe", "bambustudio.exe", "bambu-studio"}
                for process in psutil.process_iter(["name"])
            )
        except Exception:
            return False

    def _activate_window(self) -> None:
        """Restaura y activa Bambu por HWND, sin depender de clics en pantalla."""
        if self.window is None:
            raise RuntimeError("No hay una ventana de Bambu Studio conectada")
        import ctypes
        from ctypes import wintypes

        hwnd = int(self.window.handle)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL

        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if user32.GetForegroundWindow() == hwnd:
            logger.info("[BAMBU] Foreground verified HWND=%s", hwnd)
            return

        logger.info("[BAMBU] Direct focus failed; trying AttachThreadInput fallback...")
        foreground = user32.GetForegroundWindow()
        current_thread = kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        foreground_thread = (
            user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        )
        attached_target = False
        attached_foreground = False
        try:
            if target_thread and target_thread != current_thread:
                attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
            if foreground_thread and foreground_thread not in (current_thread, target_thread):
                attached_foreground = bool(
                    user32.AttachThreadInput(current_thread, foreground_thread, True)
                )
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            if attached_foreground:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
            if attached_target:
                user32.AttachThreadInput(current_thread, target_thread, False)

        # Respaldo de pywinauto para las restricciones de foco de algunas
        # versiones de Windows. Tampoco genera ningún clic.
        if user32.GetForegroundWindow() != hwnd:
            self.window.set_focus()
        if user32.GetForegroundWindow() != hwnd:
            raise RuntimeError("Windows no permitió activar la ventana de Bambu Studio")
        logger.info("[BAMBU] Foreground verified HWND=%s", hwnd)

    def connect(self, launch_if_missing: bool = True):
        if os.name != "nt":
            raise RuntimeError("El control de la ventana de Bambu Studio solo está disponible en Windows")
        logger.info("[BAMBU] Searching existing window with EnumWindows...")
        info, candidates = self._find_bambu_window()
        seen_candidates = {candidate.hwnd: candidate for candidate in candidates}
        if info is not None:
            self.window = self._wrap_window(info)
            logger.info(
                "[BAMBU] Window found HWND=%s PID=%s process=%s title=%r",
                info.hwnd, info.pid, info.process_name, info.title,
            )
            self._activate_window()
            return self.window
        if not launch_if_missing:
            self._log_candidates(seen_candidates.values())
            raise RuntimeError("No encuentro ninguna ventana abierta de Bambu Studio")

        launched = False
        if self._bambu_process_exists():
            logger.info("[BAMBU] Process found without main window; waiting...")
        else:
            logger.info("[BAMBU] Process not found. Launching...")
            executable = self._find_executable()
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            subprocess.Popen([str(executable)], creationflags=flags)
            launched = True
        poll_timeout = max(30.0, float(self.timeout))
        deadline = time.monotonic() + poll_timeout
        logger.info("[BAMBU] Waiting up to %.1f s for main window...", poll_timeout)
        while time.monotonic() < deadline:
            info, candidates = self._find_bambu_window()
            seen_candidates.update((candidate.hwnd, candidate) for candidate in candidates)
            if info is not None:
                self.window = self._wrap_window(info)
                logger.info(
                    "[BAMBU] Window ready HWND=%s PID=%s process=%s title=%r; restoring...",
                    info.hwnd, info.pid, info.process_name, info.title,
                )
                self._activate_window()
                return self.window
            time.sleep(.25)
        logger.error("[BAMBU] Main window did not appear after %.1f s", poll_timeout)
        self._log_candidates(seen_candidates.values())
        raise RuntimeError("No encuentro ninguna ventana abierta de Bambu Studio")

    @staticmethod
    def _log_candidates(candidates) -> None:
        candidates = list(candidates)
        if not candidates:
            logger.error("[BAMBU] No candidate windows were found during polling")
            return
        for info in candidates:
            logger.error(
                "[BAMBU] Candidate window: HWND=%s PID=%s process=%s title=%r visible=%s",
                info.hwnd, info.pid, info.process_name, info.title, info.visible,
            )

    def ensure_bambu_studio_active(self):
        if self.window is None:
            return self.connect(launch_if_missing=True)
        self._activate_window()
        return self.window

    def _wait_file_dialog(self, title_pattern: str):
        """Localiza el selector nativo aunque UI Automation no lo enumere."""
        from pywinauto import Desktop

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            for window in Desktop(backend="win32").windows(
                class_name="#32770", visible_only=True
            ):
                if re.match(title_pattern, window.window_text(), re.IGNORECASE):
                    return Desktop(backend="uia").window(handle=window.handle)
            time.sleep(.25)
        return None

    @staticmethod
    def _dismiss_later_popup(timeout: float = 20.0) -> bool:
        """Pulsa solamente Later/Más tarde en el aviso nativo Tips de Bambu."""
        from pywinauto import Desktop

        deadline = time.monotonic() + timeout
        pattern = re.compile(r"(?i)^\s*(later|m[aá]s tarde)\s*$")
        while time.monotonic() < deadline:
            # Bambu Studio crea este aviso como un diálogo Win32 #32770. En
            # algunas versiones UIA ve una ventana vacía y no expone botones.
            for dialog in Desktop(backend="win32").windows(
                class_name="#32770", visible_only=True
            ):
                try:
                    if not re.match(r"(?i)^\s*(tips|consejos?)\s*$", dialog.window_text() or ""):
                        continue
                    dialog.set_focus()
                    for button in dialog.children(class_name="Button"):
                        if pattern.match(button.window_text() or ""):
                            button.click_input()
                            return True

                    # Respaldo para Bambu 02.08, donde los botones se dibujan
                    # dentro del diálogo pero Win32 tampoco les asigna texto.
                    rect = dialog.rectangle()
                    dialog.click_input(coords=(rect.width() - 75, rect.height() - 36))
                    time.sleep(.5)
                    if not dialog.exists() or not dialog.is_visible():
                        return True
                except Exception:
                    continue

            # Compatibilidad con versiones que sí publican el botón por UIA.
            for window in Desktop(backend="uia").windows(visible_only=True):
                try:
                    for button in window.descendants(control_type="Button"):
                        if pattern.match(button.window_text() or ""):
                            button.click_input()
                            return True
                except Exception:
                    continue
            time.sleep(.5)
        return False

    def save_snapshot(self) -> Path:
        """Guarda siempre una copia, evitando depender del nombre actual de la ventana."""
        from pywinauto import Desktop, keyboard
        if self.window is None:
            self.connect()
        self.backup_folder.mkdir(parents=True, exist_ok=True)
        target = self.backup_folder / f"Proyecto_antes_de_optimizar_{datetime.now():%Y-%m-%d_%H-%M-%S}.3mf"
        self._activate_window()
        self.window.type_keys("^+s", set_foreground=True)
        dialog = self._wait_file_dialog(r".*(guardar.*como|save.*as).*")
        if dialog is None:
            raise RuntimeError("Bambu Studio no abrió la ventana Guardar como")
        dialog.set_focus()
        time.sleep(.5)
        import pyperclip

        filename = dialog.child_window(auto_id="1001", control_type="Edit")
        filename.click_input()
        keyboard.send_keys("^a")
        pyperclip.copy(str(target))
        keyboard.send_keys("^v")
        time.sleep(.5)
        keyboard.send_keys("{ENTER}")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if target.exists() and target.stat().st_size > 0:
                return target
            time.sleep(.5)
        raise RuntimeError(f"Bambu Studio no terminó de guardar {target}")

    def open_same_window(self, project: Path) -> None:
        from pywinauto import Desktop, keyboard
        if self.window is None:
            self.connect()
        self._activate_window()
        self.window.type_keys("^o", set_foreground=True)
        dialog = self._wait_file_dialog(r".*(abrir|open|choose.*one.*file.*3mf).*")
        if dialog is None:
            raise RuntimeError("Bambu Studio no abrió la ventana para seleccionar el proyecto")
        dialog.set_focus()
        time.sleep(.5)
        import pyperclip

        keyboard.send_keys("%n")
        time.sleep(.3)
        keyboard.send_keys("^a")
        pyperclip.copy(str(project))
        keyboard.send_keys("^v")
        time.sleep(.5)
        keyboard.send_keys("{ENTER}")
        self._dismiss_later_popup()

    def open_separate(self, project: Path) -> None:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        executable = self._find_executable()
        process = subprocess.Popen([str(executable), str(project)], creationflags=flags)
        logger.info("[BAMBU] Launched project PID=%s; waiting for main window...", process.pid)
        if os.name == "nt":
            deadline = time.monotonic() + max(30.0, float(self.timeout))
            while time.monotonic() < deadline:
                info, _candidates = self._find_bambu_window()
                if info is not None:
                    self.window = self._wrap_window(info)
                    self._activate_window()
                    break
                time.sleep(.25)
        self._dismiss_later_popup()


def write_optimizer_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_optimizer_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
