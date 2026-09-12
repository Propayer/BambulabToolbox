from __future__ import annotations
import logging, time, traceback
from PySide6.QtCore import QEasingCurve, QObject, QProcess, QPropertyAnimation, QThread, QTimer, Signal, Slot, Qt, QSize
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QGridLayout, QScrollArea, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QPlainTextEdit, QStackedWidget, QVBoxLayout, QWidget)
from . import APP_NAME, APP_VERSION
from .components import Card, HelpButton
from .guide import GuideWidget, HelpPanel
from .help_content import HELP
from .options import build_optimizer_options, effort_deadline_seconds
from .pricing import PricingWidget
from .registry import ToolDefinition
from .theme import APP_STYLESHEET, nebu_palette
from .workspace_widgets import line_icon
from PySide6.QtGui import QIcon, QPixmap
from ..resources import resource_path
from .timing import format_duration, human_duration, remaining_display
from .stl_color_map import STLColorMapWidget
from ..core.api import optimize_project
from ..core.installation import InstallationSettingsStore
from ..integrations.query_service import QueryService

logger = logging.getLogger(__name__)

class OptimizationWorker(QObject):
    progress=Signal(dict); finished=Signal(object); failed=Signal(str,str)
    def __init__(self, options): super().__init__(); self.options=options
    @Slot()
    def run(self):
        try:
            from ..optimize_current import _root, _session
            from ..settings import load_config
            source=_session(load_config(_root()/"config.yaml")).save_snapshot()
            self.finished.emit(optimize_project(source,self.options,progress_callback=self.progress.emit))
        except Exception as exc: self.failed.emit(str(exc),traceback.format_exc())

