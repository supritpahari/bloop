"""Unit tests for the RedditMemeService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.reddit_service import MemePost, RedditMemeService


class TestRedditMemeService:
    """Tests for RedditMemeService class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock aiohttp session."""
        session = AsyncMock()
        session.closed = False
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create a RedditMemeService with mocked session."""
        return RedditMemeService(session=mock_session)

    def test_init_with_session(self, mock_session):
        """Test initialization with provided session."""
        service = RedditMemeService(session=mock_session)
        assert service._session == mock_session
        assert service._owns_session is False

    def test_init_without_session(self):
        """Test initialization without session (should create own)."""
        with patch("aiohttp.ClientSession") as mock_cs:
            service = RedditMemeService()
            mock_cs.assert_called_once()
            assert service._owns_session is True

    def test_is_valid_image_url(self, service):
        """Test image URL validation."""
        valid_urls = [
            "https://example.com/image.jpg",
            "https://example.com/image.jpeg",
            "https://example.com/image.png",
            "https://example.com/image.gif",
            "https://example.com/image.webp",
            "https://example.com/Image.JPG",  # case insensitive
        ]
        invalid_urls = [
            "https://example.com/image.mp4",
            "https://example.com/video",
            "https://example.com/image",
            "https://example.com/image.txt",
            "https://reddit.com/r/memes/comments/abc123",
        ]

        for url in valid_urls:
            assert service._is_valid_image_url(url), f"Should accept: {url}"

        for url in invalid_urls:
            assert not service._is_valid_image_url(url), f"Should reject: {url}"

    def test_parse_valid_reddit_post(self, service):
        """Test parsing a valid Reddit post."""
        post_data = {
            "data": {
                "title": "Test Meme",
                "url": "https://i.imgur.com/test.jpg",
                "permalink": "/r/memes/comments/abc123/test_meme/",
                "author": "testuser",
                "score": 1500,
                "over_18": False,
                "is_video": False,
                "is_gallery": False,
                "selftext": "",
                "removed_by_category": None,
            }
        }

        meme = service._parse_reddit_post(post_data, "memes")

        assert meme is not None
        assert isinstance(meme, MemePost)
        assert meme.title == "Test Meme"
        assert meme.image_url == "https://i.imgur.com/test.jpg"
        assert meme.post_url == "https://reddit.com/r/memes/comments/abc123/test_meme/"
        assert meme.subreddit == "memes"
        assert meme.author == "testuser"
        assert meme.upvotes == 1500

    def test_parse_nsfw_post(self, service):
        """Test that NSFW posts are rejected."""
        post_data = {
            "data": {
                "title": "NSFW Meme",
                "url": "https://i.imgur.com/test.jpg",
                "permalink": "/r/memes/comments/abc123/",
                "author": "testuser",
                "score": 100,
                "over_18": True,
                "is_video": False,
                "is_gallery": False,
                "selftext": "",
                "removed_by_category": None,
            }
        }

        meme = service._parse_reddit_post(post_data, "memes")
        assert meme is None

    def test_parse_video_post(self, service):
        """Test that video posts are rejected."""
        post_data = {
            "data": {
                "title": "Video Meme",
                "url": "https://v.redd.it/video.mp4",
                "permalink": "/r/memes/comments/abc123/",
                "author": "testuser",
                "score": 100,
                "over_18": False,
                "is_video": True,
                "is_gallery": False,
                "selftext": "",
                "removed_by_category": None,
            }
        }

        meme = service._parse_reddit_post(post_data, "memes")
        assert meme is None

    def test_parse_gallery_post(self, service):
        """Test that gallery posts are rejected."""
        post_data = {
            "data": {
                "title": "Gallery Meme",
                "url": "https://reddit.com/gallery/abc123",
                "permalink": "/r/memes/comments/abc123/",
                "author": "testuser",
                "score": 100,
                "over_18": False,
                "is_video": False,
                "is_gallery": True,
                "selftext": "",
                "removed_by_category": None,
            }
        }

        meme = service._parse_reddit_post(post_data, "memes")
        assert meme is None

    def test_parse_deleted_post(self, service):
        """Test that deleted posts are rejected."""
        post_data = {
            "data": {
                "title": "Deleted Meme",
                "url": "https://i.imgur.com/test.jpg",
                "permalink": "/r/memes/comments/abc123/",
                "author": "[deleted]",
                "score": 100,
                "over_18": False,
                "is_video": False,
                "is_gallery": False,
                "selftext": "[deleted]",
                "removed_by_category": None,
            }
        }

        meme = service._parse_reddit_post(post_data, "memes")
        assert meme is None

    def test_parse_removed_post(self, service):
        """Test that removed posts are rejected."""
        post_data = {
            "data": {
                "title": "Removed Meme",
                "url": "https://i.imgur.com/test.jpg",
                "permalink": "/r/memes/comments/abc123/",
                "author": "testuser",
                "score": 100,
                "over_18": False,
                "is_video": False,
                "is_gallery": False,
                "selftext": "",
                "removed_by_category": "moderator",
            }
        }

        meme = service._parse_reddit_post(post_data, "memes")
        assert meme is None

    def test_parse_missing_title(self, service):
        """Test that posts without title are rejected."""
        post_data = {
            "data": {
                "title": "",
                "url": "https://i.imgur.com/test.jpg",
                "permalink": "/r/memes/comments/abc123/",
                "author": "testuser",
                "score": 100,
                "over_18": False,
                "is_video": False,
                "is_gallery": False,
                "selftext": "",
                "removed_by_category": None,
            }
        }

        meme = service._parse_reddit_post(post_data, "memes")
        assert meme is None

    def test_parse_invalid_image_url(self, service):
        """Test that posts with non-image URLs are rejected."""
        post_data = {
            "data": {
                "title": "Text Post",
                "url": "https://example.com/not-an-image",
                "permalink": "/r/memes/comments/abc123/",
                "author": "testuser",
                "score": 100,
                "over_18": False,
                "is_video": False,
                "is_gallery": False,
                "selftext": "",
                "removed_by_category": None,
            }
        }

        meme = service._parse_reddit_post(post_data, "memes")
        assert meme is None

    @pytest.mark.asyncio
    async def test_get_memes_cache_miss(self, service, mock_session):
        """Test fetching memes when cache is empty."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Meme 1",
                            "url": "https://i.imgur.com/meme1.jpg",
                            "permalink": "/r/memes/comments/1/",
                            "author": "user1",
                            "score": 100,
                            "over_18": False,
                            "is_video": False,
                            "is_gallery": False,
                            "selftext": "",
                            "removed_by_category": None,
                        }
                    },
                    {
                        "data": {
                            "title": "Meme 2",
                            "url": "https://i.imgur.com/meme2.png",
                            "permalink": "/r/memes/comments/2/",
                            "author": "user2",
                            "score": 200,
                            "over_18": False,
                            "is_video": False,
                            "is_gallery": False,
                            "selftext": "",
                            "removed_by_category": None,
                        }
                    },
                ]
            }
        })
        mock_session.get.return_value.__aenter__.return_value = mock_response

        memes = await service.get_memes("memes")

        assert len(memes) == 2
        assert memes[0].title == "Meme 1"
        assert memes[1].title == "Meme 2"
        mock_session.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_memes_cache_hit(self, service, mock_session):
        """Test that cached memes are returned without fetching."""
        # First call to populate cache
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Cached Meme",
                            "url": "https://i.imgur.com/cached.jpg",
                            "permalink": "/r/memes/comments/cached/",
                            "author": "cacheduser",
                            "score": 500,
                            "over_18": False,
                            "is_video": False,
                            "is_gallery": False,
                            "selftext": "",
                            "removed_by_category": None,
                        }
                    }
                ]
            }
        })
        mock_session.get.return_value.__aenter__.return_value = mock_response

        # First call - fetches from Reddit
        memes1 = await service.get_memes("memes")
        assert len(memes1) == 1

        # Reset mock
        mock_session.get.reset_mock()

        # Second call - should use cache
        memes2 = await service.get_memes("memes")
        assert len(memes2) == 1
        assert memes2[0].title == "Cached Meme"
        mock_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_memes_api_error(self, service, mock_session):
        """Test handling of Reddit API errors."""
        mock_response = AsyncMock()
        mock_response.status = 429  # Rate limited
        mock_session.get.return_value.__aenter__.return_value = mock_response

        memes = await service.get_memes("memes")
        assert memes == []

    @pytest.mark.asyncio
    async def test_get_memes_timeout(self, service, mock_session):
        """Test handling of timeout errors."""
        import asyncio
        mock_session.get.side_effect = asyncio.TimeoutError()

        memes = await service.get_memes("memes")
        assert memes == []

    @pytest.mark.asyncio
    async def test_get_random_meme_specific_subreddit(self, service):
        """Test getting a random meme from a specific subreddit."""
        mock_memes = [
            MemePost("Meme 1", "https://img1.jpg", "https://reddit.com/1", "memes", "user1", 100),
            MemePost("Meme 2", "https://img2.jpg", "https://reddit.com/2", "memes", "user2", 200),
        ]

        with patch.object(service, "get_memes", return_value=mock_memes):
            meme = await service.get_random_meme(12345, subreddit="memes")

        assert meme is not None
        assert meme.title in ["Meme 1", "Meme 2"]
        assert meme.subreddit == "memes"

    @pytest.mark.asyncio
    async def test_get_random_meme_avoids_repeat(self, service):
        """Test that the same meme isn't shown twice in a row."""
        mock_memes = [
            MemePost("Meme 1", "https://img1.jpg", "https://reddit.com/1", "memes", "user1", 100),
            MemePost("Meme 2", "https://img2.jpg", "https://reddit.com/2", "memes", "user2", 200),
        ]

        with patch.object(service, "get_memes", return_value=mock_memes):
            # First call
            meme1 = await service.get_random_meme(12345, subreddit="memes")
            # Second call - should avoid the first meme
            meme2 = await service.get_random_meme(12345, subreddit="memes")

        assert meme1 is not None
        assert meme2 is not None
        assert meme1.image_url != meme2.image_url

    @pytest.mark.asyncio
    async def test_get_random_meme_invalid_subreddit(self, service):
        """Test that invalid subreddit returns None."""
        meme = await service.get_random_meme(12345, subreddit="invalidsubreddit")
        assert meme is None

    @pytest.mark.asyncio
    async def test_get_trending_meme(self, service, mock_session):
        """Test fetching trending (top of day) memes."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Trending Meme",
                            "url": "https://i.imgur.com/trending.jpg",
                            "permalink": "/r/memes/comments/trending/",
                            "author": "trenduser",
                            "score": 5000,
                            "over_18": False,
                            "is_video": False,
                            "is_gallery": False,
                            "selftext": "",
                            "removed_by_category": None,
                        }
                    }
                ]
            }
        })
        mock_session.get.return_value.__aenter__.return_value = mock_response

        meme = await service.get_trending_meme(12345, subreddit="memes")

        assert meme is not None
        assert meme.title == "Trending Meme"
        assert meme.upvotes == 5000
        mock_session.get.assert_called_once()
        # Verify it uses top.json with t=day
        call_args = mock_session.get.call_args[0][0]
        assert "top.json" in call_args
        assert "t=day" in call_args

    def test_create_embed(self, service):
        """Test creating a Discord embed from a meme."""
        meme = MemePost(
            title="Test Meme",
            image_url="https://i.imgur.com/test.jpg",
            post_url="https://reddit.com/r/memes/comments/test/",
            subreddit="memes",
            author="testuser",
            upvotes=1234,
        )

        with patch("discord.Embed") as mock_embed_class:
            mock_embed = MagicMock()
            mock_embed_class.return_value = mock_embed

            embed = service.create_embed(meme)

            mock_embed_class.assert_called_once()
            call_kwargs = mock_embed_class.call_args[1]
            assert call_kwargs["title"] == "Test Meme"
            assert call_kwargs["url"] == "https://reddit.com/r/memes/comments/test/"
            assert isinstance(call_kwargs["color"], int)
            mock_embed.set_image.assert_called_once_with(url="https://i.imgur.com/test.jpg")
            mock_embed.set_footer.assert_called_once_with(text="r/memes • 👍 1,234 • u/testuser")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])