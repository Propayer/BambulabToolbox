"""Typed Qt parameter controls, shared by imported and reconstructed models."""
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QFormLayout,QLineEdit,QDoubleSpinBox,QComboBox,QCheckBox,
    QHBoxLayout,QPushButton,QColorDialog,QScrollArea,QVBoxLayout,QLabel,QRadioButton,QButtonGroup)
from PySide6.QtGui import QColor


class ParametersEditor(QScrollArea):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWidgetResizable(True);self.document=None;self.controls={}
        self.changed=lambda:None
    def load(self,document,changed):
        self.document=document;self.changed=changed;self.controls={}
        host=QWidget();form=QFormLayout(host)
        colors=[p for p in document['parameters'] if p['type']=='color']
        for p in document['parameters']:
            kind=p['type'];val=p['default'];key=p['id']
            if kind=='number':
                field=QDoubleSpinBox();field.setDecimals(4);field.setRange(p.get('min',-1e6),p.get('max',1e6));field.setSingleStep(p.get('step',.1));field.setValue(val)
                field.valueChanged.connect(lambda v,p=p:self.set_value(p,v))
            elif kind=='boolean':
                field=QCheckBox();field.setChecked(val);field.toggled.connect(lambda v,p=p:self.set_value(p,v))
            elif kind=='select':
                field=QComboBox()
                for o in p['options']:field.addItem(o['label'],o['value'])
                field.setCurrentIndex(max(0,field.findData(val)))
                field.currentIndexChanged.connect(lambda i,p=p,w=field:self.set_value(p,w.itemData(i)))
            else:
                field=QLineEdit(str(val));field.setMaxLength(2000);field.textEdited.connect(lambda v,p=p:self.set_value(p,v))
            self.controls[key]=field
            row=QWidget();layout=QVBoxLayout(row);layout.setContentsMargins(0,0,0,8);layout.addWidget(field)
            if kind=='color':
                pick=QPushButton('Elegir color…');pick.clicked.connect(lambda checked=False,p=p,w=field:self.pick_color(p,w));layout.addWidget(pick)
            if colors:
                colorrow=QWidget();line=QHBoxLayout(colorrow);line.setContentsMargins(0,0,0,0)
                independent=QRadioButton('Independiente');inherit=QRadioButton('Heredar color de:')
                group=QButtonGroup(colorrow);group.addButton(independent);group.addButton(inherit)
                select=QComboBox()
                for c in colors:
                    if c['id']!=key:select.addItem(c['label'],c['id'])
                binding=p.get('color_binding',{'mode':'independent'})
                select.setCurrentIndex(max(0,select.findData(binding.get('source'))))
                inherit.setChecked(binding['mode']=='inherit');independent.setChecked(binding['mode']!='inherit');select.setEnabled(inherit.isChecked())
                line.addWidget(independent);line.addWidget(inherit);line.addWidget(select)
                def update(checked=False,p=p,i=inherit,s=select):
                    s.setEnabled(i.isChecked())
                    p['color_binding']={'mode':'inherit','source':s.currentData()} if i.isChecked() else {'mode':'independent'}
                    self.changed()
                inherit.toggled.connect(update);select.currentIndexChanged.connect(update);layout.addWidget(colorrow)
            label=p.get('label',key)+(' · oculto' if p.get('hidden') else '')
            form.addRow(label,row)
        if not document['parameters']:form.addRow(QLabel('No hay literales top-level editables. Revisa el SCAD o reconstruye desde 3MF.'))
        self.setWidget(host)
    def set_value(self,p,value):p['default']=value;self.changed()
    def pick_color(self,p,field):
        color=QColorDialog.getColor(QColor(p['default']),self,'Color')
        if color.isValid():field.setText(color.name());self.set_value(p,color.name())
