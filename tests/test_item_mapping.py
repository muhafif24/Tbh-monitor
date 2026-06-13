import unittest
from unittest.mock import patch

from src.item_mapping import build_market_to_keys, owned_by_market_name, _GEAR_NAME_RE

_FAKE_GAME_ITEMS = [
    {"id": 141001, "name": {"en-US": "Bronze Ingot"},  "grade": "UNCOMMON",  "type": "MATERIAL"},
    {"id": 190001, "name": {"en-US": "Soulstone - Normal"}, "grade": "IMMORTAL", "type": "MATERIAL"},
    {"id": 424041, "name": {"en-US": "Frozen Orb"},    "grade": "IMMORTAL",  "type": "GEAR"},
    {"id": 424042, "name": {"en-US": "Frozen Orb"},    "grade": "IMMORTAL",  "type": "GEAR"},
    {"id": 428141, "name": {"en-US": "Ancient Orb"},   "grade": "DIVINE",    "type": "GEAR"},
    {"id": 428142, "name": {"en-US": "Ancient Orb"},   "grade": "DIVINE",    "type": "GEAR"},
    {"id": 910011, "name": None,                       "grade": "COMMON",    "type": "STAGEBOX"},
]


class TestGearNameRegex(unittest.TestCase):

    def test_matches_all_grades(self):
        for grade in ("Common", "Uncommon", "Rare", "Legendary", "Immortal",
                      "Arcana", "Beyond", "Celestial", "Divine", "Cosmic"):
            m = _GEAR_NAME_RE.match(f"Frozen Orb ({grade}) A")
            self.assertIsNotNone(m, f"grade {grade} should match")
            self.assertEqual(m.group("grade"), grade)

    def test_material_name_does_not_match(self):
        self.assertIsNone(_GEAR_NAME_RE.match("Soulstone - Normal"))
        self.assertIsNone(_GEAR_NAME_RE.match("Bronze Ingot"))

    def test_variant_extracted(self):
        m = _GEAR_NAME_RE.match("Frozen Orb (Immortal) B")
        self.assertEqual(m.group("var"), "B")


@patch("src.item_mapping.get_game_items", return_value=_FAKE_GAME_ITEMS)
class TestBuildMarketToKeys(unittest.TestCase):

    def test_material_direct_name(self, _mock):
        result = build_market_to_keys(["Bronze Ingot"])
        self.assertEqual(result["Bronze Ingot"], [141001])

    def test_gear_variant_a_is_lower_id(self, _mock):
        result = build_market_to_keys(["Frozen Orb (Immortal) A", "Frozen Orb (Immortal) B"])
        self.assertEqual(result["Frozen Orb (Immortal) A"], [424041])
        self.assertEqual(result["Frozen Orb (Immortal) B"], [424042])

    def test_divine_grade_matches(self, _mock):
        result = build_market_to_keys(["Ancient Orb (Divine) A"])
        self.assertEqual(result["Ancient Orb (Divine) A"], [428141])

    def test_unknown_name_omitted(self, _mock):
        result = build_market_to_keys(["Item Tidak Ada"])
        self.assertNotIn("Item Tidak Ada", result)


@patch("src.item_mapping.get_game_items", return_value=_FAKE_GAME_ITEMS)
class TestOwnedByMarketName(unittest.TestCase):

    def test_combines_counts(self, _mock):
        owned = owned_by_market_name(
            ["Soulstone - Normal", "Frozen Orb (Immortal) A", "Bronze Ingot"],
            {190001: 10, 424041: 1},
        )
        self.assertEqual(owned, {"Soulstone - Normal": 10, "Frozen Orb (Immortal) A": 1})

    def test_zero_owned_excluded(self, _mock):
        owned = owned_by_market_name(["Bronze Ingot"], {190001: 5})
        self.assertEqual(owned, {})


if __name__ == "__main__":
    unittest.main()
