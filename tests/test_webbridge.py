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

    def test_render_payload_builds_line_chart_data(self):
        payload = webbridge.evaluate("[ac:10, 11, 12] + 0")
        self.assertTrue(payload["ok"])
        render = webbridge.render_payload(payload, settings={"probability_mode": "percent"})
        self.assertEqual(render["kind"], "line")
        self.assertEqual(render["categories"], [10, 11, 12])
        self.assertEqual(render["series"][0]["values"], [10, 11, 12])

    def test_render_payload_uses_mean_for_bernoulli_sweeps(self):
        payload = webbridge.evaluate("d20 >= [ac:18, 19, 20]")
        self.assertTrue(payload["ok"])
        render = webbridge.render_payload(payload, settings={"probability_mode": "percent"})
        self.assertEqual(render["kind"], "line")
        self.assertEqual(render["spec"]["y_label"], "Probability (%)")
        self.assertEqual(render["categories"], [18, 19, 20])
        self.assertEqual(render["series"][0]["values"], [15.0, 10.0, 5.0])

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
        self.assertIn("dnd/ability_scores_4d6h3.dice", paths)
        self.assertIn("dnd/combat_profiles.dice", paths)
        self.assertIn("sweeps/indexing_basics.dice", paths)
        self.assertIn("std:dnd/core", paths)
        self.assertNotIn("dnd/lib/weapons.dice", paths)

    def test_load_sample_returns_workspace_package(self):
        sample = webbridge.load_sample("dnd/combat_profiles.dice")
        self.assertEqual(sample["source_path"], "dnd/combat_profiles.dice")
        self.assertIn("dnd/ability_scores_4d6h3.dice", sample["files"])
        self.assertIn('import "std:dnd/weapons.dice"', sample["source"])

    def test_load_sweep_sample_returns_workspace_package(self):
        sample = webbridge.load_sample("sweeps/indexing_basics.dice")
        self.assertEqual(sample["source_path"], "sweeps/indexing_basics.dice")
        self.assertIn("sweeps/adaptive_best_choice.dice", sample["files"])
        self.assertIn("study[focus", sample["source"])

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
        sample = webbridge.load_sample("dnd/ability_scores_4d6h3.dice")
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


if __name__ == "__main__":
    unittest.main()
