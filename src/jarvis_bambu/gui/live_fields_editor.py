"""Lightweight live-field editing on the full, unmodified DSC canvas."""
from copy import deepcopy
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QFontMetricsF
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,
    QLineEdit,QCheckBox,QDoubleSpinBox,QPushButton,QLabel,QFileDialog,QScrollArea)
from .workspace_widgets import ModelCanvas
from ..core.dsc_live_fields import import_template, validate_field, validate_fields


class HitboxCanvas(ModelCanvas):
    boxChanged = Signal(dict)

    def __init__(self):
        super().__init__('Personalización DSC','Genera la vista cenital para colocar los campos.')
        self.fields = []; self.selected = -1; self._drag = None
        self.setMouseTracking(True)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._pix.isNull():
            return
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        for index, field in enumerate(self.fields):
            box = field['hitbox']
            if box is None:
                continue
            r = self.box_rect(box)
            if field['enabled']:
                value = str(field['default']).replace('\n',' ').replace('\r',' ').replace('\t',' ')
                font = QFont('Arial'); font.setItalic(False); font.setWeight(QFont.DemiBold)
                lo, hi = 1, max(1,int(r.height()*2))
                while lo < hi:
                    mid = (lo+hi+1)//2; font.setPixelSize(mid); metrics = QFontMetricsF(font)
                    if metrics.horizontalAdvance(value) <= r.width()*.96 and metrics.height() <= r.height()*.9:
                        lo = mid
                    else:
                        hi = mid-1
                font.setPixelSize(lo); p.save(); p.setClipRect(r); p.setFont(font);p.setPen(QColor('#17121e'))
                p.drawText(r, Qt.AlignCenter, value); p.restore()
            p.setPen(QPen(QColor('#72E2C0' if index == self.selected else '#BBAAFF'),2 if index == self.selected else 1,Qt.DashLine))
            p.setBrush(Qt.NoBrush); p.drawRect(r)
            if index == self.selected:
                p.setBrush(QColor('#72E2C0'))
                for corner in (r.topLeft(),r.topRight(),r.bottomLeft(),r.bottomRight()):
                    p.drawRect(QRectF(corner.x()-4,corner.y()-4,8,8))
        p.end()

    def box_rect(self, box):
        r = self._rect
        return QRectF(r.x()+box['x']*r.width(),r.y()+box['y']*r.height(),box['width']*r.width(),box['height']*r.height())

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self._pix.isNull() or not 0 <= self.selected < len(self.fields):
            return
        box = self.fields[self.selected]['hitbox']
        if box is None:
            return
        r = self.box_rect(box); point = event.position()
        corners = (r.topLeft(),r.topRight(),r.bottomLeft(),r.bottomRight())
        corner = next((i for i,c in enumerate(corners) if abs(point.x()-c.x()) <= 9 and abs(point.y()-c.y()) <= 9),None)
        if corner is not None or r.contains(point):
            self._drag = (point,dict(box),corner)

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        start, box, corner = self._drag
        dx = (event.position().x()-start.x())/self._rect.width()
        dy = (event.position().y()-start.y())/self._rect.height()
        x,y,w,h = (box[k] for k in ('x','y','width','height'))
        if corner is None:
            x = max(0,min(1-w,x+dx)); y = max(0,min(1-h,y+dy))
        else:
            right,bottom = x+w,y+h
            if corner in (0,2):x = max(0,min(right-.001,x+dx))
            else:right = max(x+.001,min(1,right+dx))
            if corner in (0,1):y = max(0,min(bottom-.001,y+dy))
            else:bottom = max(y+.001,min(1,bottom+dy))
            w,h = right-x,bottom-y
        x,y = round(x,6),round(y,6)
        result = dict(x=x,y=y,width=min(round(w,6),1-x),height=min(round(h,6),1-y))
        self.boxChanged.emit(result)

    def mouseReleaseEvent(self, event):
        self._drag = None


