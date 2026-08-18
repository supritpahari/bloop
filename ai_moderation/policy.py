"""Deterministic enforcement policy for AI moderation violations.

The AI decides whether content violates a policy.  Actual punishments are also
based on the member's recent strike count so an AI model that keeps returning
``warn`` cannot prevent repeat offenders from being timed out, kicked, or
banned.
"""

from dataclasses import dataclass


ACTION_ORDER = ("none", "warn", "timeout", "kick", "ban")
OFFENSE_WINDOW_DAYS = 7

# Each entry is (action, timeout duration in seconds). The last entry repeats
# for every later strike. Every policy eventually includes timeout, kick, and
# ban while preserving the selected moderation level's intended strictness.
ESCALATION_POLICIES: dict[str, tuple[tuple[str, int | None], ...]] = {
    "strict": (
        ("timeout", 10 * 60),
        ("timeout", 60 * 60),
        ("kick", None),
        ("ban", None),
    ),
    "moderate": (
        ("warn", None),
        ("timeout", 10 * 60),
        ("timeout", 60 * 60),
        ("kick", None),
        ("ban", None),
    ),
    "lenient": (
        ("warn", None),
        ("warn", None),
        ("timeout", 10 * 60),
        ("timeout", 60 * 60),
        ("kick", None),
        ("ban", None),
    ),
}


@dataclass(frozen=True)
class Enforcement:
    """The action the bot must apply for a confirmed violation."""

    action: str
    timeout_seconds: int | None = None


def determine_enforcement(
    moderation_level: str,
    strike_count: int,
    suggested_action: str,
) -> Enforcement:
    """Combine strike escalation with the AI's severity recommendation.

    The strike policy is a minimum action. A model can recommend a stronger
    response for an immediately dangerous violation, but it cannot keep a
    repeat offender at ``warn`` forever.
    """

    policy = ESCALATION_POLICIES.get(
        moderation_level, ESCALATION_POLICIES["moderate"]
    )
    policy_action, policy_timeout = policy[min(max(strike_count, 1) - 1, len(policy) - 1)]

    if suggested_action not in ACTION_ORDER:
        suggested_action = "none"

    if ACTION_ORDER.index(suggested_action) > ACTION_ORDER.index(policy_action):
        # An AI-requested timeout before the policy's first timeout uses the
        # standard ten-minute duration.
        timeout_seconds = 10 * 60 if suggested_action == "timeout" else None
        return Enforcement(suggested_action, timeout_seconds)

    return Enforcement(policy_action, policy_timeout)


def describe_escalation(moderation_level: str) -> str:
    """Return a concise, human-readable strike schedule for the config UI."""

    policy = ESCALATION_POLICIES.get(
        moderation_level, ESCALATION_POLICIES["moderate"]
    )
    labels = []
    for strike, (action, seconds) in enumerate(policy, start=1):
        if action == "timeout":
            duration = "10m" if seconds == 10 * 60 else "1h"
            label = f"{duration} timeout"
        else:
            label = action
        labels.append(f"{strike}: {label}")
    return " → ".join(labels)
