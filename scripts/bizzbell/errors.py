"""Exceptions the CLI turns into a friendly one-line message (no traceback unless --debug).

Every expected failure raises a BBError subclass. `exit_code` is what `bb` exits with."""


class BBError(Exception):
    """An expected failure with a plain message for the user or the agent."""

    exit_code = 1


class UsageError(BBError):
    """Wrong arguments or a missing project/file."""

    exit_code = 2


class ConfigError(BBError):
    """Something in bizzbell.json / project.json is missing or wrong."""


class GateFailed(BBError):
    """Raised only by callers that want an exception for a failed gate (bb gate itself returns 3)."""

    exit_code = 3


class OutOfOrder(BBError):
    """A paid stage was asked for while a layer it builds on has not passed its gate. Nothing was sent."""

    exit_code = 3


class RoundsExhausted(BBError):
    """The restructure rounds for a stage are used up: the agent must ask the user."""

    exit_code = 4


class BudgetExceeded(BBError):
    """A paid call would pass the INR cap (or no budget was approved yet). Nothing was sent."""

    exit_code = 7
