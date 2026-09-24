"""Independent Toolbox wizard, following the existing QThread task pattern."""
from pathlib import Path
import copy
import json
import tempfile
from PySide6.QtCore import Qt,QSettings,QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,
    QTabWidget,QPlainTextEdit,QTableWidget,QTableWidgetItem,QComboBox,QFileDialog,QMessageBox,
    QSplitter,QProgressBar,QInputDialog)
from ..stl_color_map import MapTask
from .parameters import ParametersEditor
from ...core.scad_builder.makerworld import analyze_url,NO_SOURCE
from ...core.scad_builder.scad_analysis import analyze_scad
from ...core.scad_builder.reconstruction import new_document,set_mode
from ...core.scad_builder.generator import generate,prepare_package,export_package,open_package
from ...core.scad_builder.runner import run_openscad,find_openscad
from ...core.scad_builder.three_mf import analyze_3mf
from ...core.scad_builder.validation import compare
from ...core.stl_color_map import load_stl


class SCADBuilderWidget(QWidget):
    def __init__(self):
        super().__init__();self.task=None;self.reference=None;self.assets={};self.document=new_document();self.validation_files={}
        self.settings=QSettings('BambuLabToolbox','SCADBuilder')
        outer=QVBoxLayout(self)
        title=QLabel('MakerWorld → SCAD Builder');title.setProperty('heading',True);outer.addWidget(title)
        note=QLabel('SCAD público o reconstrucción asistida desde 3MF. Las propuestas geométricas requieren tu revisión.');note.setWordWrap(True);outer.addWidget(note)
        self.tabs=QTabWidget();outer.addWidget(self.tabs,1)
        source=QWidget();layout=QVBoxLayout(source);self.tabs.addTab(source,'1 · Origen')
        self.url=QLineEdit();self.url.setPlaceholderText('https://makerworld.com/en/models/…');layout.addWidget(self.url)
        self.buttons=[]
        row=QHBoxLayout();layout.addLayout(row)
        self.button(row,'Analizar URL',self.analyze_url);self.button(row,'Importar SCAD',self.import_scad);self.button(row,'Cargar 3MF',self.import_3mf);self.button(row,'Abrir paquete',self.open_saved)
        self.source_details=QPlainTextEdit();self.source_details.setReadOnly(True);self.source_details.setPlainText('Introduce una URL o carga un archivo local. No se accede a fuentes protegidas.');layout.addWidget(self.source_details)
        parts=QWidget();layout=QVBoxLayout(parts);self.tabs.addTab(parts,'2 · Reconstrucción')
        text=QLabel('¿Qué representa cada pieza? Un nombre parecido a “text” es solo un indicio.\nEl texto original debe ser una pieza separada para sustituirlo sin conservarlo debajo.');text.setWordWrap(True);layout.addWidget(text)
        self.parts=QTableWidget(0,5);self.parts.setHorizontalHeaderLabels(['Pieza / indicios','Dimensiones mm','Propuesta','Tratamiento','Color de pieza']);self.parts.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.parts)
        row=QHBoxLayout();layout.addLayout(row);self.button(row,'Ver pieza seleccionada',self.inspect_piece)
        self.piece_preview=QLabel('Selecciona una pieza para ver su silueta cenital.');self.piece_preview.setAlignment(Qt.AlignCenter);self.piece_preview.setMinimumHeight(150);layout.addWidget(self.piece_preview)
        self.parameters=ParametersEditor();self.tabs.addTab(self.parameters,'3 · Parámetros y colores')
        code=QWidget();layout=QVBoxLayout(code);self.tabs.addTab(code,'4 · SCAD editable')
        note=QLabel('Vista generada. Para conservar cambios manuales pulsa «Aplicar SCAD editado»; el editor de piezas vuelve a usarse al cargar un 3MF.');note.setWordWrap(True);layout.addWidget(note)
        self.code=QPlainTextEdit();layout.addWidget(self.code)
        row=QHBoxLayout();layout.addLayout(row);self.button(row,'Añadir parámetro',self.add_parameter);self.button(row,'Regenerar desde parámetros',self.refresh_code);self.button(row,'Aplicar SCAD editado',self.apply_code)
        validation=QWidget();layout=QVBoxLayout(validation);self.tabs.addTab(validation,'5 · Validar / comparar')
        row=QHBoxLayout();layout.addLayout(row)
        self.executable=QLineEdit(self.settings.value('openscad_path','') or find_openscad() or '');self.executable.setPlaceholderText('Ruta de openscad.exe');row.addWidget(self.executable)
        self.button(row,'Buscar…',self.choose_executable);self.button(row,'Validar y renderizar',self.validate)
        self.preview=QLabel('Render pendiente');self.preview.setMinimumSize(240,180);self.preview.setAlignment(Qt.AlignCenter);layout.addWidget(self.preview)
        self.logs=QPlainTextEdit();self.logs.setReadOnly(True);layout.addWidget(self.logs)
        bottom=QHBoxLayout();outer.addLayout(bottom)
        self.status=QLabel('Preparado');self.status.setWordWrap(True);bottom.addWidget(self.status,1)
        self.progress=QProgressBar();self.progress.setRange(0,100);bottom.addWidget(self.progress)
        self.cancel=QPushButton('Cancelar');self.cancel.setEnabled(False);self.cancel.clicked.connect(self.cancel_task);bottom.addWidget(self.cancel)
        self.export_button=self.button(bottom,'Exportar paquete ZIP',self.export)
        self.debounce=QTimer(self);self.debounce.setSingleShot(True);self.debounce.setInterval(200);self.debounce.timeout.connect(self.refresh_code)
        self.reload()
    def button(self,layout,label,callback):
        button=QPushButton(label);button.clicked.connect(callback);layout.addWidget(button);self.buttons.append(button);return button
    def run_task(self,label,operation,complete):
        if self.task:return
        self.status.setText(label);self.progress.setValue(0)
        for b in self.buttons:b.setEnabled(False)
        self.tabs.setEnabled(False);self.cancel.setEnabled(True)
        task=MapTask(operation,self);self.task=task;task.progress.connect(self.progress.setValue)
        def done():
            self.task=None
            for b in self.buttons:b.setEnabled(True)
            self.tabs.setEnabled(True);self.cancel.setEnabled(False)
            if task.cancelled:self.status.setText('Operación cancelada.')
            elif task.error:self.status.setText(str(task.error))
            else:
                try:complete(task.result)
                except Exception as exc:self.status.setText(str(exc))
            task.deleteLater()
        task.finished.connect(done);task.start()
    def cancel_task(self):
        if self.task:self.task.requestInterruption()
    def closeEvent(self,event):
        if self.task:
            self.cancel_task();self.status.setText('Cancelando antes de cerrar…');event.ignore()
        else:super().closeEvent(event)
    def changed(self):
        self.validation_files={};self.debounce.start()
    def reload(self):
        self.parameters.load(self.document,self.changed)
        self.parts.setRowCount(len(self.document['elements']))
        colors=[p for p in self.document['parameters'] if p['type']=='color']
        for row,e in enumerate(self.document['elements']):
            texts=[e['name']+' · '+', '.join(e['hints']), ' × '.join(f'{v:.2f}' for v in e['dimensions']),e['proposal']]
            for col,text in enumerate(texts):
                item=QTableWidgetItem(text);item.setFlags(item.flags() & ~Qt.ItemIsEditable);self.parts.setItem(row,col,item)
            mode=QComboBox()
            for label,value in [('Geometría fija (asset)','fixed'),('Texto paramétrico','text'),('Ignorar','ignore'),('Cubo / prisma','box'),('Cilindro aproximado','cylinder')]:mode.addItem(label,value)
            mode.setCurrentIndex(mode.findData(e['mode']));mode.currentIndexChanged.connect(lambda i,key=e['id'],w=mode:self.mode_changed(key,w.currentData()));self.parts.setCellWidget(row,3,mode)
            color=QComboBox()
            for p in colors:color.addItem(p['label'],p['id'])
            color.setCurrentIndex(max(0,color.findData(e.get('color_binding',{}).get('source'))))
            color.currentIndexChanged.connect(lambda i,e=e,w=color:self.piece_color(e,w.currentData()));self.parts.setCellWidget(row,4,color)
        self.parts.resizeColumnsToContents();self.parts.resizeRowsToContents();self.refresh_code()
    def piece_color(self,e,key):e['color_binding']={'mode':'inherit','source':key};self.changed()
    def mode_changed(self,key,mode):
        set_mode(self.document,key,mode);self.reload();self.changed()
    def refresh_code(self):
        try:
            # Attach stable placeholders for on-screen code; export replaces these with actual hashes.
            doc=copy.deepcopy(self.document)
            for e in doc['elements']:e.setdefault('asset','assets/'+e['fingerprint']+'.stl')
            self.code.setPlainText(generate(doc));self.status.setText(self.document['source_info']['reconstruction_mode'])
        except Exception as exc:self.status.setText(str(exc))
    def add_parameter(self):
        if self.document.get('original_source'):
            self.status.setText('Añade la variable en el SCAD editable y pulsa Aplicar SCAD editado.');return
        key,ok=QInputDialog.getText(self,'Añadir parámetro','ID interno (por ejemplo accent_color):')
        if not ok:return
        kind,ok=QInputDialog.getItem(self,'Tipo','Tipo de parámetro:', ['text','number','boolean','color','font'],0,False)
        if not ok:return
        from ...core.scad_builder.model import parameter,validate_parameters
        defaults={'text':'','number':0,'boolean':False,'color':'#FFFFFF','font':'Roboto'}
        candidate=parameter(key,kind,defaults[kind])
        try:validate_parameters([*self.document['parameters'],candidate])
        except Exception as exc:self.status.setText(str(exc));return
        self.document['parameters'].append(candidate);self.reload();self.tabs.setCurrentIndex(2)
    def inspect_piece(self):
        index=self.parts.currentRow()
        if index<0:self.status.setText('Selecciona una fila de pieza.');return
        e=self.document['elements'][index];ref=self.reference;assets=self.assets
        def work(cancel,progress):
            from ...core.scad_builder.generator import draw_preview
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'piece.png'
                if ref:triangles=ref.parts[index].triangles
                else:
                    asset=Path(tmp)/'piece.stl';asset.write_bytes(assets[e['asset']]);triangles=load_stl(asset)
                draw_preview(triangles,path)
                return path.read_bytes()
        def show(data):
            pix=QPixmap();pix.loadFromData(data);self.piece_preview.setPixmap(pix.scaled(260,180,Qt.KeepAspectRatio,Qt.SmoothTransformation))
            self.status.setText(e['name']+' · silueta cenital de referencia')
        self.run_task('Preparando vista de la pieza…',work,show)
    def analyze_url(self):
        url=self.url.text().strip()
        self.run_task('Analizando información pública…',lambda cancel,progress:analyze_url(url),self.url_loaded)
    def url_loaded(self,result):
        self.reference=None;self.assets={};self.validation_files={}
        self.document=new_document(source_info=result,source=result.get('original_scad'))
        details=[str(result.get('title','')),str(result.get('description','')),
                 'Parámetros visibles: '+json.dumps(result.get('visible_parameters',[]),ensure_ascii=False),
                 'Imágenes públicas:\n'+'\n'.join(result.get('images',[])),*result['warnings']]
        self.source_details.setPlainText('\n\n'.join(details));self.reload()
    def import_scad(self):
        path,_=QFileDialog.getOpenFileName(self,'Código SCAD público o propio','','OpenSCAD (*.scad)')
        if path:
            def load(cancel,progress):
                p=Path(path)
                if p.stat().st_size>2_000_000:raise ValueError('SCAD demasiado grande.')
                return p.read_text(encoding='utf-8-sig')
            self.run_task('Leyendo SCAD…',load,lambda code:self.scad_loaded(code,'user_supplied'))
    def scad_loaded(self,code,method):
        info=dict(self.document['source_info']);info['source_method']=method;info['original_scad_available']=True
        oldmode=info.get('reconstruction_mode')
        self.document=new_document(source=code,source_info=info);self.reference=None;self.assets={};self.validation_files={}
        if method=='manual_edit' and oldmode=='reconstructed SCAD':self.document['source_info']['reconstruction_mode']=oldmode;self.document['source_info']['original_scad_available']=False
        analysis=self.document['analysis'];self.source_details.setPlainText(json.dumps(analysis,ensure_ascii=False,indent=2));self.reload()
    def apply_code(self):
        try:
            ref,assets,elements=self.reference,self.assets,self.document['elements']
            self.scad_loaded(self.code.toPlainText(),'manual_edit')
            self.reference,self.assets=ref,assets
            self.document['elements']=elements
            self.reload()
        except Exception as exc:self.status.setText(str(exc))
    def import_3mf(self):
        path,_=QFileDialog.getOpenFileName(self,'3MF de referencia','','3MF (*.3mf)')
        if path:self.run_task('Analizando piezas 3MF…',lambda cancel,progress:analyze_3mf(path,cancel=cancel),lambda ref:self.reference_loaded(path,ref))
    def reference_loaded(self,path,reference):
        self.reference=reference;self.assets={};self.validation_files={}
        info=dict(self.document['source_info']);info['source_3mf']=Path(path).name
        self.document=new_document(reference,info);self.reload();self.tabs.setCurrentIndex(1)
    def choose_executable(self):
        path,_=QFileDialog.getOpenFileName(self,'Seleccionar OpenSCAD')
        if path:self.executable.setText(path);self.settings.setValue('openscad_path',path)
    def validate(self):
        doc=copy.deepcopy(self.document);ref=self.reference;assets=dict(self.assets);executable=self.executable.text().strip()
        self.settings.setValue('openscad_path',executable)
        def work(cancel,progress):
            with tempfile.TemporaryDirectory(prefix='toolbox-scad-render-') as temp:
                prepare_package(temp,doc,ref,assets)
                result=run_openscad(temp,executable,cancel=cancel,progress=progress)
                if 'generated.stl' in result['outputs']:
                    if ref:before=ref.triangles
                    elif assets:
                        import numpy as np
                        before=np.concatenate([load_stl(Path(temp)/e['asset'])+np.array(e['bounds_min']) for e in doc['elements']])
                    else:before=None
                    if before is not None:result['comparison']=compare(before,load_stl(Path(temp)/'generated.stl'))
                result['files']={p.name:p.read_bytes() for p in Path(temp).iterdir() if p.name in ('render.png','generated.stl','generated.3mf','validation.log')}
                return result
        self.run_task('Validando / renderizando OpenSCAD…',work,self.validated)
    def validated(self,result):
        self.logs.setPlainText(json.dumps(result.get('comparison',{}),ensure_ascii=False,indent=2)+'\n'+result['logs'])
        if 'render.png' in result['files']:
            pix=QPixmap();pix.loadFromData(result['files']['render.png']);self.preview.setPixmap(pix.scaled(320,240,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        self.validation_files=result['files']
        self.status.setText('Validación local correcta. Revisa la comparación y prueba también en PMM.' if result['ok'] else 'Validación incompleta: revisa los logs.');self.tabs.setCurrentIndex(4)
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'Exportar proyecto editable','model-scad.zip','ZIP (*.zip)')
        if not path:return
        doc=copy.deepcopy(self.document);ref=self.reference;assets=dict(self.assets);files=dict(self.validation_files)
        def work(cancel,progress):
            export_package(path,doc,ref,assets)
            if files:
                import zipfile
                with zipfile.ZipFile(path,'a',zipfile.ZIP_DEFLATED) as archive:
                    for name,data in files.items():archive.writestr('model/validation/'+name,data)
            return path
        self.run_task('Exportando paquete…',work,lambda p:self.status.setText('Paquete guardado: '+p))
    def open_saved(self):
        path,_=QFileDialog.getOpenFileName(self,'Abrir paquete SCAD Builder','','ZIP (*.zip)')
        if path:self.run_task('Abriendo paquete…',lambda cancel,progress:open_package(path),self.package_loaded)
    def package_loaded(self,result):
        self.document,self.assets=result;self.reference=None;self.validation_files={};self.url.setText(self.document['source_info'].get('source_url',''));self.reload()
