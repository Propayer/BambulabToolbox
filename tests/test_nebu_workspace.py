"""Layout regressions from the clipped Windows workspace screenshot."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QImage,QColor,QPainter
from PySide6.QtWidgets import QApplication
from jarvis_bambu.gui.app import MainWindow
from jarvis_bambu.gui.stl_color_map import render_light_preview,render_height_previews
from jarvis_bambu.gui.workspace_widgets import ModelCanvas
from test_height_raster import model

@pytest.mark.parametrize('size',[(960,640),(1000,720),(1360,860),(1920,1080)])
def test_workspace_fits_and_export_is_visible(size):
    app=QApplication.instance() or QApplication([])
    w=MainWindow();w.resize(*size);w.nav.setCurrentRow(w.page_indices['stl_color_map']);w.show();app.processEvents()
    v=w.stack.currentWidget();m=model();v._loaded('modelo-de-producto-con-un-nombre-muy-largo.3mf',(m,render_light_preview(m)))
    v.color_summary.setText('Información del 3MF. '*80);v.color_summary.show();app.processEvents()
    assert w.width()==size[0]
    assert v.controls.width()<=v.controls_scroll.viewport().width()
    assert v.controls_scroll.horizontalScrollBar().maximum()==0
    assert v.light_preview.width()>=200
    position=v.export_button.mapTo(w,QPoint(0,0))
    assert position.x()>=0 and position.x()+v.export_button.width()<=w.width()
    assert position.y()+v.export_button.height()<=w.height()
    assert v.preview is None
    assert w.sidebar.width()==(72 if size[0]<1180 else 208)
    w.close();app.processEvents()

def test_mask_selection_and_invalidation():
    app=QApplication.instance() or QApplication([]);w=MainWindow();v=w.stack.widget(w.page_indices['stl_color_map'])
    m=model();v._loaded('steps.stl',(m,render_light_preview(m)));v.cuts=[1.5,2.5];v._refresh_cuts()
    v._display_heights(render_height_previews(m,v.cuts));r=m.top_raster(512)
    v.show_zone(1)
    assert v.tabs.currentIndex()==0 and v.isolate_button.isChecked()
    assert v.light_preview._pix.toImage().pixelColor(256,256).alpha()==0
    assert v.light_preview.raster is r
    v.height_picked(1.8);v.add_selected_cut()
    assert v._last_stacked is None and not v.isolate_button.isEnabled()
    assert v.map_state.text()=='POR ACTUALIZAR'
    assert m.top_raster(512) is r
    w.close();app.processEvents()

def test_thumbnail_padding_only_cropped_in_light_preview():
    app=QApplication.instance() or QApplication([])
    image=QImage(200,200,QImage.Format_RGBA8888);image.fill(Qt.transparent)
    painter=QPainter(image);painter.fillRect(80,80,40,40,QColor('#72E2C0'));painter.end()
    c=ModelCanvas();c.set_image(image,crop=True)
    assert c._pix.width()==40 and image.width()==200
    c.set_image(image,crop=False)
    assert c._pix.width()==200
    c.close()
