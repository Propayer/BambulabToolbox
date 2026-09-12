import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from PySide6.QtCore import QTimer
from jarvis_bambu.gui.stl_color_map import STLColorMapWidget, render_light_preview
from test_height_raster import model


def application():
    return QApplication.instance() or QApplication([])


def finish(widget):
    deadline=time.monotonic()+10
    while widget.task is not None and time.monotonic()<deadline:
        QApplication.processEvents();QTest.qWait(5)
    assert widget.task is None


def test_worker_gallery_cache_edits_and_3d_lifecycle():
    app=application();w=STLColorMapWidget();m=model()
    w._loaded('steps.stl',(m,render_light_preview(m)))
    assert w.preview is None and not w.render_3d_active
    w.cuts=[1.5,2.5];w._refresh_cuts();w.generate_height_previews();finish(w)
    assert w._last_stacked.width()==512 and len(w._last_masks)==3
    raster=m.top_raster(512)
    w.height_picked(1.8);w.add_selected_cut();assert 1.8 in w.cuts
    w.generate_height_previews();finish(w)
    assert m.top_raster(512) is raster and w.heights_layout.count()==4
    with patch.object(QMessageBox,'exec',lambda dialog:None), patch.object(QMessageBox,'clickedButton',lambda dialog:dialog.buttons()[0]):
        w.start_3d()
    finish(w)
    assert w.render_3d_active and w.preview is not None
    viewer=w.preview;w.stop_3d()
    assert w.preview is None and viewer._map is None and not viewer._render_geometry
    assert not w.render_3d_active
    w.close();app.processEvents()


def test_cancellation_keeps_ui_alive():
    app=application();w=STLColorMapWidget();ticks=[]
    timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(1)
    def work(cancel, progress):
        while not cancel():time.sleep(.001)
        return 'cancelled'
    w._run_task('Test',work,lambda result:(_ for _ in ()).throw(AssertionError('Cancelled result applied')))
    QTest.qWait(25);w.cancel_task();finish(w)
    assert ticks and w.status.text()=='Operación cancelada.' and w.load_button.isEnabled()
    timer.stop();w.close()
