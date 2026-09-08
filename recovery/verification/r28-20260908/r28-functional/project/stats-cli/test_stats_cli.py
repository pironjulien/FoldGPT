import unittest

from stats_cli import calculate, main


class StatisticsTests(unittest.TestCase):
    def test_negative_numbers(self):
        self.assertEqual(calculate([-5, -2, -9]), {
            "count": 3, "min": -9, "max": -2, "sum": -16.0, "average": -16 / 3,
        })

    def test_decimals(self):
        result = calculate([1.5, 2.25, 3.25])
        self.assertEqual(result["count"], 3)
        self.assertAlmostEqual(result["sum"], 7.0)
        self.assertAlmostEqual(result["average"], 7 / 3)

    def test_empty_input(self):
        with self.assertRaises(ValueError):
            calculate([])

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            calculate([1, "not-a-number"])

    def test_cli_rejects_empty_input(self):
        self.assertEqual(main([]), 2)

    def test_cli_rejects_invalid_input(self):
        self.assertEqual(main(["1", "oops"]), 2)


if __name__ == "__main__":
    unittest.main()
