import unittest

from openberth.selection import SelectionModel


class SelectionModelTests(unittest.TestCase):
    def test_single_click(self) -> None:
        model = SelectionModel()
        self.assertEqual(model.single_click(10, 0), {10})

    def test_ctrl_toggle(self) -> None:
        model = SelectionModel()
        model.single_click(1, 0)
        self.assertEqual(model.ctrl_click(2, 1), {1, 2})
        self.assertEqual(model.ctrl_click(1, 0), {2})

    def test_shift_range(self) -> None:
        model = SelectionModel()
        ids = [11, 12, 13, 14]
        model.single_click(12, 1)
        self.assertEqual(model.shift_click(ids, 3), {12, 13, 14})


if __name__ == "__main__":
    unittest.main()

