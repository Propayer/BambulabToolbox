import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jarvis_bambu.core.api import ProjectOptimizationResult, optimize_project
from jarvis_bambu.core.installation import InstallationSettingsStore
from jarvis_bambu.core.routing import RoutedRequest, route_request
from jarvis_bambu.gui.options import build_optimizer_options


class ApplicationFoundationTests(unittest.TestCase):
    def test_optimize_project_has_no_mqtt_dependency(self):
        engine_result = Mock(improved=False, message="ok", output=Path("out.3mf"),
                             original_plates=2, optimized_plates=2, generations=1)
        engine = Mock(); engine.optimize.return_value = engine_result
        engine.performance.as_dict.return_value = {"packing_seconds": 1}
        with patch("jarvis_bambu.core.api.NestingOptimizer", return_value=engine):
            result = optimize_project("input.3mf", build_optimizer_options(
                "Simple", "Rápido", False, "normal", "Auto"))
        self.assertTrue(result.ok); self.assertEqual(result.original_plate_count, 2)

    def test_mqtt_adapter_uses_shared_core(self):
        mqtt = Mock()
        with patch("jarvis_bambu.integrations.mqtt_optimizer.optimize_project") as core:
            from jarvis_bambu.integrations.mqtt_optimizer import optimize_project_from_mqtt
            optimize_project_from_mqtt(Path("a"), Path("b"), Mock(preview=False), mqtt)
        core.assert_called_once()

    def test_installation_id_and_values_persist(self):
        with tempfile.TemporaryDirectory() as folder:
            store = InstallationSettingsStore(Path(folder) / "settings.json")
            first = store.load(); first.display_name = "Taller"; first.owner = "Elmar"; store.save(first)
            second = store.load()
            self.assertEqual(second.device_id, first.device_id)
            self.assertEqual((second.display_name, second.owner), ("Taller", "Elmar"))

    def test_routing_rejects_wrong_target_and_accepts_local(self):
        handler = Mock(return_value="done")
        wrong = RoutedRequest("1", "remote", "other", "optimize")
        self.assertIsNone(route_request(wrong, "local", handler)); handler.assert_not_called()
        right = RoutedRequest("2", "remote", "local", "optimize")
        self.assertEqual(route_request(right, "local", handler), "done")

    def test_gui_options_map_to_engine_options(self):
        options = build_optimizer_options("Avanzado", "Medio", True, "debug", "4")
        self.assertEqual((options.mode, options.effort, options.optimizer_workers),
                         ("advanced", "medium", 4))
        self.assertTrue(options.preview); self.assertEqual(options.preview_mode, "debug")

    def test_gui_constructs_without_starting_optimization(self):
        from PySide6.QtWidgets import QApplication
        from jarvis_bambu.gui.app import MainWindow, OptimizerWidget
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            window = MainWindow(InstallationSettingsStore(Path(folder) / "settings.json"))
            optimizer = next(widget for widget in window.findChildren(OptimizerWidget))
            self.assertIsNone(optimizer.thread)
            self.assertGreaterEqual(window.stack.count(), 6)
            window.close()

    def test_result_fields_are_structured_for_gui(self):
        result = ProjectOptimizationResult(True, True, "done", Path("a"), Path("b"),
                                           4, 3, (3,), 1.2)
        self.assertEqual((result.final_plate_count, result.message), (3, "done"))

    def test_optimizer_starts_work_on_qthread(self):
        from PySide6.QtWidgets import QApplication
        from jarvis_bambu.gui.app import OptimizerWidget
        app = QApplication.instance() or QApplication([])
        widget = OptimizerWidget()
        with patch("PySide6.QtCore.QThread.start") as start:
            widget.start()
        start.assert_called_once()
        self.assertIsNotNone(widget.thread)
        widget.thread.deleteLater(); widget.close()

    def test_result_is_rendered_by_optimizer_widget(self):
        from PySide6.QtWidgets import QApplication
        from jarvis_bambu.gui.app import OptimizerWidget
        app = QApplication.instance() or QApplication([])
        widget = OptimizerWidget()
        result = ProjectOptimizationResult(True, True, "done", Path("a"), Path("b"),
                                           4, 3, (3,), 1.2)
        with patch("jarvis_bambu.gui.app.QMessageBox.information"):
            widget.done(result)
        self.assertIn("4 → 3", widget.status.text())
        self.assertTrue(widget.open_button.isVisibleTo(widget))
        widget.close()


if __name__ == "__main__":
    unittest.main()
