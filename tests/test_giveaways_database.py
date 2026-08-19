import os
import tempfile
import unittest

from economy.giveaways_db import GiveawaysDB, utc_ts


def giveaway(giveaway_id="GW-TEST1", guild_id=10):
    now = utc_ts()
    return {
        "giveaway_id": giveaway_id,
        "guild_id": guild_id,
        "channel_id": 20,
        "host_id": 30,
        "prize": "Nitro",
        "description": "Test",
        "winners_count": 2,
        "start_time": now,
        "end_time": now + 3600,
        "requirements": {"required_role_id": None},
        "bonus_entries": {"123": 2},
        "settings": {"allow_multiple_entries": True},
    }


class GiveawayDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = GiveawaysDB(self.path)
        await self.db.setup()

    async def asyncTearDown(self):
        await self.db.close()
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(self.path + suffix)
            except FileNotFoundError:
                pass

    async def test_configuration_survives_database_restart(self):
        await self.db.create(giveaway())
        await self.db.set_message_id("GW-TEST1", 999)
        await self.db.close()
        self.db = GiveawaysDB(self.path)
        await self.db.setup()

        stored = await self.db.get("gw-test1", 10)
        self.assertEqual(stored["message_id"], 999)
        self.assertEqual(stored["bonus_entries"], {"123": 2})
        self.assertTrue(stored["settings"]["allow_multiple_entries"])
        self.assertEqual(len(await self.db.dirty_messages()), 1)
        await self.db.mark_message_synced("GW-TEST1")
        self.assertEqual(await self.db.dirty_messages(), [])

    async def test_bonus_is_only_applied_once_to_multiple_entries(self):
        await self.db.create(giveaway())
        status, entry = await self.db.add_entry("GW-TEST1", 5, bonus=3, allow_multiple=True, maximum=2)
        self.assertEqual((status, entry["base_entries"], entry["bonus_entries"]), ("added", 1, 3))
        status, entry = await self.db.add_entry("GW-TEST1", 5, bonus=99, allow_multiple=True, maximum=2)
        self.assertEqual((status, entry["base_entries"], entry["bonus_entries"]), ("added", 2, 3))
        status, _ = await self.db.add_entry("GW-TEST1", 5, bonus=3, allow_multiple=True, maximum=2)
        self.assertEqual(status, "maximum")

    async def test_single_entry_and_inactive_status_are_enforced_atomically(self):
        await self.db.create(giveaway())
        self.assertEqual((await self.db.add_entry("GW-TEST1", 5, 0, False, 1))[0], "added")
        self.assertEqual((await self.db.add_entry("GW-TEST1", 5, 0, False, 1))[0], "exists")
        claimed = await self.db.claim_for_end("GW-TEST1", 10)
        self.assertIsNotNone(claimed)
        self.assertEqual((await self.db.add_entry("GW-TEST1", 6, 0, False, 1))[0], "inactive")
        self.assertIsNone(await self.db.claim_for_end("GW-TEST1", 10))

    async def test_end_and_reroll_history_are_permanent(self):
        await self.db.create(giveaway())
        await self.db.claim_for_end("GW-TEST1", 10)
        await self.db.finish_end("GW-TEST1", [1, 2])
        await self.db.record_reroll("GW-TEST1", [3, 4])

        stored = await self.db.get("GW-TEST1", 10)
        history = await self.db.winner_history("GW-TEST1")
        self.assertEqual(stored["status"], "ended")
        self.assertEqual(stored["winner_ids"], [3, 4])
        self.assertEqual([(x["round"], x["user_id"]) for x in history], [(0, 1), (0, 2), (1, 3), (1, 4)])

    async def test_restart_recovery_finds_expired_giveaway_once(self):
        data = giveaway()
        data["end_time"] = utc_ts() - 1
        await self.db.create(data)
        await self.db.close()
        self.db = GiveawaysDB(self.path)
        await self.db.setup()

        recovered = await self.db.expired(utc_ts())
        self.assertEqual([item["giveaway_id"] for item in recovered], ["GW-TEST1"])
        self.assertIsNotNone(await self.db.claim_for_end("GW-TEST1", 10))
        self.assertIsNone(await self.db.claim_for_end("GW-TEST1", 10))

    async def test_guild_scope_prevents_cross_server_access(self):
        await self.db.create(giveaway())
        self.assertIsNone(await self.db.get("GW-TEST1", 999))
        self.assertFalse(await self.db.cancel("GW-TEST1", 999))
        self.assertEqual((await self.db.get("GW-TEST1", 10))["status"], "active")


if __name__ == "__main__":
    unittest.main()
