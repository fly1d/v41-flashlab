import unittest

from scripts.make_long_context_suite import build_suite


class LongContextGeneratorTests(unittest.TestCase):
    def test_seeded_suite_is_reproducible_and_varied(self) -> None:
        first = build_suite(1_000, case_count=3, seed=7)
        repeated = build_suite(1_000, case_count=3, seed=7)
        changed = build_suite(1_000, case_count=3, seed=8)

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, changed)
        self.assertEqual(len(first["cases"]), 3)
        self.assertEqual(len({case["expect"]["value"] for case in first["cases"]}), 3)

    def test_reserves_context_headroom_and_records_positions(self) -> None:
        suite = build_suite(32_000, case_count=1, seed=11)
        metadata = suite["metadata"]
        case = suite["cases"][0]

        self.assertLess(metadata["approx_document_tokens"], 32_000)
        self.assertGreaterEqual(metadata["reserved_headroom_tokens"], 256)
        self.assertEqual(case["metadata"]["context_band"], "<=32k")
        self.assertEqual(len(case["metadata"]["needle_positions"]), 3)
        self.assertEqual(case["messages"][1]["content"].count("CONTROL FACT"), 3)

    def test_rejects_out_of_range_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "approx_tokens"):
            build_suite(999)
        with self.assertRaisesRegex(ValueError, "case_count"):
            build_suite(1_000, case_count=0)


if __name__ == "__main__":
    unittest.main()
