import unittest
from unittest.mock import MagicMock

from agents.verifier_agent import VerificationResult


class TestGroundedness(unittest.TestCase):

    def test_grounded_answer_is_approved_by_judge(self):
        context = "Clean a ruby ring using lukewarm water, mild soap, and a soft-bristled brush."
        grounded_answer = "To clean a ruby ring, gently wash it with lukewarm water and mild soap."

        mock_judge = MagicMock()
        mock_judge.invoke.return_value = VerificationResult(
            is_valid=True, feedback="Draft answer is backed by context."
        )

        result = mock_judge.invoke(f"Context: {context}\nDraft: {grounded_answer}")
        self.assertTrue(result.is_valid)
        self.assertIn("backed by context", result.feedback)

    def test_ungrounded_answer_is_rejected_by_judge(self):
        context = "Clean a ruby ring using lukewarm water, mild soap, and a soft-bristled brush."
        ungrounded_answer = "Clean a ruby ring by soaking it in boiling bleach and acid."

        mock_judge = MagicMock()
        mock_judge.invoke.return_value = VerificationResult(
            is_valid=False, feedback="Draft introduces bleach and acid, which contradicts context."
        )

        result = mock_judge.invoke(f"Context: {context}\nDraft: {ungrounded_answer}")
        self.assertFalse(result.is_valid)
        self.assertIn("contradicts context", result.feedback)


if __name__ == "__main__":
    unittest.main()
