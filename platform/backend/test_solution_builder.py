import unittest

from solution_builder import TEMPLATES, validate_solution


class SolutionValidationTests(unittest.TestCase):
    def test_registered_templates_validate(self):
        for template in TEMPLATES.values():
            with self.subTest(template=template.id):
                self.assertTrue(validate_solution(template.to_dict())["valid"])

    def test_malformed_graph_returns_schema_errors(self):
        for field in ("nodes", "edges"):
            for value in (None, "bad", {}, [None], ["bad"]):
                with self.subTest(field=field, value=value):
                    result = validate_solution({field: value})
                    self.assertFalse(result["valid"])
                    self.assertEqual(result["errors"][0]["kind"], "schema")

    def test_implicit_conversion_is_refused(self):
        result = validate_solution({
            "nodes": [{"id": "draft", "capability": "relay.handoff"},
                      {"id": "commit", "capability": "runtime.stabilize"}],
            "edges": [{"source": "draft", "source_port": "draft",
                       "target": "commit", "target_port": "artifact"}],
        })
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["kind"], "type")

    def test_duplicate_and_unknown_nodes_are_refused(self):
        for node in ({"id": "a", "capability": "osahr.model"},
                     {"id": "b", "capability": "missing"}):
            result = validate_solution({"nodes": [
                {"id": "a", "capability": "osahr.model"}, node]})
            self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
