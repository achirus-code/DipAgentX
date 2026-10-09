"""Lead-lag monitor: BTC jumps are detected for every coin, follow-ups and summary are right, everything survives a
restart, and the measurement can be cleaned up."""

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import leadlag
from app.db import Database

COINS = ("BTC", "ETH", "SOL")


def binance(btc: float, eth: float, sol: float) -> dict:
    return {"BTCUSDT": (btc - 0.5, btc + 0.5), "ETHUSDT": (eth - 0.05, eth + 0.05), "SOLUSDT": (sol - 0.01, sol + 0.01)}


def revx(btc: float, eth: float, sol: float) -> dict:
    return {"BTC-EUR": (btc - 1, btc + 1), "ETH-EUR": (eth - 0.1, eth + 0.1), "SOL-EUR": (sol - 0.02, sol + 0.02)}


def feed(mon, t, btc, eth, sol, r_btc=None, r_eth=None, r_sol=None):
    mon.observe_binance(t, binance(btc, eth * 1.15, sol * 1.15))
    mon.observe_revx(t, revx(r_btc or btc * 0.86, r_eth or eth, r_sol or sol))
    return mon.check(t)


def monitor(db: Database, clock=lambda: 0.0) -> leadlag.LeadLagMonitor:
    mon = leadlag.LeadLagMonitor(db, clock=clock, coins=COINS)
    mon.start(clock())
    return mon


def jump(mon, t0: float) -> dict:
    """A quiet minute, then BTC +0.6 % in 60 s: ETH lags on Revolut X, BTC-EUR follows at once, SOL lags too."""
    for k in range(31):
        assert feed(mon, t0 + 2 * k, 100_000, 2000, 150) is None
    return feed(mon, t0 + 62, 100_600, 2001, 150.1, r_btc=100_600 * 0.86)


