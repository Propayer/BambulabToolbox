"""Presentation of the map workspace, kept separate from its controller/core."""
from PySide6.QtCore import Qt,QSize
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,
    QDoubleSpinBox,QListWidget,QScrollArea,QGridLayout,QTabWidget,QFrame,QProgressBar,QSizePolicy)
from .components import Card,HelpButton
from .guide import HelpPanel
from .workspace_widgets import ModelCanvas,PageFade,line_icon


def label(text,role='muted'):
    w=QLabel(text);w.setProperty('role',role);w.setWordWrap(True)
    w.setMinimumWidth(0);w.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
    return w


def button(text,callback,primary=False):
    b=QPushButton(text);b.setCursor(Qt.PointingHandCursor);b.setProperty('primary',primary)
    b.clicked.connect(callback);return b


def scroll_for(widget):
    s=QScrollArea();s.setWidgetResizable(True);s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    s.setWidget(widget);s.setMinimumWidth(0);return s


def build_map_workspace(w):
    root=QVBoxLayout(w);root.setContentsMargins(24,20,24,16);root.setSpacing(16)
    heading=QHBoxLayout();titles=QVBoxLayout();titles.setSpacing(4)
    titles.addWidget(label('PREPARACIÓN DE MODELOS','eyebrow'))
    w.page_title=label('Mapa de color','pageTitle');titles.addWidget(w.page_title)
    titles.addWidget(label('Del modelo 3D a las zonas de color de tu producto.'))
    heading.addLayout(titles,1)
    w.load_button=button('Cargar STL / 3MF',w.load_file,True);w.load_button.setIcon(line_icon('upload','#10191D'))
    heading.addWidget(w.load_button,0,Qt.AlignTop)
    help_button=HelpButton('stl_map.workflow');help_button.helpRequested.connect(w.show_help)
    heading.addWidget(help_button,0,Qt.AlignTop);root.addLayout(heading)

    filebar=QFrame();filebar.setObjectName('fileBar');fr=QHBoxLayout(filebar);fr.setContentsMargins(16,10,16,10)
    ft=QVBoxLayout();ft.setSpacing(3)
    w.file_label=label('Sin modelo cargado','bodyStrong');w.summary=label('STL y 3MF · vista ligera al cargar')
    ft.addWidget(w.file_label);ft.addWidget(w.summary);fr.addLayout(ft,1)
    w.map_state=QLabel('PENDIENTE');w.map_state.setProperty('role','badge');fr.addWidget(w.map_state)
    root.addWidget(filebar)

    w.help_panel=HelpPanel();w.help_panel.hide();w.help_panel.setMaximumHeight(180)
    w.help_panel.closed.connect(w.help_panel.hide);root.addWidget(w.help_panel)
    body=QHBoxLayout();body.setSpacing(20);root.addLayout(body,1)
    w.controls=QWidget();left=QVBoxLayout(w.controls);left.setContentsMargins(0,0,8,0);left.setSpacing(16)
    w.controls_scroll=scroll_for(w.controls);w.controls_scroll.setFixedWidth(310);body.addWidget(w.controls_scroll)

    proposal_card=Card('01  Elegir una propuesta','Empieza con una división automática.')
    w.proposal=QComboBox();w.proposal.setMinimumContentsLength(14)
    w.proposal.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    w.proposal.currentIndexChanged.connect(w.apply_proposal);proposal_card.layout.addWidget(w.proposal)
    w.warnings_button=button('Revisar información del 3MF',lambda:w.color_summary.setVisible(not w.color_summary.isVisible()))
    w.warnings_button.setProperty('quiet',True);w.warnings_button.hide();proposal_card.layout.addWidget(w.warnings_button)
    w.color_summary=label('');w.color_summary.setProperty('role','warning');w.color_summary.hide()
    proposal_card.layout.addWidget(w.color_summary);left.addWidget(proposal_card)

    edit=Card('02  Ajustar las zonas','Selecciona una zona para editarla.')
    w.cuts_list=QListWidget();w.cuts_list.setObjectName('zoneList');w.cuts_list.setFixedHeight(188)
    w.cuts_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);w.cuts_list.setTextElideMode(Qt.ElideRight)
    w.cuts_list.setIconSize(QSize(12,12))
    w.cuts_list.currentRowChanged.connect(w.zone_selected);w.cuts_list.itemDoubleClicked.connect(w.edit_cut)
    edit.layout.addWidget(w.cuts_list)
    actions=QHBoxLayout()
    w.edit_cut_button=button('Editar corte',w.edit_cut);w.edit_cut_button.setProperty('quiet',True)
    w.rename_button=button('Nombre / ID',w.rename_zone);w.rename_button.setProperty('quiet',True)
    actions.addWidget(w.edit_cut_button);actions.addWidget(w.rename_button);edit.layout.addLayout(actions)
    edit.layout.addWidget(label('Añadir un corte a esta altura','bodyStrong'))
    addrow=QHBoxLayout();w.cut_height=QDoubleSpinBox();w.cut_height.setDecimals(4);w.cut_height.setSuffix(' mm')
    w.cut_height.valueChanged.connect(w.height_picked);addrow.addWidget(w.cut_height,1)
    w.add_cut_button=button('Añadir',w.add_selected_cut);addrow.addWidget(w.add_cut_button);edit.layout.addLayout(addrow)
    w.remove_cut_button=button('Eliminar corte seleccionado',w.remove_selected_cut);w.remove_cut_button.setProperty('quiet',True)
    edit.layout.addWidget(w.remove_cut_button)
    w.selected=label('También puedes pulsar el modelo para elegir una altura.');edit.layout.addWidget(w.selected)
    left.addWidget(edit)
    hint=label('03  Exporta tu paquete\nRevisa las máscaras y lleva el ZIP a Taller DSC.');left.addWidget(hint);left.addStretch()

    work=QWidget();wl=QVBoxLayout(work);wl.setContentsMargins(0,0,0,0);wl.setSpacing(10)
    w.tabs=QTabWidget();w.tabs.setDocumentMode(True);w.tabs.tabBar().setDrawBase(False);wl.addWidget(w.tabs,1);body.addWidget(work,1)
    top=QWidget();tl=QVBoxLayout(top);tl.setContentsMargins(0,16,0,0);tl.setSpacing(12)
    w.generate_heights_button=button('Generar vista previa de alturas',w.generate_height_previews,True)
    tl.addWidget(w.generate_heights_button)
    w.light_preview=ModelCanvas();w.light_preview.heightPicked.connect(w.height_picked)
    tl.addWidget(w.light_preview,1)
    bottom=QHBoxLayout();w.light_note=label('Vista ligera · el visor 3D permanece detenido.');bottom.addWidget(w.light_note,1)
    w.isolate_button=button('Solo esta zona',w.update_canvas_selection);w.isolate_button.setCheckable(True);w.isolate_button.setProperty('quiet',True)
    bottom.addWidget(w.isolate_button);tl.addLayout(bottom);w.tabs.addTab(top,'Vista cenital')

    masks=QWidget();ml=QVBoxLayout(masks);ml.setContentsMargins(0,16,0,0)
    ml.addWidget(label('Una máscara por color. Cada píxel pertenece a una sola zona.'))
    w.masks_empty=label('Genera la vista de alturas para revisar las máscaras.');ml.addWidget(w.masks_empty)
    w.heights_host=QWidget();w.heights_layout=QGridLayout(w.heights_host);w.heights_layout.setContentsMargins(0,0,0,0)
    w.heights_layout.setSpacing(16);w.heights_layout.setAlignment(Qt.AlignTop)
    w.heights_scroll=scroll_for(w.heights_host);w.heights_scroll.hide();ml.addWidget(w.heights_scroll,1)
    w.tabs.addTab(masks,'Máscaras')

    render=QWidget();rl=QVBoxLayout(render);rl.setContentsMargins(0,16,0,0);rl.setSpacing(12)
    w.render_note=label('Explora el modelo con rotación, zoom y selección de altura. Se activa solo cuando lo solicitas.')
    rl.addWidget(w.render_note)
    w.start_3d_button=button('Empezar renderizado 3D',w.start_3d,True);rl.addWidget(w.start_3d_button)
    w.render_placeholder=ModelCanvas('Explora cuando lo necesites','El renderizado está detenido. Tus máscaras no necesitan el visor 3D.')
    rl.addWidget(w.render_placeholder,1)
    w.render_layout=rl;w.preview=None
    rr=QHBoxLayout();w.stop_3d_button=button('Parar renderizado 3D',w.stop_3d)
    w.reset_button=button('Restablecer cámara',lambda:w.preview and w.preview.reset_view())
    rr.addWidget(w.stop_3d_button);rr.addWidget(w.reset_button);rl.addLayout(rr)
    w.stop_3d_button.hide();w.reset_button.hide();w.tabs.addTab(render,'Explorar 3D')
    w.tab_fade=PageFade(w.tabs);w.tabs.currentChanged.connect(lambda _:w.tab_fade.start())

    footer=QFrame();footer.setObjectName('exportBar');fl=QHBoxLayout(footer);fl.setContentsMargins(16,12,16,12);fl.setSpacing(12)
    state=QVBoxLayout();state.setSpacing(5)
    w.status=label('Carga un modelo para empezar.','status');state.addWidget(w.status)
    w.progress=QProgressBar();w.progress.setTextVisible(False);w.progress.hide();state.addWidget(w.progress)
    fl.addLayout(state,1)
    w.cancel_button=button('Cancelar',w.cancel_task);w.cancel_button.hide();fl.addWidget(w.cancel_button)
    w.resolution=QComboBox();w.resolution.setToolTip('Resolución del paquete DSC')
    for name,size in [('Rápida · 256 px',256),('Normal · 512 px',512),('Alta · 1024 px',1024)]:w.resolution.addItem(name,size)
    w.resolution.setCurrentIndex(1);w.resolution.currentIndexChanged.connect(w._clear_height_gallery);fl.addWidget(w.resolution)
    w.export_button=button('Exportar para DSC',w.export_package,True);fl.addWidget(w.export_button);root.addWidget(footer)
    for control in (w.proposal,w.cut_height,w.cuts_list,w.rename_button,w.edit_cut_button,w.add_cut_button,
                    w.remove_cut_button,w.generate_heights_button,w.export_button,w.start_3d_button,w.isolate_button):control.setEnabled(False)
