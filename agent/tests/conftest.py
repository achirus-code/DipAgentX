import pytest

from app import cryptodata


@pytest.fixture(autouse=True)
def no_leadlag_monitor(monkeypatch):
    """The lead-lag monitor polls Binance every 2 s – never in tests that start the app."""
    monkeypatch.setenv("LEADLAG_MONITOR", "0")


@pytest.fixture(autouse=True)
def offline_cryptodata(monkeypatch):
    """No test reaches Binance, Bybit or Coin Metrics: funding and exchange flows are "not available" unless a test sets
    them."""

    async def unavailable(*args, **kwargs):
        return None

    monkeypatch.setattr(cryptodata, "funding", unavailable)
    monkeypatch.setattr(cryptodata, "exchange_inflow", unavailable)
    cryptodata.FUNDING.reset()
    cryptodata.BYBIT_FUNDING.reset()
    cryptodata.FLOWS.reset()
    cryptodata._funding_source.clear()