class OptimizerWidget(QWidget):
    def __init__(self):
        super().__init__(); outer=QHBoxLayout(self); host=QWidget(); form=QFormLayout(host)
        outer.addWidget(host,3); self.help_panel=HelpPanel(); self.help_panel.hide(); self.help_panel.closed.connect(self.help_panel.hide); outer.addWidget(self.help_panel,2)
        self.mode=QComboBox(); self.mode.addItems(["Simple","Avanzado"])
        self.mode.hide(); mode_row=QWidget(); mode_line=QHBoxLayout(mode_row); mode_line.setContentsMargins(0,0,0,0)
        self.simple_button=QPushButton("SIMPLE\nConservador"); self.advanced_button=QPushButton("AVANZADO\nMejor distribución")
        self.mode_group=QButtonGroup(self); self.mode_group.setExclusive(True)
        for button in (self.simple_button,self.advanced_button): button.setCheckable(True); button.setProperty("selectable",True); self.mode_group.addButton(button); mode_line.addWidget(button)
        self.simple_button.setChecked(True); self.simple_button.clicked.connect(lambda:self.mode.setCurrentText("Simple")); self.advanced_button.clicked.connect(lambda:self.mode.setCurrentText("Avanzado"))
        mode_help=HelpButton("optimizer.mode"); mode_help.helpRequested.connect(self.show_help); mode_line.addWidget(mode_help); form.addRow("Modo",mode_row)
        self.effort=QComboBox()
        for label in ("Rápido","Medio","Alto"): self.effort.addItem(f"{label} — hasta {human_duration(effort_deadline_seconds(label))}")
        self.preview=QCheckBox("Activada"); self.preview_mode=QComboBox(); self.preview_mode.addItems(["normal","debug"])
        self.workers=QComboBox(); self.workers.addItems(["Auto","1","2","4","6"])
        for label,widget,help_id in (("Esfuerzo",self.effort,"optimizer.effort"),("Preview",self.preview,"optimizer.preview"),("Modo preview",self.preview_mode,"optimizer.preview_mode"),("Workers",self.workers,"optimizer.workers")):
            row=QWidget(); line=QHBoxLayout(row); line.setContentsMargins(0,0,0,0); line.addWidget(widget)
            help_button=HelpButton(help_id); help_button.helpRequested.connect(self.show_help); line.addWidget(help_button)
            widget.setToolTip(HELP[help_id].short_description); form.addRow(label,row)
        self.effort_description=QLabel(); self.summary=QLabel(); self.summary.setWordWrap(True)
        self.status=QLabel("Preparado"); self.details=QLabel("Piezas: — · Plates: — · Mejor score: —"); self.details.setWordWrap(True)
        self.elapsed_label=QLabel("00:00"); self.remaining_label=QLabel("—")
        self.time_progress=QProgressBar(); self.time_progress.setRange(0,1000); self.time_progress.setTextVisible(False)
        self.time_progress.setToolTip("Presupuesto temporal de búsqueda; no es progreso real.")
        self.button=QPushButton("Optimizar proyecto actual"); self.button.setProperty("primary",True); self.button.clicked.connect(self.start)
        self.open_button=QPushButton("Abrir en Bambu Studio"); self.open_button.hide(); self.open_button.clicked.connect(self.open_result)
        self.back_button=QPushButton("Volver"); self.back_button.hide(); self.back_button.clicked.connect(self.reset_result)
        self.result_card=Card("✓ OPTIMIZACIÓN COMPLETADA",""); self.result_card.hide()
        self.open_button.setProperty("primary",True); self.result_card.layout.addWidget(self.open_button); self.result_card.layout.addWidget(self.back_button)
        form.addRow(self.effort_description); form.addRow("CONFIGURACIÓN",self.summary); form.addRow("Tiempo transcurrido",self.elapsed_label)
        form.addRow("Tiempo restante aprox.",self.remaining_label); form.addRow("Tiempo de búsqueda",self.time_progress)
        form.addRow(self.button); form.addRow("Estado",self.status); form.addRow(self.details); form.addRow(self.result_card)
        self.thread=None; self.last_result=None; self.started_at=None; self.deadline_seconds=None
        self.timer=QTimer(self); self.timer.setInterval(500); self.timer.timeout.connect(self.update_clock)
        for signal in (self.mode.currentTextChanged,self.effort.currentTextChanged,self.preview_mode.currentTextChanged,self.workers.currentTextChanged): signal.connect(self.update_summary)
        self.mode.currentTextChanged.connect(lambda text: self.advanced_button.setChecked(text == "Avanzado"))
        self.mode.currentTextChanged.connect(lambda text: self.simple_button.setChecked(text == "Simple"))
        self.preview.toggled.connect(self.preview_changed); self.preview_changed(False); self.update_summary()
    def show_help(self,help_id):
        self.help_panel.setMaximumWidth(0); self.help_panel.show_help(help_id)
        self.help_animation=QPropertyAnimation(self.help_panel,b"maximumWidth",self); self.help_animation.setDuration(180)
        self.help_animation.setStartValue(0); self.help_animation.setEndValue(380); self.help_animation.setEasingCurve(QEasingCurve.OutCubic); self.help_animation.start()
    def preview_changed(self,enabled): self.preview_mode.setEnabled(enabled); self.preview_mode.setVisible(enabled); self.update_summary()
    def update_summary(self):
        self.deadline_seconds=effort_deadline_seconds(self.effort.currentText()); duration=human_duration(self.deadline_seconds)
        self.effort_description.setText(f"Tiempo máximo de búsqueda: {duration}")
        preview=self.preview_mode.currentText().capitalize() if self.preview.isChecked() else "Desactivada"
        self.summary.setText(f"Modo: {self.mode.currentText()} · Esfuerzo: {self.effort.currentText().split(' —')[0]}\nTiempo máx.: {duration} · Workers: {self.workers.currentText()} · Preview: {preview}")
    def start(self):
        options=build_optimizer_options(self.mode.currentText(),self.effort.currentText(),self.preview.isChecked(),self.preview_mode.currentText(),self.workers.currentText())
        self.last_result=None; self.open_button.hide(); self.result_card.hide(); self.button.setEnabled(False); self.button.setText("Optimizando…"); self.status.setText("Preparando…")
        self.started_at=time.monotonic(); self.update_clock(); self.timer.start(); self.thread=QThread(self); self.worker=OptimizationWorker(options); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run); self.worker.progress.connect(self.show_progress); self.worker.finished.connect(self.done); self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.thread.quit); self.worker.failed.connect(self.thread.quit); self.thread.start()
    @Slot(object)
    def done(self,result):
        self.timer.stop(); self.time_progress.setValue(1000); self.remaining_label.setText("Completado")
        self.last_result=result; self.button.setEnabled(True); self.button.setText("Optimizar proyecto actual"); self.button.hide(); self.status.setText(f"Completado · {result.original_plate_count} → {result.final_plate_count}")
        self.elapsed_label.setText(format_duration(result.elapsed_seconds)); self.details.hide()
        result_name="Mejorado" if result.improved else "La distribución actual ya era igual o mejor"
        self.result_card.body.setText(f"<b>PLATES</b><br>{result.original_plate_count} → {result.final_plate_count}<br><br><b>TIEMPO</b><br>{format_duration(result.elapsed_seconds)}<br><br><b>RESULTADO</b><br>{result_name}<br><br>{result.message}")
        self.open_button.setVisible(bool(result.output_path)); self.back_button.show(); self.result_card.setMaximumHeight(0); self.result_card.show()
        self.result_animation=QPropertyAnimation(self.result_card,b"maximumHeight",self); self.result_animation.setDuration(200); self.result_animation.setStartValue(0); self.result_animation.setEndValue(420); self.result_animation.setEasingCurve(QEasingCurve.OutCubic); self.result_animation.start()
    @Slot(str,str)
    def failed(self,message,details):
        self.timer.stop(); self.button.setEnabled(True); self.button.setText("Optimizar proyecto actual"); self.status.setText("Error")
        box=QMessageBox(QMessageBox.Critical,"Error",message,parent=self); box.setDetailedText(details); box.exec()
    @Slot(dict)
    def show_progress(self,value):
        states={"starting":"Preparando…","optimizing":"Buscando una distribución mejor…","finished":"Finalizando…"}; self.status.setText(states.get(value.get("status"),value.get("status","Optimizando…")))
        progress=value.get("progress",value); self.details.setText(f"Piezas: {progress.get('placed','—')}/{progress.get('total','—')} · Plate: {progress.get('plate','—')} · Mejor score: {value.get('score','—')}")
    def update_clock(self):
        if self.started_at is None:return
        elapsed=max(0.0,time.monotonic()-self.started_at); self.elapsed_label.setText(format_duration(elapsed)); self.remaining_label.setText(remaining_display(elapsed,self.deadline_seconds))
        if self.deadline_seconds:
            self.time_progress.setValue(round(min(elapsed/self.deadline_seconds,1.0)*1000))
            if elapsed>=self.deadline_seconds:self.status.setText("Finalizando…")
    def open_result(self):
        if self.last_result and self.last_result.output_path:
            output_path=self.last_result.output_path
            logger.info("Opening optimization request_id=%s output_path=%s",self.last_result.request_id,output_path)
            settings=InstallationSettingsStore().load(); executable=settings.bambu_studio_executable or r"C:\Program Files\Bambu Studio\bambu-studio.exe"; QProcess.startDetached(executable,[str(output_path)])
    def reset_result(self):
        self.last_result=None; self.status.setText("Preparado"); self.details.setText("Piezas: — · Plates: — · Mejor score: —"); self.details.show(); self.button.show(); self.elapsed_label.setText("00:00"); self.remaining_label.setText("—"); self.time_progress.setValue(0); self.result_card.hide(); self.open_button.hide(); self.back_button.hide()

