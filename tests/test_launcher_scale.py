"""The scale: GTK draws the fonts, what is left for us is the player's own multiplier
and the rule that a phone-sized screen never shows more than two cards."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher import scale   # noqa: E402


class Scale(unittest.TestCase):
    def test_a_phone_sized_screen_is_a_small_one(self):
        self.assertTrue(scale.is_small(480))
        self.assertTrue(scale.is_small(600))
        self.assertFalse(scale.is_small(601))
        self.assertFalse(scale.is_small(1080))

    def test_the_player_own_multiplier_counts(self):
        self.assertAlmostEqual(scale.user_scale(1.5), 1.5)
        self.assertAlmostEqual(scale.user_scale(2.0), 2.0)

    def test_a_broken_multiplier_is_ignored(self):
        self.assertAlmostEqual(scale.user_scale(0), 1.0)
        self.assertAlmostEqual(scale.user_scale('x'), 1.0)
        self.assertAlmostEqual(scale.user_scale(None), 1.0)

    def test_a_card_grows_with_the_scale(self):
        self.assertGreater(scale.cell_size(1.5), scale.cell_size(1.0))
        self.assertGreaterEqual(scale.cell_size(0.1), 80)

    def test_a_phone_sized_screen_shows_two_cards_at_most(self):
        for width in (320, 480, 600):
            self.assertLessEqual(scale.columns(width, 1.0, small=True), 2)

    def test_a_wide_screen_shows_more_cards(self):
        self.assertGreater(scale.columns(1200, 1.0, small=False), scale.columns(600, 1.0, small=False))

    def test_the_grid_never_shows_no_card(self):
        self.assertGreaterEqual(scale.columns(1, 1.0, small=False), 1)
        self.assertGreaterEqual(scale.columns(1, 1.0, small=True), 1)


if __name__ == '__main__':
    unittest.main()
