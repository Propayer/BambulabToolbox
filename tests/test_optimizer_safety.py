import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from shapely.geometry import box

from jarvis_bambu.bambu_session import BambuSession, WindowInfo
from jarvis_bambu.nesting_optimizer import NestingOptimizer, Placement
from jarvis_bambu.optimizer_models import ModelItem, OptimizerOptions, Plate


def item(object_id=1, plate=1):
    return ModelItem(object_id, str(object_id), plate, box(0, 0, 10, 10),
                     (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0), object())


class OptimizerSafetyTests(unittest.TestCase):
    def optimizer(self, mode="advanced"):
        optimizer = object.__new__(NestingOptimizer)
        optimizer.options = OptimizerOptions(mode, "low")
        optimizer.padding = optimizer.options.clearance_mm / 2
        optimizer.bed_padding = optimizer.padding
        optimizer.bed = box(0, 0, 100, 100)
        optimizer.safe_bed = optimizer.bed.buffer(-optimizer.bed_padding)
        return optimizer

    def test_invalid_bounds_are_rejected_before_save(self):
        optimizer = self.optimizer()
        model = item()
        placement = Placement(model, 1, 0, 95, 95, box(95, 95, 105, 105))
        with self.assertRaisesRegex(ValueError, "fuera de la plate"):
            optimizer._validate_assignments([[placement]])

    def test_spacing_is_mode_specific(self):
        self.assertEqual(OptimizerOptions("simple", "low").clearance_mm, 1.5)
        self.assertEqual(OptimizerOptions("advanced", "low").clearance_mm, 1.0)
        self.assertFalse(OptimizerOptions("simple", "low").allow_cross_plate_moves)
        self.assertTrue(OptimizerOptions("advanced", "low").remove_empty_plates)

    def test_fragmented_layout_scores_worse_than_clustered(self):
        optimizer = self.optimizer()
        models = [item(index) for index in range(1, 4)]
        clustered = [[
            Placement(models[0], 1, 0, 2, 2, box(2, 2, 12, 12)),
            Placement(models[1], 1, 0, 13, 2, box(13, 2, 23, 12)),
            Placement(models[2], 1, 0, 24, 2, box(24, 2, 34, 12)),
        ]]
        spread = [[
            Placement(models[0], 1, 0, 2, 2, box(2, 2, 12, 12)),
            Placement(models[1], 1, 0, 45, 45, box(45, 45, 55, 55)),
            Placement(models[2], 1, 0, 88, 88, box(88, 88, 98, 98)),
        ]]
        self.assertLess(optimizer._solution_score(clustered), optimizer._solution_score(spread))

    def test_preview_false_does_not_create_renderer(self):
        project = Mock()
        project.brim_extension = 0
        project.printable_area = box(0, 0, 100, 100)
        project.by_object = False
        project.plates.return_value = [Plate(1, False, object())]
        project.source = Path("source.3mf")
        with patch("jarvis_bambu.nesting_optimizer.ThreeMFProject", return_value=project), \
             patch("jarvis_bambu.nesting_optimizer.PreviewReporter") as reporter:
            result = NestingOptimizer(Path("source.3mf"), OptimizerOptions("advanced", "low")).optimize(
                Path("output.3mf")
            )
        self.assertFalse(result.improved)
        reporter.assert_not_called()

    def test_debug_reports_evaluated_attempts(self):
        optimizer = self.optimizer()
        optimizer.options = OptimizerOptions(
            "advanced", "low", preview=True, preview_mode="debug", debug_sequential=True
        )
        optimizer.started = __import__("time").monotonic()
        optimizer.deadline = optimizer.started + 5
        optimizer._rotation_cache = {}
        optimizer._raster_cache = {}
        optimizer.project = Mock()
        optimizer.project.brim_extension = 0
        reporter = Mock()
        solution = optimizer._search_advanced([item()], reporter)
        self.assertEqual(sum(map(len, solution)), 1)
        self.assertTrue(any(call.kwargs.get("debug") for call in reporter.update.call_args_list))
        partial_updates = [
            call for call in reporter.update.call_args_list
            if call.kwargs.get("progress", {}).get("placed") == 1
        ]
        self.assertTrue(partial_updates)
        self.assertIsNone(partial_updates[0].args[2])


class BambuSessionTests(unittest.TestCase):
    def session(self):
        return BambuSession(Path("BambuStudio.exe"), ".*Bambu Studio.*", Path("backup"), 1)

    def test_existing_window_is_reused(self):
        window = Mock(handle=123)
        info = WindowInfo(123, 42, "bambu-studio.exe", "project.3mf - Bambu Studio", True)
        session = self.session()
        with patch("jarvis_bambu.bambu_session.os.name", "nt"), \
             patch.object(session, "_find_bambu_window", return_value=(info, [info])), \
             patch.object(session, "_wrap_window", return_value=window), \
             patch.object(session, "_activate_window") as activate, \
             patch("jarvis_bambu.bambu_session.subprocess.Popen") as launch:
            self.assertIs(session.connect(), window)
        activate.assert_called_once()
        launch.assert_not_called()

    def test_missing_window_launches_and_waits(self):
        window = Mock(handle=456)
        info = WindowInfo(456, 84, "BambuStudio.exe", "Bambu Studio", True)
        session = self.session()
        with patch("jarvis_bambu.bambu_session.os.name", "nt"), \
             patch.object(session, "_find_executable", return_value=Path("BambuStudio.exe")), \
             patch.object(session, "_bambu_process_exists", return_value=False), \
             patch.object(session, "_find_bambu_window", side_effect=[(None, []), (info, [info])]), \
             patch.object(session, "_wrap_window", return_value=window), \
             patch.object(session, "_activate_window"), \
             patch("jarvis_bambu.bambu_session.subprocess.Popen") as launch, \
             patch("jarvis_bambu.bambu_session.time.sleep"):
            self.assertIs(session.connect(), window)
        launch.assert_called_once()

    def test_title_matching_is_case_insensitive_and_not_exact(self):
        for title in (
            "proyecto.3mf - Bambu Studio", "BAMBU STUDIO", "nombrearchivo - Bambu Studio"
        ):
            info = WindowInfo(1, 2, "bambu-studio.exe", title, True)
            self.assertTrue(BambuSession._is_bambu_window(info))

    def test_hidden_or_wrong_process_window_is_not_selected(self):
        self.assertFalse(BambuSession._is_bambu_window(
            WindowInfo(1, 2, "bambu-studio.exe", "Bambu Studio", False)
        ))
        self.assertFalse(BambuSession._is_bambu_window(
            WindowInfo(1, 2, "chrome.exe", "Bambu Studio documentation", True)
        ))
        self.assertFalse(BambuSession._is_bambu_window(
            WindowInfo(1, 2, "bambu-studio.exe", "Bambu Studio GUI initialization failed", True)
        ))


if __name__ == "__main__":
    unittest.main()
