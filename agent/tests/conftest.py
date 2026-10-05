import pytest

from app import macro


@pytest.fixture(autouse=True)
def offline_macro(monkeypatch):
    """No test reaches the ECB, the US Treasury or the Department of Labor: their data is "not available" unless a
    test sets it."""

    async def unavailable(*args, **kwargs):
        return None

    for name in ("euro_cash", "eurusd", "claims", "yield_curve"):
        monkeypatch.setattr(macro, name, unavailable)
    for feed in (macro.EURIBOR, macro.EURUSD, macro.CLAIMS, macro.CURVE):
        feed.reset()
