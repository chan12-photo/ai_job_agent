import unittest

from src.app import build_app, restock


class AppTests(unittest.TestCase):
    def test_port(self):
        self.assertEqual(build_app()["port"], 8421)

    def test_restock_format(self):
        self.assertEqual(restock(" ab-1 ", 5), "AB-1:5")


if __name__ == "__main__":
    unittest.main()
