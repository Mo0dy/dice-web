import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import webbridge


class WebBridgeTest(unittest.TestCase):
    def test_evaluate_returns_structured_distribution(self):
        payload = webbridge.evaluate("d6", settings={"roundlevel": 4})
        self.assertTrue(payload["ok"])
        self.assertIn("1: 16.6667%", payload["text"])
        self.assertIn("(E): 3.5000", payload["text"])
        self.assertEqual(payload["result"]["type"], "distributions")
        self.assertEqual(payload["result"]["axes"], [])
        probabilities = [entry["probability"] for entry in payload["result"]["cells"][0]["distribution"]]
        self.assertEqual(probabilities, [round(1 / 6, 4)] * 6)

    def test_evaluate_returns_structured_error(self):
        payload = webbridge.evaluate("1 / 0")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["title"], "error")
        self.assertIn("divide by zero", payload["error"]["message"])
        self.assertIsNotNone(payload["error"]["span"])

    def test_evaluate_includes_runtime_scalar_sweep_render_payload(self):
        payload = webbridge.evaluate("[ac:10, 11, 12] + 0")
        self.assertTrue(payload["ok"])
        render = payload["render"]
        self.assertEqual(render["kind"], "scalar_sweep")
        self.assertEqual(render["payload"]["axes"][0]["values"], [10, 11, 12])
        cell_values = [cell["distribution"][0]["outcome"] for cell in render["payload"]["cells"]]
        self.assertEqual(cell_values, [10, 11, 12])

    def test_evaluate_includes_runtime_distribution_sweep_render_payload(self):
        payload = webbridge.evaluate("d20 >= [ac:18, 19, 20]")
        self.assertTrue(payload["ok"])
        render = payload["render"]
        self.assertEqual(render["kind"], "distribution_sweep")
        self.assertEqual(render["payload"]["axes"][0]["values"], [18, 19, 20])
        success_probabilities = [
            next(entry["probability"] for entry in cell["distribution"] if entry["outcome"] == 1)
            for cell in render["payload"]["cells"]
        ]
        self.assertEqual(len(success_probabilities), 3)
        self.assertAlmostEqual(success_probabilities[0], 15.0)
        self.assertAlmostEqual(success_probabilities[1], 10.0)
        self.assertAlmostEqual(success_probabilities[2], 5.0)

    def test_render_statements_use_percent_probabilities(self):
        payload = webbridge.evaluate('r_dist(d2, x="Outcome"); render()')
        self.assertTrue(payload["ok"])
        report = payload["reports"][0]["report"]
        panel = report["rows"][0][0]
        self.assertEqual(panel["x_label"], "Outcome")
        self.assertEqual(
            panel["payload"]["cells"][0]["distribution"],
            [
                {"outcome": 1, "probability": 50.0},
                {"outcome": 2, "probability": 50.0},
            ],
        )

    def test_list_symbols_exposes_builtins_and_stdlib(self):
        symbols = webbridge.list_symbols()
        builtin_names = {entry["name"] for entry in symbols["builtins"]}
        self.assertIn("mean", builtin_names)
        self.assertIn("render", builtin_names)
        self.assertIn("import", symbols["keywords"])
        self.assertIn("std:dnd/core", symbols["stdlib_imports"])

    def test_complete_includes_local_and_imported_names(self):
        payload = webbridge.complete(
            'import "helpers"; attack_bonus = 5;\n',
            len('import "helpers"; attack_bonus = 5;\n'),
            files={"helpers.dice": "weapon_damage = d8"},
        )
        labels = {option["label"] for option in payload["options"]}
        self.assertIn("attack_bonus", labels)
        self.assertIn("weapon_damage", labels)

    def test_complete_replaces_identifier_suffix_when_cursor_is_mid_token(self):
        source = "fireball = 1\nfirebax"
        payload = webbridge.complete(source, len("fireball = 1\nfireba"))
        labels = {option["label"] for option in payload["options"]}
        self.assertIn("fireball", labels)
        self.assertEqual(payload["from"], len("fireball = 1\n"))
        self.assertEqual(payload["to"], len(source))

    def test_complete_includes_defined_function_names(self):
        source = "attack(ac): d20 >= ac\natt"
        payload = webbridge.complete(source, len(source))
        labels = {option["label"] for option in payload["options"]}
        self.assertIn("attack", labels)

    def test_complete_suggests_stdlib_import_paths(self):
        payload = webbridge.complete('import "std:dnd/', len('import "std:dnd/'))
        labels = {option["label"] for option in payload["options"]}
        self.assertIn("std:dnd/core", labels)

    def test_evaluate_supports_browser_side_imports(self):
        payload = webbridge.evaluate(
            'import "helpers"; weapon_damage + 2',
            files={"helpers.dice": "weapon_damage = d6"},
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["type"], "distributions")

    def test_list_samples_exposes_runnable_dice_samples(self):
        samples = webbridge.list_samples()
        paths = {sample["path"] for sample in samples}
        self.assertIn("00_basic/00_introduction.dice", paths)
        self.assertIn("01_dnd/ability_scores_4d6h3.dice", paths)
        self.assertIn("02_python_extensions/00_import_python_library.dice", paths)
        self.assertIn("std:dnd/core", paths)
        self.assertNotIn("02_python_extensions/basic_library.py", paths)

    def test_list_samples_preserves_example_folder_then_file_order(self):
        samples = [sample["path"] for sample in webbridge.list_samples() if sample["kind"] == "sample"]
        self.assertGreaterEqual(len(samples), 3)
        self.assertEqual(samples[0], "00_basic/00_introduction.dice")
        self.assertEqual(samples[1], "00_basic/01_sweeps.dice")
        self.assertEqual(samples[2], "00_basic/02_sweeps_advanced.dice")

    def test_load_sample_returns_workspace_package(self):
        sample = webbridge.load_sample("01_dnd/combat_profiles.dice")
        self.assertEqual(sample["source_path"], "01_dnd/combat_profiles.dice")
        self.assertIn("01_dnd/ability_scores_4d6h3.dice", sample["files"])
        self.assertIn('import "std:dnd/weapons.dice"', sample["source"])

    def test_load_sweep_sample_returns_workspace_package(self):
        sample = webbridge.load_sample("00_basic/06_indexing_basics.dice")
        self.assertEqual(sample["source_path"], "00_basic/06_indexing_basics.dice")
        self.assertIn("00_basic/07_adaptive_best_choice.dice", sample["files"])
        self.assertIn("study[focus", sample["source"])

    def test_load_python_extension_sample_includes_sidecar_python_files(self):
        sample = webbridge.load_sample("02_python_extensions/00_import_python_library.dice")
        self.assertEqual(sample["source_path"], "02_python_extensions/00_import_python_library.dice")
        self.assertIn("02_python_extensions/basic_library.py", sample["files"])
        self.assertIn('import "basic_library.py"', sample["source"])

    def test_load_stdlib_returns_workspace_package(self):
        sample = webbridge.load_sample("std:dnd/spells")
        self.assertEqual(sample["source_path"], "dnd/spells.dice")
        self.assertIn("dnd/core.dice", sample["files"])
        self.assertIn('import "std:dnd/core.dice"', sample["source"])

    def test_all_runnable_samples_evaluate(self):
        samples = webbridge.list_samples()
        self.assertTrue(samples, "expected bundled samples")
        for sample_info in samples:
            with self.subTest(sample=sample_info["path"]):
                sample = webbridge.load_sample(sample_info["path"])
                payload = webbridge.evaluate(
                    sample["source"],
                    files=sample["files"],
                    settings={"source_path": sample["source_path"]},
                )
                self.assertTrue(payload["ok"], payload.get("error"))

    def test_render_statements_are_captured_as_browser_payloads(self):
        sample = webbridge.load_sample("01_dnd/ability_scores_4d6h3.dice")
        payload = webbridge.evaluate(
            sample["source"],
            files=sample["files"],
            settings={"source_path": sample["source_path"]},
        )
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(payload["text"], "Rendered 5 plot(s).")
        self.assertEqual(len(payload["reports"]), 1)
        report = payload["reports"][0]["report"]
        self.assertEqual(report["title"], "4d6 drop lowest ability scores")
        self.assertEqual(len(report["rows"]), 3)
        self.assertEqual(report["rows"][0][0]["title"], "Single ability score distribution")

    def test_direct_results_use_runtime_auto_chart_plans_for_fallback_rendering(self):
        payload = webbridge.evaluate(
            "attack_roll = d20 + 5\n"
            "hit_check = attack_roll >= 15\n"
            "weapon_damage = 2 d 6 + 4\n"
            "hit_check -> weapon_damage | 0\n"
        )
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(payload["reports"], [])
        self.assertIsNotNone(payload["render"])
        self.assertEqual(payload["render"]["kind"], "unswept_distribution")
        omit_hints = [hint for hint in payload["render"]["hints"] if hint["kind"] == "omit_outcome"]
        self.assertEqual(len(omit_hints), 1)
        self.assertEqual(omit_hints[0]["outcome"], 0)


if __name__ == "__main__":
    unittest.main()
