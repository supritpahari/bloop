import unittest
from types import SimpleNamespace

from cogs.giveaway import CreationView, Giveaway, GiveawayPublicView, default_draft


class FakeGuild:
    id = 123
    me = SimpleNamespace()

    def get_role(self, role_id):
        return SimpleNamespace(id=role_id)


class GiveawayUITests(unittest.TestCase):
    def test_all_requested_subcommands_are_registered(self):
        cog = Giveaway(SimpleNamespace())
        names = {command.name for command in cog.giveaway.commands}
        self.assertEqual(names, {"create", "list", "manage", "end", "reroll", "cancel", "info"})

    def test_creation_panel_has_all_primary_controls(self):
        guild = FakeGuild()
        view = CreationView(SimpleNamespace(), guild, 42, default_draft(guild, 42))
        labels = {item.label for item in view.children}
        self.assertEqual(
            labels,
            {
                "Prize",
                "Winners",
                "Duration",
                "Channel",
                "Requirements",
                "Appearance",
                "Advanced Settings",
                "Preview",
                "Create Giveaway",
                "Cancel",
            },
        )

    def test_published_buttons_are_restart_persistent(self):
        view = GiveawayPublicView()
        self.assertTrue(view.is_persistent())
        self.assertEqual(
            {item.custom_id for item in view.children},
            {"bloop:giveaway:enter", "bloop:giveaway:participants"},
        )


if __name__ == "__main__":
    unittest.main()
