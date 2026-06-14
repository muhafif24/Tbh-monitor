import threading
import unittest
from unittest.mock import MagicMock, patch

from src.worker import seconds_until_next_hour, PriceWorker, ListingWorker


class TestSecondsUntilNextHour(unittest.TestCase):

    def test_returns_positive(self):
        self.assertGreater(seconds_until_next_hour(), 0)

    def test_at_most_one_hour(self):
        self.assertLessEqual(seconds_until_next_hour(), 3600)

    def test_minimum_one_second(self):
        self.assertGreaterEqual(seconds_until_next_hour(), 1.0)

    def test_consistent_calls(self):
        # Two consecutive calls should return similar values (within 1s)
        a = seconds_until_next_hour()
        b = seconds_until_next_hour()
        self.assertAlmostEqual(a, b, delta=1.0)


class TestWorkerCreation(unittest.TestCase):

    def setUp(self):
        self._stop = threading.Event()

    def test_price_worker_is_daemon(self):
        w = PriceWorker(["item1", "item2"], lambda n, r: None, self._stop)
        self.assertTrue(w.daemon)

    def test_price_worker_empty_items(self):
        w = PriceWorker([], lambda n, r: None, self._stop)
        self.assertIsInstance(w, PriceWorker)

    def test_listing_worker_is_daemon(self):
        w = ListingWorker(["item1"], lambda *a: None, self._stop)
        self.assertTrue(w.daemon)

    def test_listing_worker_no_fetch_metadata_param(self):
        # fetch_metadata was removed; catalog now provides color/type/icon
        w = ListingWorker(["item1"], lambda *a: None, self._stop)
        self.assertFalse(hasattr(w, "_fetch_metadata"))

    def test_price_worker_stops_immediately_on_set_event(self):
        """Worker should exit its run() without making any requests if stop_event is set."""
        self._stop.set()
        called = []
        w = PriceWorker(["item1"], lambda n, r: called.append(n), self._stop)
        w.start()
        w.join(timeout=3)
        self.assertFalse(w.is_alive())
        self.assertEqual(called, [])


class TestListingWorkerCache(unittest.TestCase):

    def setUp(self):
        self._stop = threading.Event()

    @patch("src.worker.get_market_history_cache")
    @patch("src.worker.get_cached_image")
    @patch("src.worker.SteamMarketAPI")
    def test_uses_cache_when_history_and_image_exist(self, mock_api_class, mock_get_image, mock_get_history):
        # Setup mock API
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api
        mock_api.get_orderbook.return_value = {
            "highest_buy": 10.0, "buy_count": 5, "currency": 1
        }
        
        # Fresh history exists
        from datetime import datetime
        mock_get_history.return_value = {
            "history": [["date", 10.0, 5]],
            "updated_at": datetime.now().isoformat()
        }
        
        # Image is cached
        mock_get_image.return_value = b"image_data"
        
        called = []
        def on_update(*args):
            called.append(args)
            
        w = ListingWorker(["item1"], on_update, self._stop)
        w.run()
        
        # Should NOT call get_listing_data
        mock_api.get_listing_data.assert_not_called()
        # Should call get_orderbook
        mock_api.get_orderbook.assert_called_once_with("item1")
        self.assertEqual(len(called), 1)

    @patch("src.worker.get_market_history_cache")
    @patch("src.worker.get_cached_image")
    @patch("src.worker.SteamMarketAPI")
    def test_bypasses_cache_when_image_is_missing(self, mock_api_class, mock_get_image, mock_get_history):
        # Setup mock API
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api
        mock_api.get_orderbook.return_value = {
            "highest_buy": 10.0, "buy_count": 5, "currency": 1
        }
        mock_api.get_listing_data.return_value = {
            "history": [["date", 10.0, 5]],
            "image_url": "http://image",
            "name_color": "ffffff",
            "item_type": "type"
        }
        
        # Fresh history exists
        from datetime import datetime
        mock_get_history.return_value = {
            "history": [["date", 10.0, 5]],
            "updated_at": datetime.now().isoformat()
        }
        
        # Image is NOT cached (returns None)
        mock_get_image.return_value = None
        
        called = []
        def on_update(*args):
            called.append(args)
            
        w = ListingWorker(["item1"], on_update, self._stop)
        w.run()
        
        # Should call get_listing_data because image is missing
        mock_api.get_listing_data.assert_called_once_with("item1")
        # Should call get_orderbook
        mock_api.get_orderbook.assert_called_once_with("item1")
        self.assertEqual(len(called), 1)


if __name__ == "__main__":
    unittest.main()