class SettingsWidget(QWidget):
    def __init__(self,store):
        super().__init__(); self.store=store; self.settings=store.load(); form=QFormLayout(self); self.device=QLineEdit(self.settings.device_id); self.device.setReadOnly(True)
        self.name=QLineEdit(self.settings.display_name); self.owner=QLineEdit(self.settings.owner); self.location=QLineEdit(self.settings.location); self.exe=QLineEdit(self.settings.bambu_studio_executable)
        self.workers=QComboBox(); self.workers.addItems(["Auto","1","2","4","6"]); self.workers.setCurrentText("Auto" if not self.settings.default_workers else str(self.settings.default_workers))
        for label,widget in (("Device ID",self.device),("Nombre",self.name),("Propietario",self.owner),("Ubicación",self.location),("Workers",self.workers),("Bambu Studio",self.exe)):form.addRow(label,widget)
        button=QPushButton("Guardar"); button.clicked.connect(self.save); form.addRow(button)
    def save(self):
        self.settings.display_name=self.name.text(); self.settings.owner=self.owner.text(); self.settings.location=self.location.text(); self.settings.bambu_studio_executable=self.exe.text(); self.settings.default_workers=0 if self.workers.currentText()=="Auto" else int(self.workers.currentText()); self.store.save(self.settings)

