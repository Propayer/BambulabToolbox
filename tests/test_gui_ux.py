import os, unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from jarvis_bambu.core.api import ProjectOptimizationResult
from jarvis_bambu.gui.app import OptimizerWidget
from jarvis_bambu.gui.components import HelpButton
from jarvis_bambu.gui.guide import GuideWidget, HelpPanel
from jarvis_bambu.gui.help_content import HELP, search_help
from jarvis_bambu.gui.options import effort_deadline_seconds
from jarvis_bambu.gui.timing import format_duration, human_duration, remaining_display

class GuiUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def test_real_effort_deadlines_and_formatting(self):
        self.assertEqual(effort_deadline_seconds("Rápido"),60)
        self.assertEqual(effort_deadline_seconds("Medio"),180)
        self.assertIsNone(effort_deadline_seconds("Alto"))
        self.assertEqual(format_duration(185),"03:05"); self.assertEqual(human_duration(180),"3 min")
    def test_remaining_never_negative_and_finishing_state(self):
        self.assertEqual(remaining_display(181,180),"Finalizando...")
        self.assertEqual(remaining_display(20,10),"Finalizando...")
    def test_help_definitions_cover_controls_and_are_shared(self):
        for help_id in ("optimizer.mode","optimizer.effort","optimizer.preview","optimizer.preview_mode","optimizer.workers"):
            self.assertIn(help_id,HELP)
            button=HelpButton(help_id); self.assertEqual(button.toolTip(),HELP[help_id].short_description)
            panel=HelpPanel(); button.helpRequested.connect(panel.show_help); button.click()
            self.assertIn(HELP[help_id].title,panel.title.text())
    def test_guide_search_filters_same_definitions(self):
        self.assertIn(HELP["optimizer.workers"],search_help("procesos"))
        guide=GuideWidget(); guide.search.setText("deadline")
        self.assertTrue(any(item.id=="optimizer.effort" for item in guide.filtered))
    def test_controls_update_summary_and_preview_dependency(self):
        widget=OptimizerWidget(); widget.advanced_button.click(); self.assertIn("Avanzado",widget.summary.text())
        widget.effort.setCurrentIndex(1); self.assertIn("3 min",widget.effort_description.text())
        self.assertFalse(widget.preview_mode.isEnabled()); widget.preview.setChecked(True)
        self.assertTrue(widget.preview_mode.isEnabled()); self.assertIn("Normal",widget.summary.text())
    def test_timer_uses_monotonic_without_events_and_stops(self):
        widget=OptimizerWidget(); widget.started_at=100; widget.deadline_seconds=60
        with patch("jarvis_bambu.gui.app.time.monotonic",return_value=142): widget.update_clock()
        self.assertEqual(widget.elapsed_label.text(),"00:42"); self.assertEqual(widget.remaining_label.text(),"00:18")
        widget.timer.start(); result=ProjectOptimizationResult(True,False,"done",Path("a"),None,2,2,None,43)
        widget.done(result); self.assertFalse(widget.timer.isActive()); self.assertTrue(widget.button.isEnabled())
        self.assertEqual(widget.time_progress.value(),1000); self.assertEqual(widget.remaining_label.text(),"Completado")
        self.assertTrue(widget.result_card.isVisibleTo(widget)); self.assertFalse(widget.open_button.isVisibleTo(widget))

if __name__=="__main__": unittest.main()
