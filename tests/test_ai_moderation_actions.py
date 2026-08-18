import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cogs.ai_moderation import AIModeration


class AIModerationActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = AIModeration(SimpleNamespace())
        permissions = SimpleNamespace(
            moderate_members=True,
            kick_members=True,
            ban_members=True,
        )
        self.bot_member = SimpleNamespace(
            guild_permissions=permissions,
            top_role=10,
        )
        self.guild = SimpleNamespace(me=self.bot_member)
        self.member = SimpleNamespace(
            mention="<@123>",
            top_role=1,
            timeout=AsyncMock(),
            kick=AsyncMock(),
            ban=AsyncMock(),
        )
        self.channel = SimpleNamespace(send=AsyncMock())
        self.message = SimpleNamespace(
            author=self.member,
            guild=self.guild,
            channel=self.channel,
            reply=AsyncMock(),
        )

    async def asyncTearDown(self):
        await self.cog.service.close()

    async def test_timeout_is_actually_applied(self):
        applied = await self.cog._apply_action(
            self.message,
            action="timeout",
            reason="abusive language",
            confidence=0.9,
            strike_count=2,
            timeout_seconds=600,
        )

        self.assertTrue(applied)
        self.member.timeout.assert_awaited_once_with(
            timedelta(seconds=600),
            reason="AI moderation strike 2: abusive language",
        )
        notice = self.channel.send.await_args.args[0]
        self.assertIn("timed out for 10 minutes", notice)
        self.assertIn("active strike: 2", notice)

    async def test_kick_is_actually_applied(self):
        applied = await self.cog._apply_action(
            self.message,
            action="kick",
            reason="repeated abuse",
            confidence=0.95,
            strike_count=4,
        )

        self.assertTrue(applied)
        self.member.kick.assert_awaited_once()
        self.assertIn("was kicked", self.channel.send.await_args.args[0])

    async def test_missing_permission_is_reported_in_channel(self):
        self.bot_member.guild_permissions.kick_members = False

        applied = await self.cog._apply_action(
            self.message,
            action="kick",
            reason="repeated abuse",
            confidence=0.95,
            strike_count=4,
        )

        self.assertFalse(applied)
        self.member.kick.assert_not_awaited()
        notice = self.channel.send.await_args.args[0]
        self.assertIn("could not apply", notice)
        self.assertIn("Kick Members", notice)

    async def test_warning_explains_future_escalation(self):
        applied = await self.cog._apply_action(
            self.message,
            action="warn",
            reason="profanity",
            confidence=0.8,
            strike_count=1,
        )

        self.assertTrue(applied)
        warning = self.message.reply.await_args.args[0]
        self.assertIn("active strike: 1", warning)
        self.assertIn("timeout, kick, and ban", warning)

    async def test_unknown_action_is_never_treated_as_ban(self):
        applied = await self.cog._apply_action(
            self.message,
            action="delete",
            reason="invalid model response",
            confidence=1.0,
            strike_count=1,
        )

        self.assertFalse(applied)
        self.member.ban.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
