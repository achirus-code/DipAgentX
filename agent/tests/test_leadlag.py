"""Lead-lag monitor: a BTC jump is detected, ETH's lag is noted, the follow-ups and the summary are right."""

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import leadlag
from app.db import Database


def quotes(btc: float, eth_usdt: float, eth_eur: float) -> dict:
    return {"BTCUSDT": (btc - 0.5, btc + 0.5), "ETHUSDT": (eth_usdt - 0.05, eth_usdt + 0.05),
            "ETHEUR": (eth_eur - 0.05, eth_eur + 0.05)}


def feed(mon: leadlag.LeadLagMonitor, t: float, btc: float, eth_eur: float, revx: float) -> dict | None:
    mon.observe_binance(t, quotes(btc, eth_eur * 1.15, eth_eur))
    mon.observe_revx(t, (revx - 0.1, revx + 0.1))
    return mon.check(t)


def test_a_btc_jump_with_lagging_eth_is_followed_up_for_15_minutes(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    mon = leadlag.LeadLagMonitor(db)
    t = 1_000_000.0
    for k in range(31):  # a quiet minute
        assert feed(mon, t + 2 * k, 100_000, 2000, 2000) is None
    t += 62
    event = feed(mon, t, 100_600, 2001, 2001)  # BTC +0.6 % in 60 s, ETH only +0.05 %
    assert event and event["direction"] == "up" and event["btc_usdt_jump_pct"] == pytest.approx(0.6, abs=0.01)
    assert event["eth_lagged"] is True and event["revx"]["same_minute_pct"] == pytest.approx(0.05, abs=0.01)
    assert feed(mon, t + 30, 100_700, 2002, 2002) is None  # no second event within 5 minutes
    feed(mon, t + 61, 100_700, 2006, 2006)
    feed(mon, t + 301, 100_700, 2010, 2010)
    feed(mon, t + 901, 100_700, 2012, 2012)
    stored = db.list_leadlag_events()[0]
    fu = stored["follow_ups"]
    assert set(fu) == {"60", "300", "900"} and not mon.open
    assert fu["900"]["revx_mid_pct"] == pytest.approx((2012 / 2001 - 1) * 100, abs=0.001)
    assert fu["900"]["revx_taker_round_trip_pct"] == pytest.approx((2011.9 / 2001.1 - 1) * 100, abs=0.001)
    assert fu["900"]["btc_usdt_pct"] == pytest.approx((100_700 / 100_600 - 1) * 100, abs=0.001)
    row = next(r for r in mon.summary()["by_threshold"] if r["btc_jump_min_pct"] == 0.5 and r["eth_lagged"])
    assert row["events"] == 1 and row["revx_15min_avg_pct"] == pytest.approx(0.55, abs=0.01)
    assert row["revx_spread_avg_pct"] == pytest.approx(0.01, abs=0.001)


def test_small_moves_and_short_history_are_ignored(tmp_path: Path):
    mon = leadlag.LeadLagMonitor(Database(tmp_path / "t.db"))
    assert feed(mon, 0, 100_000, 2000, 2000) is None
    assert feed(mon, 30, 101_000, 2000, 2000) is None  # +1 % but not a full 60-second window yet
    mon = leadlag.LeadLagMonitor(Database(tmp_path / "t2.db"))
    for k in range(40):
        assert feed(mon, 100 + 2 * k, 100_000 + k, 2000, 2000) is None  # +0.04 %: below 0.3 %


def test_without_revolut_x_quotes_binance_still_decides_the_lag(tmp_path: Path):
    mon = leadlag.LeadLagMonitor(Database(tmp_path / "t.db"))
    for k in range(31):
        mon.observe_binance(2 * k, quotes(100_000, 2300, 2000))
        mon.check(2 * k)
    mon.observe_binance(62, quotes(99_500, 2290, 1990))  # BTC −0.5 %, ETH −0.5 %: not lagging
    event = mon.check(62)
    assert event["direction"] == "down" and event["revx"] is None and event["eth_lagged"] is False


async def test_the_loop_survives_failing_feeds(tmp_path: Path, monkeypatch):
    calls = {"n": 0}

    async def broken():
        calls["n"] += 1
        raise RuntimeError("offline")

    async def stop(_):
        raise SystemExit

    mon = leadlag.LeadLagMonitor(Database(tmp_path / "t.db"), broken, broken)
    monkeypatch.setattr(leadlag.asyncio, "sleep", stop)
    with pytest.raises(SystemExit):
        await mon.run()
    assert calls["n"] == 2 and mon.summary()["errors"] == {"binance": 1, "revolutx": 1}


def test_endpoint(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("API_TOKEN", "t")
    monkeypatch.setenv("EXCHANGE", "mock")
    import app.main as main
    main = importlib.reload(main)
    with TestClient(main.app) as client:
        r = client.get("/api/research/leadlag", headers={"Authorization": "Bearer t"})
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False and body["events"] == [] and len(body["by_threshold"]) == 8
        assert client.get("/api/research/leadlag").status_code == 401
