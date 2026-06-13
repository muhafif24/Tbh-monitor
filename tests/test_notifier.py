import os
import unittest

from src.notifier import send_alert


class TestNotifier(unittest.TestCase):

    def _clear_env(self):
        return os.environ.pop("DISCORD_WEBHOOK_URL", None)

    def _restore_env(self, value):
        if value is not None:
            os.environ["DISCORD_WEBHOOK_URL"] = value

    def test_no_url_does_not_raise(self):
        """send_alert must silently skip when DISCORD_WEBHOOK_URL is not set."""
        saved = self._clear_env()
        try:
            send_alert("Test Item", 15000.0, 20000.0)
        finally:
            self._restore_env(saved)

    def test_invalid_url_does_not_raise(self):
        """send_alert must log a warning but never propagate exceptions."""
        saved = self._clear_env()
        os.environ["DISCORD_WEBHOOK_URL"] = "http://localhost:1/nonexistent"
        try:
            send_alert("Test Item", 15000.0, 20000.0)
        finally:
            del os.environ["DISCORD_WEBHOOK_URL"]
            self._restore_env(saved)

    def test_send_alert_with_zero_price(self):
        """Edge case: price of 0 should not cause arithmetic errors."""
        saved = self._clear_env()
        try:
            send_alert("Test Item", 0.0, 5000.0)
        finally:
            self._restore_env(saved)

    def test_send_alert_large_values(self):
        """Large IDR prices should format without crash."""
        saved = self._clear_env()
        try:
            send_alert("Test Item", 1_200_000.0, 1_500_000.0)
        finally:
            self._restore_env(saved)


if __name__ == "__main__":
    unittest.main()
