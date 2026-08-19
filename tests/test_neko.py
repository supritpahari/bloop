import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs.neko import Neko


class NekoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = Neko(SimpleNamespace())

    def test_embed_contains_image_credit_and_source(self):
        image = SimpleNamespace(
            id="image-id",
            url="https://images.example/neko.png",
            artist=SimpleNamespace(
                name="Example Artist",
                url="https://artist.example",
            ),
            source=SimpleNamespace(
                name="Pixiv",
                url="https://source.example",
            ),
        )

        embed = self.cog._build_embed(image)

        self.assertEqual(embed.image.url, image.url)
        self.assertIn("Example Artist", embed.description)
        self.assertEqual(embed.fields[0].name, "Source")
        self.assertIn("image-id", embed.footer.text)

    def test_cooldown_is_shared_by_command_variants(self):
        self.assertEqual(self.cog._cooldown_remaining(123), 0)
        self.assertGreater(self.cog._cooldown_remaining(123), 0)
        self.assertEqual(self.cog._cooldown_remaining(456), 0)

    async def test_fetch_requests_kemonomimi_without_blocking_loop(self):
        image = SimpleNamespace(url="https://images.example/neko.png")
        self.cog.nekos.get_random_image = unittest.mock.Mock(return_value=image)

        with patch("cogs.neko.asyncio.to_thread", new=AsyncMock(return_value=image)) as to_thread:
            result = await self.cog._fetch_neko()

        self.assertIs(result, image)
        to_thread.assert_awaited_once_with(
            self.cog.nekos.get_random_image,
            categories=["kemonomimi"],
        )


if __name__ == "__main__":
    unittest.main()
