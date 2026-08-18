import os
import tempfile
import unittest

from economy.db import Database


class AIModerationDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = Database(self.path)
        await self.db.setup()

    async def asyncTearDown(self):
        await self.db.close()
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(self.path + suffix)
            except FileNotFoundError:
                pass

    async def test_offenses_increment_per_guild_member(self):
        self.assertEqual(await self.db.record_ai_moderation_offense(1, 10), 1)
        self.assertEqual(await self.db.record_ai_moderation_offense(1, 10), 2)
        self.assertEqual(await self.db.record_ai_moderation_offense(1, 20), 1)
        self.assertEqual(await self.db.record_ai_moderation_offense(2, 10), 1)

    async def test_expired_strikes_restart_at_one(self):
        await self.db.record_ai_moderation_offense(1, 10)
        await self.db.execute(
            "UPDATE ai_moderation_offenses "
            "SET last_offense_at = datetime('now', '-8 days') "
            "WHERE guild_id = ? AND user_id = ?",
            (1, 10),
        )
        self.assertEqual(await self.db.record_ai_moderation_offense(1, 10), 1)

    async def test_owner_can_reset_strikes(self):
        await self.db.record_ai_moderation_offense(1, 10)
        await self.db.record_ai_moderation_offense(1, 10)
        await self.db.reset_ai_moderation_offenses(1, 10)
        self.assertEqual(await self.db.record_ai_moderation_offense(1, 10), 1)


if __name__ == "__main__":
    unittest.main()
