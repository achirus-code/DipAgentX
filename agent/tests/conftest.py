import pytest

from app import cryptodata, macro


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


@pytest.fixture(autouse=True)
def offline_cryptodata(monkeypatch):
    """No test reaches Binance or Coin Metrics: funding and exchange flows are "not available" unless a test sets them."""

    async def unavailable(*args, **kwargs):
        return None

    monkeypatch.setattr(cryptodata, "funding", unavailable)
    monkeypatch.setattr(cryptodata, "exchange_inflow", unavailable)
    cryptodata.FUNDING.reset()
    cryptodata.FLOWS.reset()
