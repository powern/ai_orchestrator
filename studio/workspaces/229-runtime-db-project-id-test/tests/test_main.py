import unittest
from app.main import main

class TestMain(unittest.TestCase):
    def test_main(self):
        self.assertEqual(main(), 'runtime db project id ok')

if __name__ == '__main__':
    unittest.main()