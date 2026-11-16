import unittest
from unittest.mock import MagicMock, patch

from agents.router_agent import RouteDecision, route_query


class FakeLLMClassifier:
    def __init__(self, predefined_route: str = "product_search"):
        self.predefined_route = predefined_route

    def invoke(self, messages):
        return RouteDecision(route=self.predefined_route, metric="total_count")


class FakeChatGroq:
    def __init__(self, **_):
        pass

    def with_structured_output(self, schema):
        return FakeLLMClassifier("catalog_analytics")


class TestRouterAgent(unittest.TestCase):

    def test_router_agent_role_routing(self):
        shopper_state = {
            "query": "How many products have no sale price?",
            "role": "Shopper",
        }
        with patch("agents.router_agent.ChatGroq", FakeChatGroq):
            decision_shopper = route_query(shopper_state)
            self.assertEqual(decision_shopper["plan"], "forbidden")

        merch_state = {
            "query": "How many products have no sale price?",
            "role": "Merchandiser",
        }
        with patch("agents.router_agent.ChatGroq", FakeChatGroq):
            decision_merch = route_query(merch_state)
            self.assertEqual(decision_merch["plan"], "catalog_analytics")

        admin_state = {
            "query": "Which collection has the widest price range?",
            "role": "Admin",
        }
        with patch("agents.router_agent.ChatGroq", FakeChatGroq):
            decision_admin = route_query(admin_state)
            self.assertEqual(decision_admin["plan"], "catalog_analytics")


if __name__ == "__main__":
    unittest.main()
