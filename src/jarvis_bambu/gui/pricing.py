from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QGridLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .components import Card, HelpButton
from ..core.installation import InstallationSettingsStore
from ..excel_report import DEFAULT_PRICE_COLUMNS, MANDATORY_PRICE_COLUMNS, PRICE_COLUMNS
from ..price_analysis import (
    GlobalPriceOptions, PriceAnalysisItem, PriceAnalysisResult,
    SUPPORTED_PRICE_EXTENSIONS, analyze_price_files, export_price_analysis,
    inspect_price_file, item_final_price, price_components, recalculate_price_totals,
)
from ..resources import resource_path


def money(value):
    return "—" if value is None else f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def duration(minutes):
    if minutes is None:
        return "—"
    hours, mins = divmod(round(minutes), 60)
    return f"{hours} h {mins:02d} min" if hours else f"{mins} min"


class PriceFilesArea(QWidget):
    filesDropped = Signal(list)

    def __init__(self):
        super().__init__(); self.setAcceptDrops(True)
        self.layout = QVBoxLayout(self); self.content = QWidget(); self.layout.addWidget(self.content)
        self.overlay = QLabel("+\n\nSUELTA PARA AÑADIR ARCHIVOS\n\nSTL y 3MF compatibles", self)
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter); self.overlay.hide()
        self.overlay.setStyleSheet("background: rgba(20,20,20,190); color: white; border: 3px solid palette(highlight); border-radius: 14px; font-size: 16px; font-weight: 600;")

    @staticmethod
    def valid_paths(mime):
        return [Path(url.toLocalFile()) for url in mime.urls() if Path(url.toLocalFile()).suffix.lower() in SUPPORTED_PRICE_EXTENSIONS]

    def resizeEvent(self, event):
        self.overlay.setGeometry(self.rect()); super().resizeEvent(event)

    def dragEnterEvent(self, event):
        paths = self.valid_paths(event.mimeData())
        if paths:
            self.overlay.setText(f"+\n\nSUELTA PARA AÑADIR ARCHIVOS\n\n{len(paths)} archivo(s) compatible(s)")
            self.overlay.show(); self.overlay.raise_(); event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.valid_paths(event.mimeData()): event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.overlay.hide(); event.accept()

    def dropEvent(self, event):
        paths = self.valid_paths(event.mimeData()); self.overlay.hide()
        if paths: self.filesDropped.emit(paths); event.acceptProposedAction()


class PriceItemCard(Card):
    removeRequested = Signal(str); changed = Signal(); retryRequested = Signal(str)

    def __init__(self, item, options):
        super().__init__(f"📦 {item.display_name}", ""); self.item=item; self.options=options
        close=QPushButton("×"); close.clicked.connect(lambda:self.removeRequested.emit(item.id)); self.layout.addWidget(close)
        self.state=QLabel(); self.details=QLabel(); self.details.setWordWrap(True); self.layout.addWidget(self.state); self.layout.addWidget(self.details)
        controls=QHBoxLayout(); self.quantity=QSpinBox(); self.quantity.setRange(1,9999); self.quantity.setValue(item.quantity)
        self.multiplier=QDoubleSpinBox(); self.multiplier.setRange(.01,100); self.multiplier.setDecimals(2); self.multiplier.setSingleStep(.05); self.multiplier.setValue(item.price_multiplier)
        controls.addWidget(QLabel("Cantidad")); controls.addWidget(self.quantity); controls.addWidget(QLabel("Multiplicador")); controls.addWidget(self.multiplier); self.layout.addLayout(controls)
        self.price=QLabel(); self.layout.addWidget(self.price)
        self.error_detail=QPushButton("Ver detalle"); self.error_detail.clicked.connect(lambda:QMessageBox.warning(self,"Detalle del análisis",self.item.error)); self.layout.addWidget(self.error_detail)
        self.retry=QPushButton("Reintentar"); self.retry.clicked.connect(lambda:self.retryRequested.emit(item.id)); self.layout.addWidget(self.retry)
        self.quantity.valueChanged.connect(self._changed); self.multiplier.valueChanged.connect(self._changed); self.refresh()

    def _changed(self):
        self.item.quantity=self.quantity.value(); self.item.price_multiplier=self.multiplier.value(); self.changed.emit(); self.refresh()

    def refresh(self):
        labels={"imported":"○ Importado","analyzing":"◌ Analizando","analyzed":"● Analizado","warning":"⚠ Advertencia","error":"⚠ No se pudo analizar"}
        self.state.setText(labels.get(self.item.state,self.item.state)); self.retry.setVisible(self.item.state=="error"); self.error_detail.setVisible(self.item.state=="error")
        lines=[self.item.file_type]
        if self.item.piece_count is not None: lines.append(f"Piezas detectadas: {self.item.piece_count}")
        if self.item.metrics:
            m=self.item.metrics; lines += [f"Material: {m.material}",f"Peso: {m.weight_grams:.2f} g",f"Tiempo: {duration(m.print_minutes)}"]
        if self.item.error: lines.append(self.item.error)
        self.details.setText("\n".join(lines)); self.price.setText(f"Precio estimado: {money(item_final_price(self.item,self.options))}")


