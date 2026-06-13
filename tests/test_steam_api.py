import unittest
from unittest.mock import MagicMock, patch

from src.steam_api import _encode_name, _parse_idr, _get_retry_delay, SteamMarketAPI


class TestEncodeName(unittest.TestCase):

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            _encode_name("")

    def test_whitespace_only_raises(self):
        with self.assertRaises(ValueError):
            _encode_name("   ")

    def test_spaces_encoded(self):
        result = _encode_name("Frozen Orb (Immortal) A")
        self.assertNotIn(" ", result)

    def test_tilde_becomes_percent7E(self):
        result = _encode_name("item~name")
        self.assertIn("%7E", result)
        self.assertNotIn("~", result)

    def test_strips_leading_trailing_whitespace(self):
        self.assertEqual(_encode_name("Test Item"), _encode_name("  Test Item  "))

    def test_parentheses_encoded(self):
        result = _encode_name("Orb (Immortal) A")
        self.assertNotIn("(", result)
        self.assertNotIn(")", result)


class TestParseIDR(unittest.TestCase):

    def test_dot_thousands_separator(self):
        self.assertEqual(_parse_idr("Rp 15.000"), 15000.0)

    def test_space_thousands_separator(self):
        self.assertEqual(_parse_idr("Rp 111 842"), 111842.0)

    def test_comma_thousands_separator(self):
        self.assertEqual(_parse_idr("Rp 111,842"), 111842.0)

    def test_plain_digits(self):
        self.assertEqual(_parse_idr("800000"), 800000.0)

    def test_empty_string_returns_none(self):
        self.assertIsNone(_parse_idr(""))

    def test_no_digits_returns_none(self):
        self.assertIsNone(_parse_idr("Rp"))

    def test_large_value(self):
        self.assertEqual(_parse_idr("Rp 1.200.000"), 1200000.0)


class TestGetRetryDelay(unittest.TestCase):

    def _mock(self, json_data=None, headers=None, json_raises=False):
        r = MagicMock()
        if json_raises:
            r.json.side_effect = ValueError("not json")
        else:
            r.json.return_value = json_data if json_data is not None else {}
        r.headers = headers or {}
        return r

    def test_json_body_has_highest_priority(self):
        r = self._mock(json_data={"retry_after": 30}, headers={"Retry-After": "60"})
        self.assertEqual(_get_retry_delay(r, 0), 30.0)

    def test_retry_after_header(self):
        r = self._mock(headers={"Retry-After": "45"})
        self.assertEqual(_get_retry_delay(r, 0), 45.0)

    def test_x_retry_after_header(self):
        r = self._mock(headers={"X-Retry-After": "20"})
        self.assertEqual(_get_retry_delay(r, 0), 20.0)

    def test_retry_after_takes_priority_over_x_retry_after(self):
        r = self._mock(headers={"Retry-After": "30", "X-Retry-After": "60"})
        self.assertEqual(_get_retry_delay(r, 0), 30.0)

    def test_fallback_exponential(self):
        r = self._mock()
        self.assertEqual(_get_retry_delay(r, 3), 40.0)   # 2**3 * 5
        self.assertEqual(_get_retry_delay(r, 0), 5.0)    # 2**0 * 5

    def test_json_error_falls_through_to_header(self):
        r = self._mock(json_raises=True, headers={"Retry-After": "15"})
        self.assertEqual(_get_retry_delay(r, 0), 15.0)

    def test_json_error_falls_through_to_fallback(self):
        r = self._mock(json_raises=True)
        self.assertEqual(_get_retry_delay(r, 2), 20.0)   # 2**2 * 5


class TestGetOrderbook(unittest.TestCase):

    def _api_with_response(self, payload):
        api = SteamMarketAPI()
        resp = MagicMock()
        resp.json.return_value = payload
        api._request = MagicMock(return_value=resp)
        return api

    def test_parses_amounts_divided_by_100(self):
        api = self._api_with_response({
            "success": True,
            "data": {
                "amtMaxBuyOrder": 5754500, "amtMinSellOrder": 150300,
                "cBuyOrders": 12764, "cSellOrders": 1098, "eCurrency": 10,
            },
        })
        result = api.get_orderbook("Soulstone - Normal")
        self.assertEqual(result["highest_buy"], 57545.0)
        self.assertEqual(result["lowest_sell"], 1503.0)
        self.assertEqual(result["buy_count"], 12764)
        self.assertEqual(result["sell_count"], 1098)
        self.assertEqual(result["currency"], 10)

    def test_sends_query_action_header(self):
        api = self._api_with_response({"success": True, "data": {}})
        api.get_orderbook("Iron Ingot")
        _, kwargs = api._request.call_args
        self.assertEqual(kwargs["headers"], {"x-valve-request-type": "queryAction"})

    def test_no_orders_returns_none(self):
        api = self._api_with_response({
            "success": True,
            "data": {"amtMaxBuyOrder": 0, "amtMinSellOrder": 0,
                     "cBuyOrders": 0, "cSellOrders": 0, "eCurrency": 10},
        })
        result = api.get_orderbook("War Bow (Legendary) A")
        self.assertIsNone(result["highest_buy"])
        self.assertIsNone(result["lowest_sell"])
        self.assertEqual(result["buy_count"], 0)

    def test_request_failure_returns_empty(self):
        api = SteamMarketAPI()
        api._request = MagicMock(return_value=None)
        result = api.get_orderbook("Iron Ingot")
        self.assertIsNone(result["highest_buy"])
        self.assertEqual(result["buy_count"], 0)

    def test_bad_payload_returns_empty(self):
        api = self._api_with_response({"success": False})
        result = api.get_orderbook("Iron Ingot")
        self.assertIsNone(result["highest_buy"])


if __name__ == "__main__":
    unittest.main()
