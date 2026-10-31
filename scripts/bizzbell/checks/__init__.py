"""Local (deterministic) gate checks. Every module here is imported by gate.load_checks().

Add a check by adding a module with functions decorated by @check("name"):

    from ..gate import check

    @check("my_check")
    def my_check(ctx, limit=3):
        return "yes", "evidence text"      # or "partly"/"no", or True/False, or {"answer", "evidence"}

A rubric question then uses it with {"id": "...", "text": "...", "check": "my_check", "args": {"limit": 3}}.
Checks never call a model and never spend."""
