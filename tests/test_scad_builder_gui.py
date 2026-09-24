import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import QTimer
from jarvis_bambu.gui.scad_builder import SCADBuilderWidget
from jarvis_bambu.gui.app import MainWindow
from jarvis_bambu.core.scad_builder.three_mf import analyze_3mf
from test_scad_builder import fixture_3mf


def app():return QApplication.instance() or QApplication([])
def finish(w):
    deadline=time.monotonic()+20
    while w.task and time.monotonic()<deadline:QApplication.processEvents();QTest.qWait(5)
    assert w.task is None


def test_editor_text_color_and_export_reopen(tmp_path):
    application=app();w=SCADBuilderWidget();w.resize(1100,800);w.show()
    source=fixture_3mf(tmp_path/'ref.3mf');w.reference_loaded(source,analyze_3mf(source))
    w.mode_changed('part_2','text');QTest.qWait(250)
    field=w.parameters.controls['part_2'];field.selectAll();QTest.keyClicks(field,'DANIELA');QTest.qWait(250)
    assert 'DANIELA' in w.code.toPlainText()
    assert 'color(base_color)' in w.code.toPlainText()
    w.parts.selectRow(1);w.inspect_piece();finish(w)
    assert not w.piece_preview.pixmap().isNull()
    # Manual code editing keeps original reference assets available.
    w.apply_code();assert w.reference is not None and len(w.document['elements'])==2
    w.close();application.processEvents()


def test_background_work_cancellation_and_main_window_close():
    application=app();main=MainWindow();w=main.stack.widget(main.page_indices['scad_builder'])
    ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(1)
    def work(cancel,progress):
        while not cancel():time.sleep(.001)
    w.run_task('Trabajo',work,lambda result:None);QTest.qWait(30)
    main.close();finish(w);assert ticks
    timer.stop();main.close();application.processEvents()
