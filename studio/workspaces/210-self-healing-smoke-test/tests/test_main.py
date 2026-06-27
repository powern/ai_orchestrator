
import unittest
from app import main

class TestMain(unittest.TestCase):
    def test_main(self):
        self.assertEqual(main(), "self healing ok")

if __name__ == '__main__':
    unittest.main()
