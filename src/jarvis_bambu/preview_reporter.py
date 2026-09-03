from __future__ import annotations

import json
import subprocess
import sys
import time
import logging
import queue
import threading
import uuid
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


class PreviewReporter:
    def __init__(
        self,
        image_path: Path,
        state_path: Path,
        bed,
        show_window: bool = True,
        on_update: Callable[[Path, dict], None] | None = None,
        update_interval_ms: int = 50,
    ):
        self.image_path = image_path
        self.state_path = state_path
        self.bed = bed
        self.image_path.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.process = None
        self.show_window = show_window
        self.on_update = on_update
        self.update_interval = max(0, update_interval_ms) / 1000.0
        self._last_queued = 0.0
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._latest_request = None
        self._finished = False
        self._worker = threading.Thread(target=self._work, daemon=True, name="jarvis-preview")
        self._worker.start()
        self._heartbeat = threading.Thread(
            target=self._heartbeat_work, daemon=True, name="jarvis-preview-clock"
        )
        self._heartbeat.start()

    def _heartbeat_work(self) -> None:
        """Refresh elapsed time even when the optimizer emits no improvements."""
        while not self._finished:
            time.sleep(.5)
            request = self._latest_request
            if request is not None and not self._queue.full() and not self._finished:
                self._queue.put(request)

    def _work(self) -> None:
        while True:
            request = self._queue.get()
            if request is None:
                self._queue.task_done()
                return
            try:
                self._render(*request)
            except Exception:
                logger.exception("No se pudo actualizar la preview")
            finally:
                self._queue.task_done()

    def start(self) -> None:
        if not self.show_window or self.process is not None:
            return
        self.process = subprocess.Popen(
            [sys.executable, "-m", "jarvis_bambu.optimizer_preview",
             "--image", str(self.image_path), "--state", str(self.state_path)],
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )

    def update(
        self,
        solution,
        generation: int,
        score,
        finished: bool = False,
        attempt: int | None = None,
        debug: bool = False,
        progress: dict | None = None,
        status: str | None = None,
    ) -> None:
        logger.debug(
            "Preview iteration=%d attempt=%s score=%s plates=%d objects=%d improved=%s",
            generation, attempt, score, len(solution), sum(map(len, solution)), not debug,
        )
        now = time.monotonic()
        if not finished and now - self._last_queued < self.update_interval:
            return
        self._last_queued = now
        snapshot = [list(plate) for plate in solution]
        request = (snapshot, generation, score, finished, attempt, debug, progress, status)
        self._latest_request = request
        self._finished = finished
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                pass
        self._queue.put(request)
        if finished:
            self._queue.join()

    def _render(
        self, solution, generation: int, score, finished: bool = False,
        attempt: int | None = None, debug: bool = False,
        progress: dict | None = None, status: str | None = None,
    ) -> None:
        width, height = 1100, 680
        image = Image.new("RGB", (width, height), "#111820")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=18)
        title_font = ImageFont.load_default(size=26)
        elapsed = time.monotonic() - self.started
        draw.text((24, 18), "JARVIS · OPTIMIZACIÓN GENERACIONAL", fill="#ffffff", font=title_font)
        detail = f"Generación {generation}"
        if attempt is not None:
            detail += f"   ·   Intento {attempt}"
        state_text = status or ("Solución probada" if debug else "Mejor solución")
        progress_text = ""
        if progress:
            progress_text = (
                f"   ·   Colocadas {progress.get('placed', 0)}/{progress.get('total', 0)}"
                f"   ·   Plate {progress.get('plate', 1)}"
            )
        draw.text(
            (24, 58),
            f"{detail}   ·   {state_text}: {len(solution)} placas{progress_text}"
            f"   ·   {elapsed:.0f} s",
            fill="#7ee7a8", font=font,
        )

        display_solution = solution[:12]
        count = max(1, len(display_solution))
        columns = min(3, count)
        rows = (count + columns - 1) // columns
        panel_w = (width - 48 - (columns - 1) * 18) / columns
        panel_h = (height - 110 - (rows - 1) * 18) / rows
        minx, miny, maxx, maxy = self.bed.bounds
        bed_w, bed_h = maxx - minx, maxy - miny
        for index, placements in enumerate(display_solution):
            col, row = index % columns, index // columns
            left = 24 + col * (panel_w + 18)
            top = 96 + row * (panel_h + 18)
            scale = min((panel_w - 24) / bed_w, (panel_h - 42) / bed_h)
            ox = left + (panel_w - bed_w * scale) / 2
            oy = top + 28 + (panel_h - 32 - bed_h * scale) / 2
            draw.rounded_rectangle((left, top, left + panel_w, top + panel_h), 8,
                                   fill="#1b2632", outline="#566776", width=2)
            draw.text((left + 10, top + 7), f"Placa {index + 1} · {len(placements)} piezas",
                      fill="#dbe8f1", font=font)
            draw.rectangle((ox, oy, ox + bed_w * scale, oy + bed_h * scale),
                           fill="#29343d", outline="#8da0ad", width=2)
            colors = ("#00ae42", "#28c76f", "#00c2a8", "#5ee28b")
            for part_index, placement in enumerate(placements):
                geoms = list(placement.geometry.geoms) if hasattr(placement.geometry, "geoms") else [placement.geometry]
                for poly in geoms:
                    if not hasattr(poly, "exterior"):
                        continue
                    points = [(ox + (x - minx) * scale, oy + (maxy - y) * scale)
                              for x, y in poly.exterior.coords]
                    draw.polygon(points, fill=colors[part_index % len(colors)], outline="#07170d")
        if len(solution) > len(display_solution):
            draw.text(
                (width - 300, 62),
                f"Mostrando 12/{len(solution)} placas",
                fill="#ffcc66", font=font,
            )

        token = uuid.uuid4().hex
        temp = self.image_path.with_name(f"{self.image_path.stem}.{token}.tmp.png")
        image.save(temp)
        image_published = self._replace_with_retry(temp, self.image_path)
        payload = {"generation": generation, "attempt": attempt, "plates": len(solution),
                   "score": list(score) if score is not None else [],
                   "elapsed_seconds": round(elapsed, 1), "finished": finished,
                   "debug": debug, "status": status, "progress": progress}
        state_temp = self.state_path.with_name(f"{self.state_path.stem}.{token}.tmp")
        state_temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        state_published = self._replace_with_retry(state_temp, self.state_path)
        if self.on_update is not None and image_published and state_published:
            self.on_update(self.image_path, payload)

    @staticmethod
    def _replace_with_retry(source: Path, target: Path, attempts: int = 7) -> bool:
        """Publish a frame without blocking the optimizer on transient viewer locks."""
        for attempt in range(attempts):
            try:
                source.replace(target)
                return True
            except PermissionError:
                if attempt + 1 < attempts:
                    time.sleep(min(0.1, 0.01 * (2 ** attempt)))
        logger.warning("Preview bloqueada; se descarta el frame %s", source.name)
        try:
            source.unlink(missing_ok=True)
        except OSError:
            pass
        return False
