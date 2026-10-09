"""Lead-lag bot: buys right after a BTC jump the coin hasn't followed, once per jump, sells after the holding time or
at the stop; the monitor hands the jump over and wakes the engine."""

from decimal import Decimal
from pathlib import Path

import pytest

from app import leadlag
from app.db import Database
from app.i18n import render
from tests.test_core import FakeExchange, make_engine, pos
from tests.test_leadlag import jump, monitor

MIN = 60_000


@pytest.fixture(autouse=True)
def signals(monkeypatch):
    monkeypatch.setenv("LEADLAG_MONITOR", "1")
    monkeypatch.setattr(leadlag, "_latest_signal", None)
    monkeypatch.setattr(leadlag, "_listeners", [])


def signal(at: int, jump_pct: float = 0.6, lagged: bool = True, direction: str = "up") -> dict:
    return {"at": at, "direction": direction, "btc_usdt_jump_pct": jump_pct,
            "coins": {"ETH-EUR": {"lagged": lagged, "same_minute_pct": 0.05}, "BTC-EUR": {"lagged": False, "same_minute_pct": 0.6}}}


def bot(db, **params):
    return db.create_bot("LL", "leadlag", "ETH-EUR", {"amount": 100, **params}, True, True)


async def test_buys_after_a_lagging_jump_once_and_sells_after_the_holding_time(tmp_path: Path):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = bot(db)
    await engine.tick()
    assert pos(db.get_bot(bot_id)) is None and "seit dem Start kein Sprung" in render(db.get_bot(bot_id)["status"], "de")
    leadlag.publish(signal(ex.now - 5_000))
    await engine.tick()
    b = db.get_bot(bot_id)
    assert pos(b) is not None
    ex.now += 5 * MIN
    await engine.tick()
    assert pos(db.get_bot(bot_id)) is not None and "Verkauf in 10 min" in render(db.get_bot(bot_id)["status"], "de")
    ex.price = Decimal("1999")  # a small loss: sold anyway when the time is up
    ex.now += 10 * MIN
    await engine.tick()
    assert pos(db.get_bot(bot_id)) is None
    ex.now += MIN
    await engine.tick()  # the same jump never buys twice
    assert pos(db.get_bot(bot_id)) is None


@pytest.mark.parametrize("sig", [
    signal(0, jump_pct=0.4),                   # below the threshold
    signal(0, lagged=False),                   # ETH already moved with BTC
    signal(0, direction="down", jump_pct=-0.8),
])
async def test_no_buy_without_a_valid_signal(tmp_path: Path, sig):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = bot(db)
    sig["at"] = ex.now - 5_000
    leadlag.publish(sig)
    await engine.tick()
    assert pos(db.get_bot(bot_id)) is None


async def test_too_old_signal_is_ignored_and_lagging_can_be_switched_off(tmp_path: Path):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    old = bot(db)
    leadlag.publish(signal(ex.now - 90_000))
    await engine.tick()
    assert pos(db.get_bot(old)) is None
    db2, engine2 = make_engine((tmp_path / "b").mkdir() or tmp_path / "b", ex)
    anyway = bot(db2, only_lagging=False)
    leadlag.publish(signal(ex.now - 5_000, lagged=False))
    await engine2.tick()
    assert pos(db2.get_bot(anyway)) is not None


async def test_stop_loss_sells_early(tmp_path: Path):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = bot(db)
    leadlag.publish(signal(ex.now - 5_000))
    await engine.tick()
    ex.price = Decimal("1960")
    ex.now += MIN
    await engine.tick()
    assert pos(db.get_bot(bot_id)) is None


async def test_a_coin_that_isnt_measured_says_so(tmp_path: Path):
    ex = FakeExchange("2000", "2000")
    db, engine = make_engine(tmp_path, ex)
    bot_id = db.create_bot("LL", "leadlag", "SOL-EUR", {"amount": 100}, True, True)
    leadlag.publish(signal(ex.now - 5_000))
    await engine.tick()
    assert "LEADLAG_COINS" in render(db.get_bot(bot_id)["status"], "en") and pos(db.get_bot(bot_id)) is None


def test_the_monitor_publishes_jumps_and_wakes_listeners(tmp_path: Path):
    woken = []
    leadlag.on_signal(lambda: woken.append(1))
    mon = monitor(Database(tmp_path / "t.db"))
    event = jump(mon, 1_000_000.0)
    sig = leadlag.latest_signal()
    assert woken == [1] and sig["at"] == event["at"] and sig["direction"] == "up"
    assert sig["coins"]["ETH-EUR"]["lagged"] is True and sig["coins"]["BTC-EUR"]["lagged"] is False
