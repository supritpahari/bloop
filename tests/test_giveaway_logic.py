import unittest
from unittest.mock import patch

from cogs.giveaway import Giveaway, parse_duration


class GiveawayLogicTests(unittest.TestCase):
    def test_duration_parser(self):
        self.assertEqual(parse_duration("1d12h30m"), 131400)
        self.assertEqual(parse_duration("45s"), 45)
        for invalid in ("", "tomorrow", "5", "5s", "999w"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_duration(invalid)

    def test_weighted_draw_without_replacement(self):
        with patch("cogs.giveaway.secrets.randbelow", side_effect=[1, 0]):
            winners = Giveaway.choose_winners([(10, 1), (20, 3), (30, 1)], 2)
        self.assertEqual(winners, [20, 10])
        self.assertEqual(len(set(winners)), 2)

    def test_not_enough_participants_is_handled(self):
        with patch("cogs.giveaway.secrets.randbelow", return_value=0):
            self.assertEqual(Giveaway.choose_winners([(10, 1)], 3), [10])
            self.assertEqual(Giveaway.choose_winners([], 3), [])

    def test_duplicate_winners_only_when_explicitly_enabled(self):
        with patch("cogs.giveaway.secrets.randbelow", return_value=0):
            self.assertEqual(Giveaway.choose_winners([(10, 1)], 3, allow_duplicates=True), [10, 10, 10])


if __name__ == "__main__":
    unittest.main()
