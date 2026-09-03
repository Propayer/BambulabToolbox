from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from .metrics_parser import parse_time_minutes, parse_weight_grams
from .models import ConfigurationError, PieceMetrics, PieceProcessingError


class BambuStudioController:
    """Controlador visual con UI Automation y recuperación por coordenadas relativas."""

    def __init__(self, config: dict, defaults: dict, work_folder: Path):
        self.config = config
        self.defaults = defaults
        self.work_folder = work_folder
        self.work_folder.mkdir(parents=True, exist_ok=True)
        self.executable = self._find_executable()
        self.app = None
        self.window = None
        self.sync_status = "No requerido"
        self.last_unknown_screenshot = None

    def _find_executable(self) -> Path:
        configured = str(self.config.get("executable", "")).strip()
        candidates = []
        if configured:
            candidates.append(Path(configured))
        candidates.extend(
            [
                Path(r"C:\Program Files\Bambu Studio\bambu-studio.exe"),
                Path(r"C:\Program Files\Bambu Studio\BambuStudio.exe"),
                Path(r"C:\Program Files (x86)\Bambu Studio\bambu-studio.exe"),
            ]
        )
        for path in candidates:
            if path.exists():
                return path
        raise ConfigurationError(
            "No se encuentra Bambu Studio. Indica su ruta en bambu_studio.executable."
        )

    def diagnose(self) -> Path:
        self._connect_window()
        output = self.work_folder / "diagnostico_controles.txt"
        screenshot = self.work_folder / "diagnostico_bambu.png"
        try:
            self.window.capture_as_image().save(screenshot)
            lines = []
            for control in self.window.descendants():
                try:
                    lines.append(
                        f"{control.element_info.control_type}\t{control.window_text()}\t{control.rectangle()}"
                    )
                except Exception:
                    continue
            output.write_text("\n".join(lines), encoding="utf-8")
        except Exception as exc:
            raise PieceProcessingError(f"No se pudo generar el diagnóstico: {exc}") from exc
        return output

    def process(self, source_path: Path) -> PieceMetrics:
        try:
            self._launch_piece(source_path)
            self._handle_known_popups()
            self._arrange()
            self._handle_known_popups()
            self._slice()
            self._handle_known_popups()
            text = self._collect_visible_text()
            minutes = parse_time_minutes(text)
            grams = parse_weight_grams(text)
            preview = self._capture_preview(source_path)
            if minutes is None or grams is None:
                raise PieceProcessingError(
                    "No pude leer el tiempo o el peso. Ejecuta --diagnose para calibrar esta versión."
                )
            return PieceMetrics(
                source_path=source_path,
                print_minutes=minutes,
                weight_grams=grams,
                preview_path=preview,
                machine=str(self.defaults["machine"]),
                material=str(self.defaults["material"]),
                profile=str(self.defaults["profile"]),
                sync_status=self.sync_status,
            )
        except PieceProcessingError:
            raise
        except Exception as exc:
            raise PieceProcessingError(str(exc)) from exc
        finally:
            if self.config.get("close_between_pieces", True):
                self._close_project()

    def _launch_piece(self, source_path: Path) -> None:
        try:
            from pywinauto import Application, Desktop
        except ImportError as exc:
            raise ConfigurationError("Falta pywinauto. Ejecuta instalar.ps1.") from exc

        subprocess.Popen([str(self.executable), str(source_path)])
        deadline = time.time() + int(self.config.get("startup_timeout_seconds", 90))
        title_regex = str(self.config.get("window_title_regex", ".*Bambu Studio.*"))
        while time.time() < deadline:
            try:
                window = Desktop(backend="uia").window(title_re=title_regex)
                if window.exists(timeout=1):
                    window.wait("visible enabled", timeout=10)
                    self.window = window
                    self.app = Application(backend="uia").connect(handle=window.handle)
                    time.sleep(3)
                    return
            except Exception:
                time.sleep(1)
        raise PieceProcessingError("Bambu Studio no apareció dentro del tiempo esperado.")

    def _connect_window(self) -> None:
        from pywinauto import Desktop

        title_regex = str(self.config.get("window_title_regex", ".*Bambu Studio.*"))
        self.window = Desktop(backend="uia").window(title_re=title_regex)
        self.window.wait("visible enabled", timeout=15)

    def _all_windows(self):
        from pywinauto import Desktop

        return Desktop(backend="uia").windows()

    def _click_matching_button(self, patterns: list[str]) -> bool:
        for window in self._all_windows():
            for pattern in patterns:
                try:
                    button = window.child_window(title_re=pattern, control_type="Button")
                    if button.exists(timeout=0.2) and button.is_visible():
                        button.click_input()
                        return True
                except Exception:
                    continue
        return False

    def _matching_button_exists(self, patterns: list[str]) -> bool:
        for window in self._all_windows():
            for pattern in patterns:
                try:
                    button = window.child_window(title_re=pattern, control_type="Button")
                    if button.exists(timeout=0.2) and button.is_visible():
                        return True
                except Exception:
                    continue
        return False

    def _handle_known_popups(self) -> None:
        sync = list(self.config.get("sync_button_patterns", []))
        later = list(self.config.get("later_button_patterns", []))
        policy = str(self.config.get("sync_policy", "sync_then_later"))
        if self._click_matching_button(sync):
            self.sync_status = "Sincronizado"
            deadline = time.time() + int(self.config.get("popup_timeout_seconds", 60))
            while time.time() < deadline:
                time.sleep(1)
                if self._matching_button_exists(later):
                    break
                if not self._matching_button_exists(sync):
                    return
            if policy == "sync_then_later" and self._click_matching_button(later):
                self.sync_status = "Continuado sin sincronizar"
                return
            raise PieceProcessingError("La sincronización de la P2S no terminó.")
        if self._click_matching_button(later):
            self.sync_status = "Continuado sin sincronizar"
            return
        self._assert_no_unknown_dialogs()

    def _assert_no_unknown_dialogs(self) -> None:
        if not self.window:
            return
        try:
            main_pid = self.window.element_info.process_id
            main_handle = self.window.handle
            for candidate in self._all_windows():
                try:
                    if candidate.handle == main_handle or not candidate.is_visible():
                        continue
                    if candidate.element_info.process_id != main_pid:
                        continue
                    if candidate.element_info.control_type not in ("Window", "Pane"):
                        continue
                    text = candidate.window_text().strip() or "ventana sin título"
                    screenshot = self.work_folder / "popup_desconocido.png"
                    candidate.capture_as_image().save(screenshot)
                    self.last_unknown_screenshot = screenshot
                    raise PieceProcessingError(
                        f"Bambu Studio mostró un cuadro no reconocido: {text}"
                    )
                except PieceProcessingError:
                    raise
                except Exception:
                    continue
        except PieceProcessingError:
            raise
        except Exception:
            return

    def _arrange(self) -> None:
        if self._click_main_button([r"(?i).*organizar.*", r"(?i).*arrange.*"]):
            time.sleep(2)
            return
        click = self.config.get("arrange_click")
        if click:
            self._relative_click(click)
            time.sleep(2)
            return
        hotkey = str(self.config.get("arrange_hotkey", "a"))
        self.window.set_focus()
        self.window.type_keys(hotkey, set_foreground=True)
        time.sleep(2)

    def _slice(self) -> None:
        if not self._click_main_button(
            [r"(?i).*laminar.*placa.*", r"(?i).*slice.*plate.*", r"(?i)^laminar$", r"(?i)^slice$"]
        ):
            click = self.config.get("slice_click")
            if click:
                self._relative_click(click)
            else:
                raise PieceProcessingError(
                    "No encuentro el botón Laminar. Ejecuta --diagnose para calibrarlo."
                )
        deadline = time.time() + int(self.config.get("slicing_timeout_seconds", 900))
        while time.time() < deadline:
            time.sleep(2)
            self._handle_known_popups()
            text = self._collect_visible_text()
            if parse_time_minutes(text) is not None and parse_weight_grams(text) is not None:
                return
        raise PieceProcessingError("El laminado no terminó dentro del tiempo máximo.")

    def _click_main_button(self, patterns: list[str]) -> bool:
        if not self.window:
            return False
        for pattern in patterns:
            try:
                control = self.window.child_window(title_re=pattern, control_type="Button")
                if control.exists(timeout=0.4) and control.is_visible():
                    control.click_input()
                    return True
            except Exception:
                continue
        return False

    def _relative_click(self, point) -> None:
        import pyautogui

        rectangle = self.window.rectangle()
        x = rectangle.left + int(rectangle.width() * float(point["x"]))
        y = rectangle.top + int(rectangle.height() * float(point["y"]))
        pyautogui.click(x, y)

    def _collect_visible_text(self) -> str:
        texts = []
        if not self.window:
            return ""
        try:
            texts.append(self.window.window_text())
            for control in self.window.descendants():
                try:
                    text = control.window_text().strip()
                    if text:
                        texts.append(text)
                except Exception:
                    continue
        except Exception:
            pass
        return "\n".join(texts)

    def _capture_preview(self, source_path: Path) -> Path:
        output = self.work_folder / f"{source_path.stem}_preview.png"
        image = self.window.capture_as_image()
        crop = self.config.get("preview_crop")
        if crop:
            width, height = image.size
            image = image.crop(
                (
                    int(width * float(crop["left"])),
                    int(height * float(crop["top"])),
                    int(width * float(crop["right"])),
                    int(height * float(crop["bottom"])),
                )
            )
        image.save(output)
        return output

    def capture_error(self, source_path: Path) -> Path | None:
        if self.last_unknown_screenshot and self.last_unknown_screenshot.exists():
            return self.last_unknown_screenshot
        if not self.window:
            return None
        output = self.work_folder / f"{source_path.stem}_error.png"
        try:
            self.window.capture_as_image().save(output)
            return output
        except Exception:
            return None

    def _close_project(self) -> None:
        if not self.window:
            return
        try:
            self.window.close()
            time.sleep(1)
            self._click_matching_button(list(self.config.get("discard_button_patterns", [])))
            time.sleep(1)
        except Exception:
            pass
        finally:
            self.window = None
            self.app = None
