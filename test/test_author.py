import unittest
import asyncio
import os

from .test_utils import make_request, create_error_response, ErrorType, Config

class TestAuthorTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Skip live API tests when no key is configured."""
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if not api_key or api_key.strip().lower() in ("", "none", "null", "false"):
            raise unittest.SkipTest("SEMANTIC_SCHOLAR_API_KEY is required for author integration tests")

    def setUp(self):
        """Set up test environment"""
        # Create event loop for async tests
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Sample author IDs for testing
        self.sample_author_id = "1741101"  # Andrew Ng
        self.sample_author_ids = [
            self.sample_author_id,
            "2061296"  # Yann LeCun
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

    def test_author_search(self):
        """Test author search functionality"""
        result = self.run_async(self.async_test_with_delay(make_request(
            "/author/search",
            params={
                "query": "Andrew Ng",
                "fields": "name,affiliations,paperCount"
            }
        )))
        self.assertIn("data", result)
        self.assertIn("total", result)

    def test_author_details(self):
        """Test author details functionality"""
        result = self.run_async(self.async_test_with_delay(make_request(
            f"/author/{self.sample_author_id}",
            params={
                "fields": "name,affiliations,paperCount,citationCount,hIndex"
            }
        )))
        self.assertIn("authorId", result)
        self.assertIn("name", result)

    def test_author_papers(self):
        """Test author papers functionality"""
        result = self.run_async(self.async_test_with_delay(make_request(
            f"/author/{self.sample_author_id}/papers",
            params={
                "fields": "title,year,citationCount",
                "limit": 10
            }
        )))
        self.assertIn("data", result)
        self.assertIn("next", result)
        self.assertIn("offset", result)
        self.assertTrue(isinstance(result["data"], list))

    def test_author_batch_details(self):
        """Test batch author details functionality"""
        result = self.run_async(self.async_test_with_delay(make_request(
            "/author/batch",
            method="POST",
            params={"fields": "name,affiliations,paperCount"},
            json={"ids": self.sample_author_ids}
        )))
        self.assertTrue(isinstance(result, list))
        self.assertEqual(len(result), len(self.sample_author_ids))

if __name__ == '__main__':
    unittest.main()
