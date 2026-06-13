import threading
import unittest

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


if __name__ == "__main__":
    unittest.main()
