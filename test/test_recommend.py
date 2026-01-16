import unittest
import asyncio
import os
from typing import Optional, List, Dict

from .test_utils import make_request, create_error_response, ErrorType, Config

class TestRecommendationTools(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        # API key is required for recommendations
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if not api_key or api_key.strip().lower() in ("", "none", "null", "false"):
            self.skipTest("SEMANTIC_SCHOLAR_API_KEY is required for recommendation tests")
        
        # Create event loop for async tests
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Sample paper IDs for testing (using full IDs)
        self.sample_paper_id = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"  # "Attention is All You Need"
        self.positive_paper_ids = [
            self.sample_paper_id,
            "df2b0e26d0599ce3e70df8a9da02e51594e0e992"  # BERT
        ]
        self.negative_paper_ids = [
            "649def34f8be52c8b66281af98ae884c09aef38b"  # Different topic
        ]

    def tearDown(self):
        """Clean up after tests"""
        self.loop.close()

    def run_async(self, coro):
        """Helper to run async functions in tests"""
        return self.loop.run_until_complete(coro)

    async def async_test_with_delay(self, coro):
        """Helper to run async tests with delay to handle rate limiting"""
        await asyncio.sleep(1)  # Add 1 second delay between tests
        return await coro

    def test_paper_recommendations_single(self):
        """Test single paper recommendations functionality"""
        result = self.run_async(self.async_test_with_delay(make_request(
            f"papers/forpaper/{self.sample_paper_id}",  # Using full paper ID
            params={
                "fields": "title,year"  # Minimal fields
            }
        )))
        self.assertIn("recommendedPapers", result)
        self.assertTrue(isinstance(result["recommendedPapers"], list))

    def test_paper_recommendations_multi(self):
        """Test multi-paper recommendations functionality"""
        result = self.run_async(self.async_test_with_delay(make_request(
            "papers",  # No leading slash
            method="POST",
            params={"fields": "title,year"},  # Minimal fields
            json={
                "positivePaperIds": self.positive_paper_ids,  # Changed key name to match API
                "negativePaperIds": self.negative_paper_ids
            }
        )))
        self.assertIn("recommendedPapers", result)
        self.assertTrue(isinstance(result["recommendedPapers"], list))

if __name__ == '__main__':
    unittest.main()
