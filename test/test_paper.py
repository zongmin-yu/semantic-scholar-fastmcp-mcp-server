import unittest
import asyncio
import os
import random

from .test_utils import make_request, create_error_response, ErrorType, Config

class TestPaperTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Skip live API tests when no key is configured."""
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if not api_key or api_key.strip().lower() in ("", "none", "null", "false"):
            raise unittest.SkipTest("SEMANTIC_SCHOLAR_API_KEY is required for paper integration tests")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(10))
        finally:
            loop.close()

    def setUp(self):
        """Set up test environment"""
        # Create event loop for async tests
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Sample paper IDs for testing
        self.sample_paper_id = "649def34f8be52c8b66281af98ae884c09aef38b"
        self.sample_paper_ids = [
            self.sample_paper_id,
            "ARXIV:2106.15928"
        ]

    def tearDown(self):
        """Clean up after tests"""
        self.loop.close()

    def run_async(self, coro):
        """Helper to run async functions in tests"""
        return self.loop.run_until_complete(coro)

    def assert_success_or_skip(self, result):
        """Skip flaky live-API failures so the suite reflects local correctness."""
        if isinstance(result, dict) and "error" in result:
            self.skipTest(f"Semantic Scholar API unavailable: {result['error']['message']}")

    async def async_test_with_delay(self, endpoint: str, **kwargs):
        """Helper to run async tests with delay to handle rate limiting"""
        await asyncio.sleep(random.uniform(5, 8))  # Random initial delay
        
        max_retries = 5
        base_delay = 8
        
        for attempt in range(max_retries):
            result = await make_request(endpoint, **kwargs)
            if not isinstance(result, dict) or "error" not in result:
                return result
                
            if result["error"]["type"] == "rate_limit":
                delay = base_delay * (2 ** attempt) + random.uniform(0, 2)  # Add jitter
                await asyncio.sleep(delay)
                continue
            else:
                return result
                
        return result  # Return last result if all retries failed

    def test_paper_relevance_search(self):
        """Test paper relevance search functionality"""
        # Test basic search
        result = self.run_async(self.async_test_with_delay(
            "paper/search",  # Remove leading slash
            params={
                "query": "quantum computing",
                "fields": "title,abstract,year"
            }
        ))
        self.assert_success_or_skip(result)
        self.assertIn("data", result)
        self.assertIn("total", result)
        
        # Test with filters
        result = self.run_async(self.async_test_with_delay(
            "paper/search",
            params={
                "query": "machine learning",
                "fields": "title,year",
                "minCitationCount": 100,
                "year": "2020-2023"
            }
        ))
        self.assert_success_or_skip(result)
        self.assertIn("data", result)

    def test_paper_bulk_search(self):
        """Test paper bulk search functionality"""
        result = self.run_async(self.async_test_with_delay(
            "paper/search/bulk",  # Remove leading slash
            params={
                "query": "neural networks",
                "fields": "title,year,authors",
                "sort": "citationCount:desc"
            }
        ))
        self.assert_success_or_skip(result)
        self.assertIn("data", result)

    def test_paper_details(self):
        """Test paper details functionality"""
        result = self.run_async(self.async_test_with_delay(
            f"paper/{self.sample_paper_id}",  # Remove leading slash
            params={
                "fields": "title,abstract,year,authors"
            }
        ))
        self.assert_success_or_skip(result)
        self.assertIn("paperId", result)
        self.assertIn("title", result)

    def test_paper_batch_details(self):
        """Test batch paper details functionality"""
        result = self.run_async(self.async_test_with_delay(
            "paper/batch",  # Remove leading slash
            method="POST",
            params={"fields": "title,year,authors"},
            json={"ids": self.sample_paper_ids}
        ))
        self.assert_success_or_skip(result)
        self.assertTrue(isinstance(result, list))
        self.assertEqual(len(result), len(self.sample_paper_ids))

if __name__ == '__main__':
    unittest.main()