class QueriesWidget(QWidget):
    def __init__(self,settings,service=None):
        super().__init__(); self.settings=settings; self.service=service or QueryService(); form=QFormLayout(self); self.category=QComboBox(); self.category.addItems(["Optimizador","Calculador de precios","Aplicación","Otro"]); self.message=QPlainTextEdit(); self.status=QLabel(""); button=QPushButton("Enviar consulta"); button.clicked.connect(self.send); form.addRow("Categoría",self.category); form.addRow("Mensaje",self.message); form.addRow(button); form.addRow(self.status)
    def send(self):
        try:self.service.send(self.settings.device_id,self.settings.owner,self.category.currentText(),self.message.toPlainText()); self.status.setText("Consulta enviada")
        except RuntimeError as exc:self.status.setText(str(exc))

def text_page(title,body):
    widget=QWidget(); layout=QVBoxLayout(widget); layout.addWidget(Card(title,body)); layout.addStretch(); return widget

class HomeWidget(QWidget):
    navigate=Signal(str)
    def __init__(self,tools,settings,detected):
        super().__init__()
        from .color_map_layout import label
        layout=QVBoxLayout(self);layout.setContentsMargins(28,24,28,24);layout.setSpacing(16)
        layout.addWidget(label('TU TALLER · TUS HERRAMIENTAS','eyebrow'))
        layout.addWidget(label('¿Qué quieres preparar?','pageTitle'))
        layout.addWidget(label('Modelos, precios y organización. Elige una herramienta para empezar.'))
        status=Card('Tu espacio de trabajo',f"Bambu Studio {'detectado' if detected else 'no detectado'} · {settings.display_name}")
        layout.addWidget(status)
        grid_host=QWidget();grid=QGridLayout(grid_host);grid.setContentsMargins(0,0,0,0);grid.setSpacing(16)
        for i,tool in enumerate(tools):
            card=Card(tool.name,tool.description)
            icon=QLabel();icon.setPixmap(line_icon(tool.id,'#72E2C0').pixmap(26,26));card.layout.insertWidget(0,icon)
            card.layout.addStretch()
            button=QPushButton('Abrir herramienta  →');button.setProperty('quiet',True);button.setCursor(Qt.PointingHandCursor)
            button.setEnabled(tool.enabled);button.clicked.connect(lambda checked=False,tool_id=tool.id:self.navigate.emit(tool_id))
            card.layout.addWidget(button);grid.addWidget(card,i//2,i%2)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);scroll.setWidget(grid_host)
        layout.addWidget(scroll,1)

class MainWindow(QMainWindow):
    def __init__(self,store=None):
        super().__init__(); self.store=store or InstallationSettingsStore(); settings=self.store.load(); self.setWindowTitle(APP_NAME); self.resize(1360,860); self.setMinimumSize(960,640); self.setPalette(nebu_palette()); self.setStyleSheet(APP_STYLESHEET)
        root=QWidget();root.setObjectName('appRoot');row=QHBoxLayout(root);row.setContentsMargins(0,0,0,0);row.setSpacing(0)
        self.sidebar=QWidget();self.sidebar.setObjectName('sidebar');self.sidebar.setFixedWidth(208)
        side=QVBoxLayout(self.sidebar);side.setContentsMargins(12,24,12,16);side.setSpacing(16)
        brand=QHBoxLayout();brand.setSpacing(10)
        icon_path=resource_path('assets/BambuLabToolbox.ico')
        self.setWindowIcon(QIcon(str(icon_path)))
        logo=QLabel();logo.setPixmap(QPixmap(str(icon_path)).scaled(32,32,Qt.KeepAspectRatio,Qt.SmoothTransformation));brand.addWidget(logo)
        self.brand_text=QLabel('BambuLab\nToolbox');self.brand_text.setStyleSheet('font-size:16px;font-weight:600;');brand.addWidget(self.brand_text,1)
        side.addLayout(brand)
        self.nav_heading=QLabel('HERRAMIENTAS');self.nav_heading.setProperty('role','muted');side.addWidget(self.nav_heading)
        self.nav=QListWidget();self.nav.setObjectName('navigation');self.nav.setIconSize(QSize(20,20))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.nav.setSpacing(2)
        side.addWidget(self.nav,1)
        self.nav_footer=QLabel('DISEÑO NEBU\nLocal · Modular');self.nav_footer.setProperty('role','muted');side.addWidget(self.nav_footer)
        self.stack=QStackedWidget();self.stack.setObjectName('workspace');self.stack.setMinimumWidth(0)
        row.addWidget(self.sidebar);row.addWidget(self.stack,1);self.setCentralWidget(root)
        try:
            from ..bambu_session import BambuSession
            detected=bool(BambuSession._find_bambu_window()[0])
        except Exception:detected=False
        definitions=[ToolDefinition("optimizer","Optimizador","Distribuye las piezas automáticamente.","⚙",OptimizerWidget),ToolDefinition("stl_color_map","Mapa de color STL / 3MF","Analiza STL/3MF y genera zonas por altura para previews web.","◫",STLColorMapWidget),ToolDefinition("prices","Calculador de precios","Analiza STL/3MF y exporta precios a Excel.","€",lambda:PricingWidget(self.store)),ToolDefinition("guide","Guía","Ayuda navegable de la aplicación.","?",GuideWidget),ToolDefinition("queries","Consultas","Ayuda y consultas sobre tus herramientas.","✉",lambda:QueriesWidget(settings)),ToolDefinition("settings","Ajustes","Identidad y preferencias.","☰",lambda:SettingsWidget(self.store))]
        home=HomeWidget(definitions,settings,detected); all_defs=[ToolDefinition("home","Inicio","Herramientas","⌂",lambda:home),*definitions]; self.tools={tool.id:tool for tool in all_defs}; self.page_indices={}
        self._nav_names=[]
        for index,tool in enumerate(all_defs):
            name={'stl_color_map':'Mapa de color','prices':'Precios'}.get(tool.id,tool.name)
            item=QListWidgetItem(line_icon(tool.id),name);item.setToolTip(tool.name)
            self.nav.addItem(item);self._nav_names.append(name)
            self.stack.addWidget(tool.widget_factory());self.page_indices[tool.id]=index
        home.navigate.connect(lambda tool_id:self.nav.setCurrentRow(self.page_indices[tool_id])); self.nav.currentRowChanged.connect(self.stack.setCurrentIndex); self.nav.setCurrentRow(0)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not hasattr(self,'_nav_names'):return
        compact=self.width()<1180
        self.sidebar.setFixedWidth(72 if compact else 208)
        self.brand_text.setVisible(not compact);self.nav_heading.setVisible(not compact);self.nav_footer.setVisible(not compact)
        for i,name in enumerate(self._nav_names):self.nav.item(i).setText('' if compact else name)

    def closeEvent(self, event):
        page = self.stack.widget(self.page_indices['stl_color_map'])
        if not page.shutdown():
            # Cancel cooperatively; close only after QThread has finished.
            if not getattr(self, '_closing_map', False):
                self._closing_map = True
                page.task.finished.connect(self.close)
            event.ignore()
            return
        event.accept()

def run():
    app=QApplication.instance() or QApplication([]); app.setStyle('Fusion'); app.setPalette(nebu_palette()); app.setStyleSheet(APP_STYLESHEET); window=MainWindow(); window.show(); return app.exec()
