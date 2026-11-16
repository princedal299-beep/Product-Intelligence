import unittest

from workflow.graph import after_verification, route_to_agent, safe_response


class TestTrajectory(unittest.TestCase):

    def test_right_agent_routing(self):
        self.assertEqual(route_to_agent({"plan": "product_search"}), "catalog_agent")
        self.assertEqual(route_to_agent({"plan": "product_details"}), "catalog_agent")
        self.assertEqual(route_to_agent({"plan": "catalog_analytics"}), "catalog_agent")

        self.assertEqual(route_to_agent({"plan": "jewellery_help"}), "knowledge_agent")

        self.assertEqual(route_to_agent({"plan": "forbidden"}), "safe_response")
        self.assertEqual(route_to_agent({"plan": "unsupported"}), "safe_response")

    def test_stayed_within_retry_limit(self):
        self.assertEqual(after_verification({"verification_status": "FAIL", "retry_count": 0}), "retry")
        self.assertEqual(after_verification({"verification_status": "FAIL", "retry_count": 1}), "retry")
        self.assertEqual(after_verification({"verification_status": "FAIL", "retry_count": 2}), "safe_response")

        final_reply = safe_response({"retry_count": 2})
        self.assertEqual(final_reply["generation"], "Sorry, I could not confirm this answer.")


if __name__ == "__main__":
    unittest.main()
