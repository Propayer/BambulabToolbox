import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from jarvis_bambu.gui.live_fields_editor import LiveFieldsEditor
from test_dsc_v2 import FIELD


def editor():
    app=QApplication.instance() or QApplication([])
    w=LiveFieldsEditor(lambda:['color_1']);w.resize(1000,640);w.add(copy.deepcopy(FIELD))
    image=QImage(512,512,QImage.Format_RGBA8888);image.fill(Qt.white);w.canvas.set_image(image)
    w.show();app.processEvents();return app,w


def test_move_resize_normalized_and_window_independent():
    app,w=editor();c=w.canvas;r=c.box_rect(FIELD['hitbox']);start=r.center().toPoint()
    QTest.mousePress(c,Qt.LeftButton,pos=start);QTest.mouseMove(c,start+QPoint(30,20));QTest.mouseRelease(c,Qt.LeftButton,pos=start+QPoint(30,20));app.processEvents()
    moved=w.validated_fields()[0]['hitbox'];assert moved['x']>FIELD['hitbox']['x'] and moved['y']>FIELD['hitbox']['y']
    r=c.box_rect(moved);start=r.bottomRight().toPoint()
    QTest.mousePress(c,Qt.LeftButton,pos=start);QTest.mouseMove(c,start+QPoint(15,12));QTest.mouseRelease(c,Qt.LeftButton,pos=start+QPoint(15,12));app.processEvents()
    resized=w.validated_fields()[0]['hitbox'];assert resized['width']>moved['width'] and resized['height']>moved['height']
    stored=copy.deepcopy(w.validated_fields());w.resize(840,700);app.processEvents();assert w.validated_fields()==stored
    w.close()


def test_manual_values_disabled_null_and_invalid_pending():
    app,w=editor();w.spins['x'].setValue(.1);w.default.setText('SOL');w.enabled.setChecked(False)
    f=w.validated_fields()[0];assert f['default']=='SOL' and not f['enabled'] and f['hitbox']['x']==.1
    w.has_box.setChecked(False);assert w.validated_fields()[0]['hitbox'] is None
    w.field_id.setText('color_1')
    with pytest.raises(ValueError,match='únicos'):w.validated_fields()
    assert w.fields[0]['field_id']=='pet_name'
    w.close()