class ColumnsDialog(QDialog):
    def __init__(self, selected, order, parent=None):
        super().__init__(parent); self.setWindowTitle("Columnas del Excel"); layout=QVBoxLayout(self); self.list=QListWidget(); layout.addWidget(self.list)
        keys=[key for key in order if key in PRICE_COLUMNS]+[key for key in PRICE_COLUMNS if key not in order]
        for key in keys:
            item=QListWidgetItem(PRICE_COLUMNS[key][1]); item.setData(Qt.ItemDataRole.UserRole,key); item.setCheckState(Qt.CheckState.Checked if key in selected or key in MANDATORY_PRICE_COLUMNS else Qt.CheckState.Unchecked)
            if key in MANDATORY_PRICE_COLUMNS: item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(item)
        row=QHBoxLayout(); all_button=QPushButton("Seleccionar todas"); none=QPushButton("Deseleccionar todas"); defaults=QPushButton("Predeterminadas")
        for button in (all_button,none,defaults): row.addWidget(button)
        layout.addLayout(row); all_button.clicked.connect(lambda:self._checks(set(PRICE_COLUMNS))); none.clicked.connect(lambda:self._checks(set())); defaults.clicked.connect(lambda:self._checks(set(DEFAULT_PRICE_COLUMNS)))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def _checks(self, selected):
        for i in range(self.list.count()):
            item=self.list.item(i); key=item.data(Qt.ItemDataRole.UserRole); item.setCheckState(Qt.CheckState.Checked if key in selected or key in MANDATORY_PRICE_COLUMNS else Qt.CheckState.Unchecked)

    def values(self):
        order=[self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        selected=[self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState()==Qt.CheckState.Checked]
        return selected,order


from PySide6.QtCore import QObject
class AnalysisWorker(QObject):
    progress=Signal(dict); finished=Signal(object)
    def __init__(self,items,all_items,options): super().__init__(); self.items=items; self.all_items=all_items; self.options=options
    @Slot()
    def run(self):
        partial=analyze_price_files(self.items,self.options,self.progress.emit); partial.items=self.all_items; partial.totals=recalculate_price_totals(self.all_items,self.options); self.finished.emit(partial)


class PricingWidget(QWidget):
    def __init__(self, store=None):
        super().__init__(); self.store=store or InstallationSettingsStore(); self.settings=self.store.load(); self.items=[]; self.cards={}; self.result=None; self.thread=None
        selected=self.settings.price_visible_columns or list(DEFAULT_PRICE_COLUMNS); order=self.settings.price_column_order or list(PRICE_COLUMNS)
        work=self.store.path.parent/"pricing_work"; bambu={"executable":self.settings.bambu_studio_executable,"slicing_timeout_seconds":900}
        self.options=GlobalPriceOptions(self.settings.price_global_multiplier,selected,work_folder=work,bambu_config=bambu); self.column_order=order
        outer=QVBoxLayout(self); toolbar=QHBoxLayout(); self.import_button=QPushButton("Importar"); self.import_button.clicked.connect(self.choose_files); self.global_multiplier=QDoubleSpinBox(); self.global_multiplier.setRange(.01,100); self.global_multiplier.setDecimals(2); self.global_multiplier.setValue(self.options.global_multiplier); self.global_multiplier.valueChanged.connect(self.commercial_changed); self.columns_button=QPushButton(); self.columns_button.clicked.connect(self.configure_columns)
        toolbar.addWidget(self.import_button); toolbar.addWidget(QLabel("Multiplicador global")); toolbar.addWidget(self.global_multiplier); toolbar.addWidget(HelpButton("pricing.global_multiplier")); toolbar.addWidget(self.columns_button); toolbar.addWidget(HelpButton("pricing.excel_columns")); outer.addLayout(toolbar)
        self.area=PriceFilesArea(); self.area.filesDropped.connect(self.add_files); self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); self.grid_host=QWidget(); self.grid=QGridLayout(self.grid_host); self.scroll.setWidget(self.grid_host); self.area.layout.addWidget(self.scroll); outer.addWidget(self.area,1)
        self.notice=QLabel(); outer.addWidget(self.notice); self.progress=QProgressBar(); self.progress.hide(); outer.addWidget(self.progress)
        self.summary=Card("RESUMEN",""); outer.addWidget(self.summary); actions=QHBoxLayout(); self.analyze_button=QPushButton("ANALIZAR"); self.analyze_button.setProperty("primary",True); self.analyze_button.clicked.connect(self.analyze); self.export_button=QPushButton("EXPORTAR EXCEL"); self.export_button.clicked.connect(self.export); self.export_button.hide(); self.new_button=QPushButton("Nuevo análisis"); self.new_button.clicked.connect(self.clear_analysis); actions.addWidget(self.analyze_button); actions.addWidget(self.export_button); actions.addWidget(self.new_button); outer.addLayout(actions)
        self.export_result=Card("✓ EXCEL GENERADO",""); self.export_result.hide(); self.open_excel=QPushButton("Abrir Excel"); self.open_folder=QPushButton("Abrir carpeta"); self.export_result.layout.addWidget(self.open_excel); self.export_result.layout.addWidget(self.open_folder); outer.addWidget(self.export_result); self._grid_columns=0; self.refresh()

    def choose_files(self):
        start=self.settings.price_last_import_folder or str(Path.home()); paths,_=QFileDialog.getOpenFileNames(self,"Importar archivos",start,"Archivos de impresión (*.3mf *.stl);;3MF (*.3mf);;STL (*.stl);;Todos (*.*)")
        if paths: self.add_files([Path(path) for path in paths])

    @Slot(list)
    def add_files(self, paths):
        known={str(item.path).casefold() for item in self.items}; omitted=duplicates=0
        for raw in paths:
            path=Path(raw).resolve()
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_PRICE_EXTENSIONS: omitted+=1; continue
            if str(path).casefold() in known: duplicates+=1; continue
            item=PriceAnalysisItem(path); item.piece_count=inspect_price_file(path); self.items.append(item); known.add(str(path).casefold()); self.settings.price_last_import_folder=str(path.parent)
        parts=[]
        if omitted: parts.append(f"{omitted} archivo(s) omitido(s): formato no compatible")
        if duplicates: parts.append(f"{duplicates} duplicado(s) omitido(s)")
        self.notice.setText(" · ".join(parts)); self.store.save(self.settings); self.refresh()

    def remove_item(self,item_id): self.items[:]=[item for item in self.items if item.id!=item_id]; self.result=None; self.refresh()
    def retry_item(self,item_id):
        for item in self.items:
            if item.id==item_id: item.state="imported"; item.error=""
        self.analyze()

    def commercial_changed(self):
        self.options.global_multiplier=self.global_multiplier.value(); self.settings.price_global_multiplier=self.options.global_multiplier; self.store.save(self.settings); self.update_summary()

    def configure_columns(self):
        dialog=ColumnsDialog(self.options.visible_categories,self.column_order,self)
        if dialog.exec():
            self.options.visible_categories,self.column_order=dialog.values(); self.settings.price_visible_columns=self.options.visible_categories; self.settings.price_column_order=self.column_order; self.store.save(self.settings); self.update_columns_button()

    def update_columns_button(self): self.columns_button.setText(f"Columnas del Excel: {len(set(self.options.visible_categories)|set(MANDATORY_PRICE_COLUMNS))} seleccionadas · Configurar")

    def refresh(self):
        while self.grid.count():
            child=self.grid.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        self.cards={}; columns=1 if self.width()<700 else 2 if self.width()<1100 else 3; self._grid_columns=columns
        if not self.items:
            card=Card("+", "Arrastra tus archivos aquí\n\nSTL o 3MF"); button=QPushButton("Importar"); button.clicked.connect(self.choose_files); card.layout.addWidget(button); self.grid.addWidget(card,0,0,1,columns)
        else:
            for index,item in enumerate(self.items):
                card=PriceItemCard(item,self.options); card.removeRequested.connect(self.remove_item); card.retryRequested.connect(self.retry_item); card.changed.connect(self.update_summary); self.cards[item.id]=card; self.grid.addWidget(card,index//columns,index%columns)
            more=Card("+", "Importar más\nSTL / 3MF"); button=QPushButton("Importar más"); button.clicked.connect(self.choose_files); more.layout.addWidget(button); index=len(self.items); self.grid.addWidget(more,index//columns,index%columns)
        self.analyze_button.setEnabled(bool(self.items) and self.thread is None); self.update_columns_button(); self.update_summary()

    def update_summary(self):
        totals=recalculate_price_totals(self.items,self.options); lines=[f"Archivos: {totals.files}",f"Unidades: {totals.units}"]
        if totals.weight_grams is not None: lines += [f"Material total: {totals.weight_grams:.2f} g",f"Tiempo total: {duration(totals.print_minutes)}",f"Coste base: {money(totals.base_cost)}",f"Precio calculado: {money(totals.final_price)}"]
        lines.append(f"Multiplicador global: {self.options.global_multiplier:.2f}×"); self.summary.body.setText("\n".join(lines))
        for card in self.cards.values(): card.refresh()

    def analyze(self):
        if not self.items or self.thread is not None:return
        pending=[item for item in self.items if item.state in ("imported","error","warning")]
        if not pending:return
        self.progress.setRange(0,len(pending)); self.progress.setValue(0); self.progress.show(); self.analyze_button.setEnabled(False); self.notice.setText("Analizando archivos…")
        self.thread=QThread(self); self.worker=AnalysisWorker(pending,self.items,self.options); self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.worker.progress.connect(self.analysis_progress); self.worker.finished.connect(self.analysis_done); self.worker.finished.connect(self.thread.quit); self.thread.finished.connect(self.analysis_thread_finished); self.thread.start()

    @Slot(dict)
    def analysis_progress(self,value):
        self.progress.setValue(value["current"]); self.notice.setText(f"Analizando {value['current']} / {value['total']}\n{Path(value['path']).name}")
        item=next((x for x in self.items if x.id==value["item_id"]),None)
        if item and item.id in self.cards: self.cards[item.id].refresh()

    @Slot(object)
    def analysis_done(self,result):
        self.result=result; self.progress.hide(); self.notice.setText(f"Análisis completado con {len(result.warnings)} advertencia(s)"); self.export_button.setVisible(any(item.metrics for item in self.items)); self.refresh()

    def analysis_thread_finished(self): self.thread=None; self.analyze_button.setEnabled(bool(self.items))

    def export(self):
        if not self.result:return
        start=self.settings.price_last_export_folder or str(Path.home()); path,_=QFileDialog.getSaveFileName(self,"Exportar análisis",str(Path(start)/"Analisis_precios.xlsx"),"Excel (*.xlsx)")
        if not path:return
        output=export_price_analysis(self.result,self.options,Path(path),resource_path("Plantilla_Analisis_Piezas.xlsx")); self.settings.price_last_export_folder=str(output.parent); self.store.save(self.settings); self.export_result.body.setText(str(output)); self.export_result.show(); self.open_excel.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(output)))); self.open_folder.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(output.parent))))

    def clear_analysis(self): self.items.clear(); self.result=None; self.export_button.hide(); self.export_result.hide(); self.notice.clear(); self.refresh()

    def resizeEvent(self,event):
        super().resizeEvent(event); columns=1 if self.width()<700 else 2 if self.width()<1100 else 3
        if self._grid_columns and columns!=self._grid_columns: self.refresh()
