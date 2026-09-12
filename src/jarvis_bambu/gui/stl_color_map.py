from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import numpy as np
from PySide6.QtCore import Qt, Signal, QThread, Slot
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QInputDialog, QFileDialog, QMessageBox, QPushButton, QWidget,
)

from ..core.stl_color_map import (
    STLHeightMap,
    SUPPORTED_MODEL_EXTENSIONS,
    analyze_model,
    normalize_cuts,
)
from ..core.height_raster import DIAGNOSTIC_COLORS, CancelledError, check_cancel
from ..core.dsc_export import export_dsc
from .components import Card


_ZONE_COLORS = [QColor(c) for c in DIAGNOSTIC_COLORS]

def rgba_image(array):
    height, width, _ = array.shape
    return QImage(array.data, width, height, width*4, QImage.Format_RGBA8888).copy()


def render_light_preview(height_map, size=(256, 256)):
    raster = height_map.top_raster(min(size))
    return rgba_image(raster.rgba(raster.labels([]), neutral=True))


def render_height_previews(height_map, cuts, colors=None, *, stacked_size=512, layer_size=512, cancel=None, progress=None):
    raster = height_map.top_raster(stacked_size, cancel=cancel, progress=progress)
    labels = raster.labels(normalize_cuts(cuts, height_map.z_min, height_map.z_max))
    palette = [c.name() for c in colors] if colors else DIAGNOSTIC_COLORS
    stacked = rgba_image(raster.rgba(labels, palette))
    layers = [rgba_image(raster.rgba(labels, palette, zone=i)) for i in range(len(height_map.zones(cuts)))]
    masks = [rgba_image(raster.rgba(labels, zone=i, neutral=True)) for i in range(len(layers))]
    return stacked, layers, masks


class MapTask(QThread):
    progress = Signal(int)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.result = None
        self.error = None
        self.cancelled = False

    def run(self):
        try:
            self.result = self.operation(self.isInterruptionRequested, self.progress.emit)
        except Exception as exc:
            self.error = exc
        finally:
            self.cancelled = self.cancelled or self.isInterruptionRequested()
            self.operation = None


class STLColorMapWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.task = None
        self.zone_names = {}
        self._layers = []
        from .color_map_layout import build_map_workspace
        build_map_workspace(self)

        self.height_map: STLHeightMap | None = None
        self.cuts: list[float] = []
        self.selected_height: float | None = None
        self.render_3d_active = False
        self._last_stacked: QImage | None = None
        self._last_masks: list[QImage] = []

    def show_help(self, help_id):
        self.help_panel.show_help(help_id); self.help_panel.show()

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar modelo", "", "Modelos 3D (*.stl *.3mf)")
        if not path:
            return
        if Path(path).suffix.lower() not in SUPPORTED_MODEL_EXTENSIONS:
            QMessageBox.warning(self, "Formato no compatible", "Selecciona un STL o un 3MF.")
            return
        self.stop_3d()
        def analyze(cancel, progress):
            result = analyze_model(path, cancel=cancel)
            check_cancel(cancel)
            light = QImage.fromData(result.embedded_preview) if result.embedded_preview else QImage()
            if light.isNull():
                result.embedded_preview = None
                raster = result.top_raster(256, cancel=cancel, progress=progress)
                light = rgba_image(raster.rgba(raster.labels([]), neutral=True))
            return result, light
        self._run_task(f'Analizando {Path(path).suffix[1:].upper()}…', analyze,
                       lambda result: self._loaded(path, result))

    def _loaded(self, path, result):
        self.height_map, self._light_image = result
        self.zone_names.clear()
        self.cut_height.setRange(self.height_map.z_min, self.height_map.z_max)
        self.cut_height.setValue((self.height_map.z_min+self.height_map.z_max)/2)
        self.file_label.setText(Path(path).name)
        self.file_label.setToolTip(str(Path(path)))
        source = self.height_map.source_type.upper()
        self.summary.setText(
            f"{source} · Triángulos: {self.height_map.summary.triangle_count:,} · Altura: {self.height_map.summary.height:.3f} mm"
        )
        if self.height_map.detected_colors:
            colors = " · ".join(f"F{c.slot} {c.color}" for c in self.height_map.detected_colors)
            self.color_summary.setText(
                f"Colores detectados en 3MF: {len(self.height_map.detected_colors)} · {colors}\n"
                "Se usarán como guía para proponer cortes por altura."
            )
            self.warnings_button.show()
        else:
            self.color_summary.clear(); self.color_summary.hide(); self.warnings_button.hide()

        if self.height_map.warnings:
            self.color_summary.setText(self.color_summary.text()+'\n'+'\n'.join(self.height_map.warnings))
            self.warnings_button.setText("Revisar avisos del 3MF")
            self.warnings_button.show()
        else:
            self.warnings_button.setText("Colores detectados en el 3MF")
        self.color_summary.hide()
        self._show_light_preview()
        self._clear_height_gallery()
        self.proposal.blockSignals(True); self.proposal.clear()
        for item in self.height_map.proposals:
            suffix = f" · {len(item.cuts)+1} zonas" if item.cuts else " · sin cortes detectados"
            names = {'simple':'Simple','balanced':'Equilibrado','detailed':'Detallado','uniform':'Uniforme','3mf_colors':'Colores del 3MF'}
            self.proposal.addItem(names.get(item.id,item.name) + suffix, item.id)
            self.proposal.setItemData(self.proposal.count() - 1, item.description, Qt.ToolTipRole)
        self.proposal.blockSignals(False)
        guided_index = self.proposal.findData("3mf_colors")
        if guided_index >= 0 and not self.height_map.warnings:
            self.proposal.setCurrentIndex(guided_index)
        else:
            balanced = self.proposal.findData("balanced")
            self.proposal.setCurrentIndex(balanced if balanced >= 0 else 0)
        self.apply_proposal()
        self._busy_controls(False)
        self.status.setText('Modelo cargado. Genera la vista de alturas.')

    def _show_light_preview(self):
        if not self.height_map:
            return
        self.light_preview.set_image(self._light_image, smooth=True, crop=bool(self.height_map.embedded_preview))
        self.light_preview.badge = 'VISTA LIGERA'
        if self.height_map.embedded_preview:
            self.light_note.setText('Imagen del 3MF · genera la vista cenital para comprobar las alturas.')
        else:
            self.light_note.setText('Huella del modelo · genera el mapa para ver las zonas de color.')


    def apply_proposal(self):
        if not self.height_map or self.proposal.currentIndex() < 0:
            return
        proposal_id = self.proposal.currentData()
        proposal = next((p for p in self.height_map.proposals if p.id == proposal_id), None)
        self.zone_names.clear()
        self.cuts = list(proposal.cuts if proposal else ())
        self._refresh_cuts()

    def _active_colors(self) -> list[QColor]:
        return list(_ZONE_COLORS)

    def height_picked(self, z: float):
        self.selected_height = z; self.selected.setText(f"Altura seleccionada: {z:.3f} mm")
        self.cut_height.blockSignals(True); self.cut_height.setValue(z); self.cut_height.blockSignals(False)
        if self.height_map:
            self.cuts_list.setCurrentRow(int(np.searchsorted(self.cuts, z, side='right')))
        self.add_cut_button.setEnabled(bool(self.height_map) and self.task is None)

    def add_selected_cut(self):
        if not self.height_map or self.selected_height is None:
            return
        if len(self.cuts) >= 11:
            QMessageBox.warning(self, "Límite DSC", "DSC admite como máximo 12 zonas."); return
        self.zone_names.clear()
        self.cuts = normalize_cuts([*self.cuts, self.selected_height], self.height_map.z_min, self.height_map.z_max)
        self._refresh_cuts()

    def remove_selected_cut(self):
        row = self.cuts_list.currentRow()
        if row < 0 or row >= len(self.cuts):
            return
        self.zone_names.clear()
        del self.cuts[row]; self._refresh_cuts()

    def _refresh_cuts(self):
        self.cuts_list.clear()
        if not self.height_map:
            return
        active = next((p for p in self.height_map.proposals if p.id == self.proposal.currentData()), None)
        if active is None or list(active.cuts) != list(self.cuts):
            self.proposal.blockSignals(True)
            self.proposal.setPlaceholderText(f'Manual · {len(self.cuts) + 1} zonas')
            self.proposal.setCurrentIndex(-1)
            self.proposal.blockSignals(False)
        from PySide6.QtWidgets import QListWidgetItem
        from PySide6.QtGui import QIcon
        from PySide6.QtCore import QSize
        for i,zone in enumerate(self.current_zones()):
            swatch=QPixmap(12,12);swatch.fill(_ZONE_COLORS[i % len(_ZONE_COLORS)])
            item=QListWidgetItem(QIcon(swatch),f'{zone.label}\n{zone.z_from:.3f} → {zone.z_to:.3f} mm')
            item.setSizeHint(QSize(0,58));item.setToolTip(f'{zone.id} · {zone.label}')
            self.cuts_list.addItem(item)
        self.remove_cut_button.setEnabled(False)
        self.add_cut_button.setEnabled(True)
        # Existing generated height images become stale after any map edit.
        self._clear_height_gallery()
        if self.render_3d_active:
            self._update_3d_geometry()

    def _clear_height_gallery(self):
        while self.heights_layout.count():
            item = self.heights_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.heights_scroll.hide(); self._last_stacked = None; self._last_masks = []; self._layers = []
        self.masks_empty.show();self.isolate_button.setEnabled(False)
        self.isolate_button.setChecked(False)
        if getattr(self,'height_map',None):
            self.map_state.setText('POR ACTUALIZAR');self._show_light_preview()
        else:
            self.map_state.setText('PENDIENTE')

    def generate_height_previews(self):
        if not self.height_map:
            return
        model, cuts, size = self.height_map, list(self.cuts), self.resolution.currentData()
        self._run_task('Generando mapa y máscaras…',
            lambda cancel, progress: render_height_previews(model, cuts, stacked_size=size, cancel=cancel, progress=progress),
            self._display_heights)

    def _display_heights(self, result):
        self._clear_height_gallery()
        stacked, layers, masks = result
        self._last_stacked = stacked; self._last_masks = masks
        raster = self.height_map.top_raster(self.resolution.currentData())
        self._layers=layers
        from .workspace_widgets import ModelCanvas
        for index, (zone, image) in enumerate(zip(self.current_zones(), layers)):
            cell=Card(zone.label,f'{zone.z_from:.3f} → {zone.z_to:.3f} mm')
            view=ModelCanvas();view.setFixedHeight(160);view.set_image(image)
            cell.layout.addWidget(view)
            choose=QPushButton('Ver esta zona');choose.setProperty('quiet',True)
            choose.clicked.connect(lambda checked=False,i=index:self.show_zone(i))
            cell.layout.addWidget(choose)
            self.heights_layout.addWidget(cell,index//2,index%2)
        self.masks_empty.hide();self.heights_scroll.show()
        self.light_preview.set_image(stacked,raster)
        self.light_preview.badge='VISTA CENITAL · +Z / XY'
        self.light_note.setText(f'{len(layers)} zonas · {stacked.width()} × {stacked.height()} px · pulsa para elegir una altura')
        self.map_state.setText('ACTUALIZADO');self.isolate_button.setEnabled(True)
        self.status.setText('Máscaras listas para exportar.')

    def zone_selected(self, row):
        ready=bool(getattr(self,'height_map',None)) and self.task is None
        self.remove_cut_button.setEnabled(ready and 0 <= row < len(self.cuts))
        self.edit_cut_button.setEnabled(ready and 0 <= row < len(self.cuts))
        self.rename_button.setEnabled(ready and row >= 0)
        self.update_canvas_selection()

    def update_canvas_selection(self):
        row=self.cuts_list.currentRow()
        if self._last_stacked is None:return
        image=self._layers[row] if self.isolate_button.isChecked() and 0 <= row < len(self._layers) else self._last_stacked
        raster=self.height_map.top_raster(self.resolution.currentData())
        self.light_preview.set_image(image,raster)

    def show_zone(self,row):
        self.cuts_list.setCurrentRow(row);self.isolate_button.setChecked(True)
        self.update_canvas_selection();self.tabs.setCurrentIndex(0)

    def start_3d(self):
        if not self.height_map or self.render_3d_active:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Renderizado 3D opcional')
        dialog.setText('El renderizado 3D puede utilizar una cantidad considerable de CPU/GPU y memoria, especialmente con modelos complejos. ¿Quieres activarlo?')
        if self.height_map.summary.triangle_count > 6000:
            dialog.setInformativeText('El archivo contiene demasiados triángulos para la vista 3D recomendada. Se mostrará una muestra de 6.000 caras para interacción; usa el modo ligero y las máscaras para comprobar el resultado exacto.')
        start = dialog.addButton('Empezar renderizado 3D', QMessageBox.AcceptRole)
        cancel = dialog.addButton('Cancelar', QMessageBox.RejectRole)
        dialog.setDefaultButton(cancel); dialog.exec()
        if dialog.clickedButton() != start:
            return
        from .height_viewer import STLMapPreview
        self.preview = STLMapPreview()
        self.preview.heightPicked.connect(self.height_picked)
        self.render_layout.insertWidget(self.render_layout.count()-1,self.preview,1)
        self.render_placeholder.hide();self.start_3d_button.hide()
        self.stop_3d_button.show();self.reset_button.show()
        self.render_3d_active = True
        self.preview.set_model(self.height_map); self.preview.show()
        self._update_3d_geometry()
        self.start_3d_button.setEnabled(False); self.stop_3d_button.setEnabled(True); self.reset_button.setEnabled(True)
        self.selected.setText("Altura seleccionada: haz clic sobre el modelo")

    def _update_3d_geometry(self):
        from ..core.viewer_geometry import preview_geometry
        model, cuts = self.height_map, list(self.cuts)
        self._run_task('Preparando geometría 3D…',
            lambda cancel, progress: preview_geometry(model, cuts), self._set_3d_geometry)

    def _set_3d_geometry(self, geometry):
        if self.preview is not None and self.render_3d_active:
            self.preview.set_cuts(self.cuts, geometry)

    def stop_3d(self):
        if self.preview is not None:
            self.preview.clear_model(); self.preview.hide()
            self.render_layout.removeWidget(self.preview)
            self.preview.deleteLater(); self.preview = None
        self.render_3d_active = False
        self.render_placeholder.show();self.start_3d_button.show()
        self.stop_3d_button.hide();self.reset_button.hide()
        if hasattr(self, "stop_3d_button"):
            self.stop_3d_button.setEnabled(False); self.reset_button.setEnabled(False)
            self.start_3d_button.setEnabled(bool(self.height_map))
        self.selected_height = None
        if hasattr(self, "selected"):
            self.selected.setText("Altura seleccionada: —")
        if hasattr(self, "add_cut_button"):
            self.add_cut_button.setEnabled(False)

    def export_package(self):
        if not self.height_map:
            return
        target = QFileDialog.getExistingDirectory(self, "Carpeta donde exportar el paquete DSC")
        if not target:
            return
        stem = Path(self.height_map.summary.source_name).stem
        destination = Path(target) / f'{stem}-dsc-preview.zip'
        if destination.exists() and QMessageBox.question(self, 'Reemplazar paquete', 'Ya existe este ZIP. ¿Quieres reemplazarlo?') != QMessageBox.Yes:
            return
        model, cuts, size, zones = self.height_map, list(self.cuts), self.resolution.currentData(), self.current_zones()
        self._run_task('Generando máscaras y exportando DSC…',
            lambda cancel, progress: export_dsc(destination, model, cuts, size=size, zones=zones, cancel=cancel, progress=progress),
            lambda path: QMessageBox.information(self, 'Paquete exportado', f'{path}\n\nEn Taller, edita el modelo e importa este paquete DSC. Revisa los campos y guarda el modelo.'))

    def current_zones(self):
        return [replace(z, id=self.zone_names.get(i,(z.id,z.label))[0], label=self.zone_names.get(i,(z.id,z.label))[1])
                for i,z in enumerate(self.height_map.zones(self.cuts))]

    def rename_zone(self):
        row = self.cuts_list.currentRow()
        if not self.height_map or row < 0:
            return
        zone = self.current_zones()[row]
        label, ok = QInputDialog.getText(self, 'Nombre de zona', 'Nombre visible:', text=zone.label)
        if not ok or not label.strip(): return
        identifier, ok = QInputDialog.getText(self, 'ID de zona', 'ID del campo DSC:', text=zone.id)
        if not ok: return
        import re
        if (not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', identifier) or identifier in ('constructor','prototype','__proto__')
                or len(label.strip()) > 100 or any(z.id == identifier for i,z in enumerate(self.current_zones()) if i != row)):
            QMessageBox.warning(self, 'Nombre / ID inválido', 'Usa un ID único en minúsculas y un nombre de hasta 100 caracteres.'); return
        self.zone_names[row] = (identifier, label.strip()); self._refresh_cuts()

    def edit_cut(self):
        row = self.cuts_list.currentRow()
        if row < 0 or row >= len(self.cuts): return
        value, ok = QInputDialog.getDouble(self, 'Editar corte', 'Altura exacta (mm):', self.cuts[row],
                                          self.height_map.z_min, self.height_map.z_max, 4)
        if ok:
            self.cuts[row] = value
            self.cuts = normalize_cuts(self.cuts, self.height_map.z_min, self.height_map.z_max)
            self._refresh_cuts()

    def _busy_controls(self, busy):
        ready = bool(self.height_map) and not busy
        self.load_button.setEnabled(not busy)
        for control in (self.proposal,self.cut_height,self.cuts_list,self.rename_button,self.resolution,
                        self.export_button,self.generate_heights_button,self.start_3d_button):
            control.setEnabled(ready)
        self.add_cut_button.setEnabled(ready)
        self.remove_cut_button.setEnabled(ready and 0 <= self.cuts_list.currentRow() < len(self.cuts))
        if self.render_3d_active:
            self.start_3d_button.setEnabled(False)
        self.edit_cut_button.setEnabled(ready and 0 <= self.cuts_list.currentRow() < len(self.cuts))
        self.light_preview.setEnabled(not busy)
        self.isolate_button.setEnabled(ready and self._last_stacked is not None)
        self.heights_scroll.setEnabled(not busy)
        if self.preview: self.preview.setEnabled(not busy)
        self.cancel_button.setVisible(busy); self.progress.setVisible(busy)

    def _run_task(self, message, operation, callback):
        if self.task is not None: return
        self.status.setText(message); self.progress.setRange(0,0)
        self.map_state.setText('PROCESANDO')
        self._busy_controls(True)
        self._task_callback = callback
        self.task = MapTask(operation, self)
        self.task.progress.connect(self._progress)
        self.task.finished.connect(self._task_finished)
        self.task.start()

    @Slot(int)
    def _progress(self, value):
        self.progress.setRange(0,100); self.progress.setValue(value)

    @Slot()
    def _task_finished(self):
        task, self.task = self.task, None
        callback, self._task_callback = self._task_callback, None
        try:
            if task.cancelled or isinstance(task.error, CancelledError):
                self.status.setText('Operación cancelada.')
            elif task.error:
                self.status.setText(str(task.error))
                QMessageBox.critical(self, 'No se pudo completar la operación', str(task.error))
            else:
                callback(task.result)
                self.status.setText('Máscaras listas para exportar.' if self._last_stacked is not None else 'Modelo listo. Genera la vista de alturas.' if self.height_map else 'Listo')
        finally:
            task.result = None; task.deleteLater(); self._busy_controls(False)
            self.map_state.setText('ACTUALIZADO' if self._last_stacked is not None else 'POR ACTUALIZAR' if self.height_map else 'PENDIENTE')

    def cancel_task(self):
        if self.task:
            self.task.cancelled = True
            self.task.requestInterruption(); self.status.setText('Cancelando…')

    def shutdown(self):
        self.stop_3d()
        if self.task is not None:
            self.cancel_task()
            return False
        return True
