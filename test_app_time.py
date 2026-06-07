import unittest

from app_time import BEIJING_TZ, beijing_timestamp


class AppTimeTest(unittest.TestCase):
    def test_beijing_timezone_is_fixed_to_utc_plus_eight(self):
        self.assertEqual(BEIJING_TZ.utcoffset(None).total_seconds(), 8 * 60 * 60)
        self.assertRegex(beijing_timestamp(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


if __name__ == "__main__":
    unittest.main()
