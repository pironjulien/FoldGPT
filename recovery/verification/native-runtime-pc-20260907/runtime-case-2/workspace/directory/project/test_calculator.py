import unittest
from calculator import add, answer
class CalculatorTests(unittest.TestCase):
    def test_edited_answer(self):
        self.assertEqual(answer(), 42)
    def test_signed_addition(self):
        self.assertEqual(add(-13, 55), 42)
    def test_invalid_operand(self):
        with self.assertRaises(TypeError):
            add(1, None)
