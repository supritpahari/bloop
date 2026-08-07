"""Reddit meme fetching service with caching and filtering."""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp
import discord

logger = logging.getLogger(__name__)


@dataclass
class MemePost:
    """Represents a valid meme post from Reddit."""
    title: str
    image_url: str
    post_url: str
    subreddit: str
    author: str
    upvotes: int


class RedditMemeService:
    """Service for fetching memes from Reddit with caching and filtering."""

    # Supported subreddits
    SUBREDDITS = [
        "memes",
        "dankmemes",
        "wholesomememes",
        "meirl",
        "shitposting",
        "ProgrammerHumor",
        "HistoryMemes",
        "MinecraftMemes",
        "AnimeMemes",
        "DiscordMemes",
        "FunnyAnimals",
        "PerfectTiming",
    ]

    # Valid image extensions
    VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

    # Cache TTL: 15 minutes
    CACHE_TTL = 900

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        """Initialize the Reddit meme service.

        Args:
            session: Optional aiohttp ClientSession. If not provided, one will be created.
        """
        self._session = session
        self._owns_session = session is None
        # Cache: subreddit -> (timestamp, list of MemePost)
        self._cache: dict[str, tuple[float, list[MemePost]]] = {}
        # Track last meme per guild to avoid repeats
        self._last_meme: dict[int, str] = {}
        self._lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "BloopBot/1.0 (by /u/BloopBot)"}
            )
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session if we own it."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    def _is_cache_valid(self, subreddit: str) -> bool:
        """Check if cache for subreddit is still valid."""
        if subreddit not in self._cache:
            return False
        timestamp, _ = self._cache[subreddit]
        return time.time() - timestamp < self.CACHE_TTL

    def _is_valid_image_url(self, url: str) -> bool:
        """Check if URL is a direct image link with valid extension."""
        url_lower = url.lower()
        return any(url_lower.endswith(ext) for ext in self.VALID_EXTENSIONS)

    def _parse_reddit_post(self, post_data: dict, subreddit: str) -> Optional[MemePost]:
        """Parse a Reddit post into a MemePost if valid.

        Args:
            post_data: The post data from Reddit's JSON.
            subreddit: The subreddit name.

        Returns:
            MemePost if valid, None otherwise.
        """
        try:
            data = post_data.get("data", {})

            # Skip NSFW
            if data.get("over_18", False):
                return None

            # Skip deleted/removed
            if data.get("selftext", "") in ("[deleted]", "[removed]") or data.get("removed_by_category"):
                return None

            # Skip videos and galleries
            if data.get("is_video", False):
                return None
            if data.get("is_gallery", False):
                return None

            # Must have a valid image URL
            url = data.get("url", "")
            if not self._is_valid_image_url(url):
                return None

            # Must have title and author
            title = data.get("title", "").strip()
            author = data.get("author", "").strip()
            if not title or not author or author == "[deleted]":
                return None

            # Get upvotes
            upvotes = data.get("score", 0)

            # Construct post URL
            permalink = data.get("permalink", "")
            post_url = f"https://reddit.com{permalink}"

            return MemePost(
                title=title,
                image_url=url,
                post_url=post_url,
                subreddit=subreddit,
                author=author,
                upvotes=upvotes,
            )
        except Exception as e:
            logger.debug(f"Failed to parse Reddit post: {e}")
            return None

    async def _fetch_subreddit(self, subreddit: str) -> list[MemePost]:
        """Fetch and parse hot posts from a subreddit.

        Args:
            subreddit: The subreddit name.

        Returns:
            List of valid MemePost objects.
        """
        session = await self._get_session()
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=100"

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.warning(f"Reddit API returned {response.status} for r/{subreddit}")
                    return []

                json_data = await response.json()
                posts = json_data.get("data", {}).get("children", [])

                memes = []
                for post in posts:
                    meme = self._parse_reddit_post(post, subreddit)
                    if meme:
                        memes.append(meme)

                logger.info(f"Fetched {len(memes)} valid memes from r/{subreddit}")
                return memes

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching r/{subreddit}")
            return []
        except aiohttp.ClientError as e:
            logger.warning(f"Client error fetching r/{subreddit}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching r/{subreddit}: {e}")
            return []

    async def get_memes(self, subreddit: str) -> list[MemePost]:
        """Get memes for a subreddit, using cache if valid.

        Args:
            subreddit: The subreddit name.

        Returns:
            List of MemePost objects.
        """
        async with self._lock:
            if self._is_cache_valid(subreddit):
                _, memes = self._cache[subreddit]
                return memes

            # Fetch fresh data
            memes = await self._fetch_subreddit(subreddit)
            self._cache[subreddit] = (time.time(), memes)
            return memes

    async def get_random_meme(self, guild_id: int, subreddit: Optional[str] = None) -> Optional[MemePost]:
        """Get a random meme, avoiding the last one shown in this guild.

        Args:
            guild_id: The Discord guild ID.
            subreddit: Optional specific subreddit. If None, picks randomly.

        Returns:
            A random MemePost, or None if no memes available.
        """
        if subreddit:
            if subreddit not in self.SUBREDDITS:
                logger.warning(f"Invalid subreddit requested: {subreddit}")
                return None
            subreddits_to_try = [subreddit]
        else:
            subreddits_to_try = self.SUBREDDITS.copy()
            random.shuffle(subreddits_to_try)

        last_meme_url = self._last_meme.get(guild_id)

        for sub in subreddits_to_try:
            memes = await self.get_memes(sub)
            if not memes:
                continue

            # Filter out the last meme shown in this guild
            available = [m for m in memes if m.image_url != last_meme_url]
            if not available:
                # If all memes were the last one, just use all
                available = memes

            meme = random.choice(available)
            self._last_meme[guild_id] = meme.image_url
            return meme

        return None

    async def get_trending_meme(self, guild_id: int, subreddit: Optional[str] = None) -> Optional[MemePost]:
        """Get a trending meme (top posts of the day).

        Args:
            guild_id: The Discord guild ID.
            subreddit: Optional specific subreddit. If None, picks randomly.

        Returns:
            A random top meme, or None if no memes available.
        """
        session = await self._get_session()

        if subreddit:
            if subreddit not in self.SUBREDDITS:
                return None
            subreddits_to_try = [subreddit]
        else:
            subreddits_to_try = self.SUBREDDITS.copy()
            random.shuffle(subreddits_to_try)

        last_meme_url = self._last_meme.get(guild_id)

        for sub in subreddits_to_try:
            url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=50"
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        continue
                    json_data = await response.json()
                    posts = json_data.get("data", {}).get("children", [])

                    memes = []
                    for post in posts:
                        meme = self._parse_reddit_post(post, sub)
                        if meme:
                            memes.append(meme)

                    if not memes:
                        continue

                    available = [m for m in memes if m.image_url != last_meme_url]
                    if not available:
                        available = memes

                    meme = random.choice(available)
                    self._last_meme[guild_id] = meme.image_url
                    return meme

            except Exception as e:
                logger.debug(f"Error fetching trending from r/{sub}: {e}")
                continue

        return None

    def create_embed(self, meme: MemePost) -> discord.Embed:
        """Create a Discord embed for a meme.

        Args:
            meme: The MemePost to create an embed for.

        Returns:
            A Discord Embed object.
        """
        embed = discord.Embed(
            title=meme.title,
            url=meme.post_url,
            color=random.randint(0, 0xFFFFFF),
        )
        embed.set_image(url=meme.image_url)
        embed.set_footer(text=f"r/{meme.subreddit} • 👍 {meme.upvotes:,} • u/{meme.author}")
        return embed