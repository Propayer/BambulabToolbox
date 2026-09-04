import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QMimeData,QUrl
from PySide6.QtWidgets import QApplication,QPushButton

from jarvis_bambu.core.installation import InstallationSettingsStore
from jarvis_bambu.gui.pricing import PriceFilesArea,PricingWidget


def file(folder,name,content=b"x"):
    path=Path(folder)/name; path.write_bytes(content); return path


class Event:
    def __init__(self,paths): self._mime=QMimeData(); self._mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths]); self.accepted=False
    def mimeData(self): return self._mime
    def acceptProposedAction(self): self.accepted=True
    def accept(self): self.accepted=True
    def ignore(self): self.accepted=False


class PricingGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def widget(self,folder): return PricingWidget(InstallationSettingsStore(Path(folder)/"settings.json"))

    def test_multi_import_invalid_duplicate_remove_and_import_more(self):
        with tempfile.TemporaryDirectory() as folder:
            widget=self.widget(folder); stl=file(folder,"a.stl",b"solid a\nendsolid a"); mf=file(folder,"b.3mf"); png=file(folder,"x.png")
            widget.add_files([stl,mf,png,stl]); self.assertEqual(len(widget.items),2); self.assertIn("omitido",widget.notice.text()); self.assertIn("duplicado",widget.notice.text())
            self.assertTrue(any(button.text()=="Importar más" for button in widget.findChildren(QPushButton)))
            widget.remove_item(widget.items[0].id); self.assertEqual(len(widget.items),1); widget.clear_analysis(); self.assertEqual(widget.items,[])

    def test_dialog_selection_adds_without_replacing(self):
        with tempfile.TemporaryDirectory() as folder:
            widget=self.widget(folder); first=file(folder,"a.stl"); second=file(folder,"b.stl"); widget.add_files([first])
            with patch("jarvis_bambu.gui.pricing.QFileDialog.getOpenFileNames",return_value=([str(second)],"")): widget.choose_files()
            self.assertEqual([item.path for item in widget.items],[first.resolve(),second.resolve()])

    def test_drop_overlay_appears_leaves_and_emits_multiple(self):
        with tempfile.TemporaryDirectory() as folder:
            area=PriceFilesArea(); paths=[file(folder,"a.stl"),file(folder,"b.3mf")]; received=[]; area.filesDropped.connect(received.extend)
            enter=Event(paths); area.dragEnterEvent(enter); self.assertTrue(enter.accepted); self.assertFalse(area.overlay.isHidden())
            leave=Event([]); area.dragLeaveEvent(leave); self.assertTrue(area.overlay.isHidden())
            area.dragEnterEvent(Event(paths)); drop=Event(paths); area.dropEvent(drop); self.assertEqual(received,paths); self.assertTrue(area.overlay.isHidden())

    def test_analyze_uses_thread_without_blocking_caller(self):
        with tempfile.TemporaryDirectory() as folder:
            widget=self.widget(folder); widget.add_files([file(folder,"a.stl")])
            with patch("PySide6.QtCore.QThread.start") as start: widget.analyze()
            start.assert_called_once(); self.assertIsNotNone(widget.thread); widget.thread.deleteLater()

    def test_settings_persist_global_multiplier_and_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            store=InstallationSettingsStore(Path(folder)/"settings.json"); widget=PricingWidget(store); widget.global_multiplier.setValue(1.4); widget.options.visible_categories=["name","weight"]; widget.settings.price_visible_columns=widget.options.visible_categories; store.save(widget.settings)
            loaded=PricingWidget(store); self.assertAlmostEqual(loaded.options.global_multiplier,1.4); self.assertEqual(loaded.options.visible_categories,["name","weight"])


if __name__=="__main__": unittest.main()
