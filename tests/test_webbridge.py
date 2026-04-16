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


if __name__ == "__main__":
    unittest.main()
