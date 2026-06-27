import unittest
from app.main import main

class TestMain(unittest.TestCase):
    def test_main(self):
        self.assertEqual(main(), "final executor json ok")

if __name__ == '__main__':
    unittest.main()