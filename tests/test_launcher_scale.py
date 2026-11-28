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
        self.assertEqual(scale.cell_size(1.0), scale.COVER + 2 * scale.CARD_PAD)

    def test_the_same_formula_at_the_player_scales(self):
        for user in (1.0, 1.25, 1.5):
            cell = scale.cell_size(user)
            for width, expected in ((content, None) for content in (600, 1000, 1400)):
                count = scale.columns(width, user)
                self.assertTrue(1 <= count <= scale.MAX_COLUMNS)
                # the cards a row must actually fit the content width
                self.assertLessEqual(count * cell + (count - 1) * scale.gap(user), width)
                if count < scale.MAX_COLUMNS:
                    # one more card would not fit — the count is tight, not sparse
                    self.assertGreater((count + 1) * cell + count * scale.gap(user), width)

    def test_a_phone_sized_screen_shows_two_cards_at_most(self):
        for width in (320, 480, 600):
            self.assertLessEqual(scale.columns(width, 1.0, small=True), 2)

    def test_a_wide_screen_shows_more_cards(self):
        self.assertGreater(scale.columns(1200, 1.0, small=False), scale.columns(600, 1.0, small=False))

    def test_a_wide_window_stays_at_four_columns(self):
        """The grid the launcher wants: four a row at the most — a wider window
        shows margins, not a fifth column."""
        self.assertEqual(scale.columns(1400, 1.0), 4)
        self.assertEqual(scale.columns(2400, 1.0), 4)
        self.assertEqual(scale.columns(300, 1.0), 1)   # narrow: fewer, never zero

    def test_the_sizes_are_in_the_band_the_review_set(self):
        """Cover 112–128, card 144–152, gap 12–16 at scale 1."""
        self.assertTrue(112 <= scale.COVER <= 128)
        self.assertTrue(144 <= scale.cell_size(1.0) <= 152)
        self.assertTrue(12 <= scale.GAP <= 16)

    def test_the_grid_never_shows_no_card(self):
        self.assertGreaterEqual(scale.columns(1, 1.0, small=False), 1)
        self.assertGreaterEqual(scale.columns(1, 1.0, small=True), 1)


if __name__ == '__main__':
    unittest.main()
