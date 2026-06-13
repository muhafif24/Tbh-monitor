import os
import unittest
import tempfile

import src.database as db


class TestDatabase(unittest.TestCase):
    """All tests run against a fresh temporary SQLite file."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._orig_path = db._DB_PATH
        db._DB_PATH = self._tmp.name
        db.init_db()

    def tearDown(self):
        db._DB_PATH = self._orig_path
        os.unlink(self._tmp.name)

    # ── tracked_items ─────────────────────────────────────────────────────────

    def test_add_item_returns_true(self):
        self.assertTrue(db.add_item("Orb A"))

    def test_add_duplicate_returns_false(self):
        db.add_item("Orb A")
        self.assertFalse(db.add_item("Orb A"))

    def test_add_item_strips_whitespace(self):
        db.add_item("  Orb A  ")
        self.assertEqual(db.get_all_items()[0]["name"], "Orb A")

    def test_get_all_items_empty(self):
        self.assertEqual(db.get_all_items(), [])

    def test_get_all_items_order_by_id(self):
        db.add_item("B")
        db.add_item("A")
        names = [i["name"] for i in db.get_all_items()]
        self.assertEqual(names, ["B", "A"])

    def test_get_item_count(self):
        db.add_item("X")
        db.add_item("Y")
        self.assertEqual(db.get_item_count(), 2)

    def test_remove_item(self):
        db.add_item("Orb A")
        db.remove_item("Orb A")
        self.assertEqual(db.get_item_count(), 0)

    def test_remove_nonexistent_no_error(self):
        db.remove_item("Ghost")  # should not raise

    def test_update_item_metadata(self):
        db.add_item("Orb A")
        db.update_item_metadata("Orb A", "E8695A", "Orb - Lv.15", "http://img", "99999")
        item = db.get_all_items()[0]
        self.assertEqual(item["color_hex"], "E8695A")
        self.assertEqual(item["item_type"], "Orb - Lv.15")
        self.assertEqual(item["item_nameid"], "99999")
        self.assertEqual(item["image_url"], "http://img")

    def test_alert_price_default_none(self):
        db.add_item("Orb A")
        self.assertIsNone(db.get_alert_price("Orb A"))

    def test_get_alert_price_nonexistent_returns_none(self):
        self.assertIsNone(db.get_alert_price("Ghost"))

    def test_update_and_get_alert_price(self):
        db.add_item("Orb A")
        db.update_alert_price("Orb A", 50000.0)
        self.assertEqual(db.get_alert_price("Orb A"), 50000.0)

    def test_clear_alert_price(self):
        db.add_item("Orb A")
        db.update_alert_price("Orb A", 50000.0)
        db.update_alert_price("Orb A", None)
        self.assertIsNone(db.get_alert_price("Orb A"))

    # ── price_history ─────────────────────────────────────────────────────────

    def test_save_and_get_last_price(self):
        db.add_item("Orb A")
        db.save_price("Orb A", 15000.0)
        self.assertEqual(db.get_last_price("Orb A"), 15000.0)

    def test_get_last_price_returns_most_recent(self):
        db.add_item("Orb A")
        db.save_price("Orb A", 10000.0)
        db.save_price("Orb A", 25000.0)
        self.assertEqual(db.get_last_price("Orb A"), 25000.0)

    def test_get_last_price_no_history_returns_none(self):
        self.assertIsNone(db.get_last_price("Ghost"))

    def test_init_db_migration_idempotent(self):
        """Calling init_db() twice on existing DB must not raise."""
        db.init_db()
        db.init_db()


if __name__ == "__main__":
    unittest.main()
