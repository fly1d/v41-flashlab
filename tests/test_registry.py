import json
import tempfile
import unittest
from pathlib import Path

from v41flash_eval.registry import RegistryFormatError, validate_registry


class RegistryTests(unittest.TestCase):
    def test_repository_registry_matches_suites(self) -> None:
        root = Path(__file__).parents[1]
        result = validate_registry(root / "benchmarks" / "registry.json")
        self.assertEqual(result["suite_count"], 2)
        self.assertEqual({item["samples"] for item in result["suites"]}, {3, 12})

    def test_rejects_sample_count_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            benchmark_dir = root / "benchmarks"
            benchmark_dir.mkdir()
            suite = {
                "schema_version": "v41-flashlab.suite.v1",
                "version": "1.0.0",
                "name": "demo",
                "metadata": {
                    "version": "1.0.0",
                    "language": "en",
                    "provenance": "synthetic",
                    "license": "MIT",
                },
                "cases": [
                    {
                        "id": "one",
                        "metadata": {"track": "reasoning"},
                        "messages": [{"role": "user", "content": "x"}],
                    }
                ],
            }
            (benchmark_dir / "demo.json").write_text(
                json.dumps(suite), encoding="utf-8"
            )
            registry = {
                "schema_version": "v41flash.registry.v1",
                "suites": [
                    {
                        "id": "demo",
                        "path": "benchmarks/demo.json",
                        "version": "1.0.0",
                        "sample_count": 2,
                        "languages": ["en"],
                        "tracks": ["reasoning"],
                        "provenance": "synthetic",
                        "license": "MIT",
                        "default_epochs": 1,
                    }
                ],
            }
            registry_path = benchmark_dir / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaisesRegex(RegistryFormatError, "does not match 1 cases"):
                validate_registry(registry_path)


if __name__ == "__main__":
    unittest.main()