def test_a_btc_jump_is_measured_for_every_coin_and_followed_up(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    mon = monitor(db)
    event = jump(mon, 1_000_000.0)
    t = 1_000_062.0
    assert event["direction"] == "up" and event["btc_usdt_jump_pct"] == pytest.approx(0.6, abs=0.01)
    assert set(event["coins"]) == {"BTC-EUR", "ETH-EUR", "SOL-EUR"}
    assert event["coins"]["ETH-EUR"]["lagged"] is True and event["coins"]["BTC-EUR"]["lagged"] is False
    assert feed(mon, t + 30, 100_700, 2002, 150.2) is None  # no second event within 5 minutes
    feed(mon, t + 61, 100_700, 2006, 150.5)
    feed(mon, t + 301, 100_700, 2010, 151)
    feed(mon, t + 901, 100_700, 2012, 151)
    stored = leadlag.normalize(db.list_leadlag_events()[0])
    assert stored["status"] == "complete" and not mon.open
    eth = stored["coins"]["ETH-EUR"]["follow_ups"]["900"]
    assert eth["revx_mid_pct"] == pytest.approx((2012 / 2001 - 1) * 100, abs=0.001)
    assert eth["revx_taker_round_trip_pct"] == pytest.approx((2011.9 / 2001.1 - 1) * 100, abs=0.001)
    assert stored["btc_follow_ups"]["900"] == pytest.approx((100_700 / 100_600 - 1) * 100, abs=0.001)
    summary = mon.summary()
    key = summary["key_figures_0_5pct_lagged"]["ETH-EUR"]
    assert key["events"] == 1 and key["revx_15min_avg_pct"] == pytest.approx(0.55, abs=0.01)
    assert summary["events_complete"] == 1 and summary["key_figures_0_5pct_lagged"]["BTC-EUR"]["events"] == 0


def test_counters_and_open_events_survive_a_restart(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    now = {"t": 1_000_000.0}
    mon = monitor(db, lambda: now["t"])
    jump(mon, 1_000_000.0)
    mon._error("binance", 1_000_062.0)
    mon._save_state(force=True)
    first = mon.state["first_started_at"]
    # restart 2 minutes later: the 1-minute follow-up was missed -> interrupted
    now["t"] = 1_000_062.0 + 120
    mon2 = monitor(db, lambda: now["t"])
    s = mon2.summary()
    assert s["restarts"] == 1 and s["measuring_since"] == first and s["errors"]["binance"] == 1
    assert s["events_interrupted"] == 1 and not mon2.open
    # the 5-minute gap still holds after the restart (last jump persisted)
    assert mon2.state["last_event_at"] == int(1_000_062.0 * 1000)


def test_an_open_event_is_resumed_when_nothing_was_missed(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    mon = monitor(db)
    jump(mon, 1_000_000.0)
    t = 1_000_062.0
    feed(mon, t + 61, 100_700, 2006, 150.5)  # 1-minute follow-up taken, then restart
    mon2 = monitor(db, lambda: t + 100)
    assert len(mon2.open) == 1
    for dt in (301, 901):
        mon2.observe_binance(t + dt, binance(100_700, 2010 * 1.15, 151 * 1.15))
        mon2.observe_revx(t + dt, revx(100_700 * 0.86, 2010, 151))
        mon2.check(t + dt)
    assert leadlag.normalize(db.list_leadlag_events()[0])["status"] == "complete"


def test_cleanup(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    for at, status in ((1000, "complete"), (2000, "interrupted"), (3000, "complete")):
        db.add_leadlag_event(at, {"at": at, "direction": "up", "btc_usdt_jump_pct": 0.5, "status": status,
                                  "btc_follow_ups": {}, "coins": {}})
    # an event from 1.35.1 (ETH only, flat) that never got its follow-ups counts as interrupted
    db.add_leadlag_event(1500, {"at": 1500, "direction": "up", "btc_usdt_jump_pct": 0.4, "follow_ups": {}})
    mon = monitor(db, lambda: 5.0)
    mon.state["restarts"] = 4
    assert mon.cleanup("interrupted")["deleted"] == 2
    assert mon.state["restarts"] == 4
    assert mon.cleanup("before", before=2500)["deleted"] == 1
    assert [e["at"] for e in db.list_leadlag_events()] == [3000]
    out = mon.cleanup("all")
    assert out["deleted"] == 1 and out["counters_reset"] and mon.state["restarts"] == 0
    assert json.loads(json.dumps(db.get_setting(leadlag.STATE_KEY)))["first_started_at"] == 5000
    with pytest.raises(ValueError):
        mon.cleanup("before")


def test_small_moves_and_short_history_are_ignored(tmp_path: Path):
    mon = monitor(Database(tmp_path / "t.db"))
    assert feed(mon, 0, 100_000, 2000, 150) is None
    assert feed(mon, 30, 101_000, 2000, 150) is None  # +1 % but not a full 60-second window yet
    mon = monitor(Database(tmp_path / "t2.db"))
    for k in range(40):
        assert feed(mon, 100 + 2 * k, 100_000 + k, 2000, 150) is None  # +0.04 %: below 0.3 %


async def test_the_loop_survives_failing_feeds_and_counts_errors(tmp_path: Path, monkeypatch):
    async def broken(_symbols):
        raise RuntimeError("offline")

    async def stop(_):
        raise SystemExit

    db = Database(tmp_path / "t.db")
    mon = leadlag.LeadLagMonitor(db, broken, broken, coins=COINS)
    monkeypatch.setattr(leadlag.asyncio, "sleep", stop)
    with pytest.raises(SystemExit):
        await mon.run()
    assert mon.summary()["errors"] == {"binance": 1, "revolutx": 1}


def test_coins_from_env(monkeypatch):
    monkeypatch.setenv("LEADLAG_COINS", "eth, sol,ETH")
    assert leadlag.coins_from_env() == ("ETH", "SOL")
    monkeypatch.delenv("LEADLAG_COINS")
    assert leadlag.coins_from_env() == leadlag.DEFAULT_COINS


def test_endpoints(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("API_TOKEN", "t")
    monkeypatch.setenv("EXCHANGE", "mock")
    import app.main as main
    main = importlib.reload(main)
    auth = {"Authorization": "Bearer t"}
    with TestClient(main.app) as client:
        body = client.get("/api/research/leadlag", headers=auth).json()
        assert body["enabled"] is False and body["events"] == [] and "ETH-EUR" in body["by_coin"]
        assert client.delete("/api/research/leadlag?scope=interrupted", headers=auth).json()["deleted"] == 0
        assert client.delete("/api/research/leadlag?scope=before", headers=auth).status_code == 400
        assert client.delete("/api/research/leadlag?scope=nope", headers=auth).status_code == 422
        assert client.delete("/api/research/leadlag?scope=all").status_code == 401