class LiveFieldsEditor(QWidget):
    def __init__(self, color_ids):
        super().__init__()
        self.color_ids = color_ids; self.fields = []; self.index = -1; self._populating = False; self._dirty = False
        root = QHBoxLayout(self);root.setContentsMargins(0,12,0,0)
        controls = QWidget();controls.setObjectName('liveFieldControls')
        controls.setStyleSheet('QWidget#liveFieldControls { background: #1B282E; }')
        form = QVBoxLayout(controls)
        self.list = QComboBox();self.list.setMinimumContentsLength(12);self.list.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.list.currentIndexChanged.connect(self.select);form.addWidget(self.list)
        for title, action in [('Importar plantilla DSC',self.import_file),('Añadir campo',self.add_field),('Eliminar campo',self.remove_field)]:
            b = QPushButton(title);b.clicked.connect(action);form.addWidget(b)
        rows = QFormLayout();form.addLayout(rows)
        self.field_id = QLineEdit();self.label = QLineEdit();self.kind = QComboBox();self.kind.addItems(['text','number'])
        self.default = QLineEdit();self.enabled = QCheckBox('Mostrar valor');self.has_box = QCheckBox('Definir hitbox')
        for title,control in [('ID',self.field_id),('Nombre',self.label),('Tipo',self.kind),('Valor',self.default),('',self.enabled),('',self.has_box)]:rows.addRow(title,control)
        self.spins = {}
        for key,title in [('x','X'),('y','Y'),('width','Ancho'),('height','Alto')]:
            spin = QDoubleSpinBox();spin.setRange(0,1);spin.setDecimals(6);spin.setSingleStep(.01);rows.addRow(title,spin);self.spins[key] = spin
            spin.valueChanged.connect(self.mark_dirty)
        for edit in (self.field_id,self.label,self.default):edit.textChanged.connect(self.mark_dirty)
        self.kind.currentIndexChanged.connect(self.mark_dirty);self.enabled.toggled.connect(self.mark_dirty);self.has_box.toggled.connect(self.mark_dirty)
        apply = QPushButton('Aplicar cambios');apply.clicked.connect(self.apply_changes);form.addWidget(apply)
        self.message = QLabel('Coordenadas del canvas completo, de 0 a 1. Arrastra la caja o sus esquinas.');self.message.setWordWrap(True);form.addWidget(self.message);form.addStretch()
        scroll = QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(controls);scroll.setFixedWidth(280);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);root.addWidget(scroll)
        self.canvas = HitboxCanvas();self.canvas.boxChanged.connect(self.move_box);root.addWidget(self.canvas,1)
        self.populate()

    def mark_dirty(self, *_):
        if not self._populating and self.index >= 0:
            self._dirty = True
            self.message.setText('Cambios pendientes · pulsa Aplicar cambios para verlos.')

    def populate(self):
        self._populating = True
        f = self.fields[self.index] if self.index >= 0 else dict(field_id='',label='',type='text',default='',enabled=False,hitbox=None)
        self.field_id.setText(f['field_id']);self.label.setText(f['label']);self.kind.setCurrentText(f['type']);self.default.setText(str(f['default']))
        self.enabled.setChecked(f['enabled']);self.has_box.setChecked(f['hitbox'] is not None)
        box = f['hitbox'] or dict(x=.25,y=.4,width=.5,height=.15)
        for key,spin in self.spins.items():spin.setValue(box[key])
        for control in (self.field_id,self.label,self.kind,self.default,self.enabled,self.has_box,*self.spins.values()):control.setEnabled(self.index >= 0)
        self.canvas.fields = self.fields;self.canvas.selected = self.index;self.canvas.update()
        self._dirty = False;self._populating = False

    def commit(self):
        if self.index < 0 or not self._dirty:return
        value = self.default.text()
        if self.kind.currentText() == 'number' and value != '':
            import re
            if not re.fullmatch(r'-?\d{1,12}(\.\d{1,6})?',value):raise ValueError('Número inválido: máximo 12 dígitos y 6 decimales.')
            value = float(value) if '.' in value else int(value)
        f = validate_field(dict(field_id=self.field_id.text(),label=self.label.text(),type=self.kind.currentText(),default=value,
                    enabled=self.enabled.isChecked(),hitbox={k:s.value() for k,s in self.spins.items()} if self.has_box.isChecked() else None))
        incoming = deepcopy(self.fields);incoming[self.index] = f;validate_fields(incoming,self.color_ids())
        self.fields[self.index] = f;self.list.setItemText(self.index,f['label']);self._dirty = False
        self.canvas.fields = self.fields;self.canvas.update()

    def apply_changes(self):
        try:self.commit();self.message.setText('Campo actualizado · posición referida al canvas completo.')
        except ValueError as exc:self.message.setText(str(exc))

    def select(self, index):
        try:self.commit()
        except ValueError as exc:
            self.list.blockSignals(True);self.list.setCurrentIndex(self.index);self.list.blockSignals(False);self.message.setText(str(exc));return
        self.index = index;self.populate()

    def add(self, field):
        self.commit();incoming = [*self.fields,field];validate_fields(incoming,self.color_ids())
        self.fields.append(field);self.list.blockSignals(True);self.list.addItem(field['label']);self.list.setCurrentIndex(len(self.fields)-1);self.list.blockSignals(False)
        self.index = len(self.fields)-1;self.populate()

    def add_field(self):
        ids = set(self.color_ids()) | {f['field_id'] for f in self.fields};n = 1
        while f'text_{n}' in ids:n += 1
        try:self.add(dict(field_id=f'text_{n}',label=f'Texto {n}',type='text',default='LUNA',enabled=True,hitbox=dict(x=.25,y=.4,width=.5,height=.15)))
        except ValueError as exc:self.message.setText(str(exc))

    def import_file(self):
        path,_ = QFileDialog.getOpenFileName(self,'Importar plantilla de campo DSC','','Plantilla DSC (*.json)')
        if not path:return
        try:self.add(import_template(path));self.message.setText('Plantilla importada. ID y valores conservados.')
        except (ValueError,OSError) as exc:self.message.setText(str(exc))

    def remove_field(self):
        if self.index < 0:return
        self.fields.pop(self.index);self._dirty = False;self.list.blockSignals(True);self.list.removeItem(self.index);self.index = self.list.currentIndex();self.list.blockSignals(False);self.populate()

    def move_box(self, box):
        try:
            self.commit()
            if self.index < 0:return
            self.fields[self.index]['hitbox'] = box;self.populate()
        except ValueError as exc:self.message.setText(str(exc))

    def validated_fields(self):
        self.commit();return deepcopy(validate_fields(self.fields,self.color_ids()))

    def reset(self):
        self.fields.clear();self.index = -1;self._dirty = False;self.list.blockSignals(True);self.list.clear();self.list.blockSignals(False);self.canvas.clear_image();self.populate()
