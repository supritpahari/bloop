import unittest

from ai_moderation.policy import describe_escalation, determine_enforcement


class AIModerationPolicyTests(unittest.TestCase):
    def test_moderate_repeat_warnings_escalate(self):
        expected = [
            ("warn", None),
            ("timeout", 600),
            ("timeout", 3600),
            ("kick", None),
            ("ban", None),
        ]
        actual = []
        for strike in range(1, 6):
            enforcement = determine_enforcement("moderate", strike, "warn")
            actual.append((enforcement.action, enforcement.timeout_seconds))
        self.assertEqual(actual, expected)

    def test_strict_takes_action_on_first_violation(self):
        first = determine_enforcement("strict", 1, "warn")
        second = determine_enforcement("strict", 2, "warn")
        self.assertEqual((first.action, first.timeout_seconds), ("timeout", 600))
        self.assertEqual((second.action, second.timeout_seconds), ("timeout", 3600))

    def test_lenient_eventually_kicks_and_bans(self):
        self.assertEqual(
            determine_enforcement("lenient", 5, "warn").action, "kick"
        )
        self.assertEqual(
            determine_enforcement("lenient", 6, "warn").action, "ban"
        )
        self.assertEqual(
            determine_enforcement("lenient", 99, "warn").action, "ban"
        )

    def test_ai_can_raise_but_not_lower_policy_action(self):
        self.assertEqual(
            determine_enforcement("moderate", 1, "ban").action, "ban"
        )
        self.assertEqual(
            determine_enforcement("moderate", 4, "warn").action, "kick"
        )

    def test_early_ai_timeout_uses_ten_minutes(self):
        enforcement = determine_enforcement("lenient", 1, "timeout")
        self.assertEqual(
            (enforcement.action, enforcement.timeout_seconds), ("timeout", 600)
        )

    def test_schedule_is_human_readable(self):
        schedule = describe_escalation("moderate")
        self.assertIn("1: warn", schedule)
        self.assertIn("2: 10m timeout", schedule)
        self.assertIn("5: ban", schedule)


if __name__ == "__main__":
    unittest.main()
