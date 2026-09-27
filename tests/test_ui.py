import pandas as pd

import ui

FRI_CLOSE = pd.Timestamp("2026-09-25 20:04", tz="UTC").timestamp()   # 4:04 PM ET
MON_1431 = pd.Timestamp("2026-09-28 18:31", tz="UTC").timestamp()    # 2:31 PM ET


def test_open_market_shows_live_time():
    s = ui.price_stamp("REGULAR", MON_1431, checked_at=MON_1431)
    assert "Market open" in s and "02:31 PM ET" in s and "Mon, Sep 28, 2026" in s and "checked" in s


def test_closed_market_shows_last_close_date_and_time():
    s = ui.price_stamp("CLOSED", FRI_CLOSE)
    assert "Market closed" in s and "last close on Fri, Sep 25, 2026" in s and "04:04 PM ET" in s


def test_extended_hours_are_flagged():
    assert "extended-hours trading isn't included" in ui.price_stamp("POST", FRI_CLOSE)


def test_fallback_when_live_prices_missing():
    s = ui.price_stamp(None, None, fallback_date="2026-09-25")
    assert "Live prices unavailable" in s and "Fri, Sep 25, 2026" in s


def test_nothing_known_gives_empty_stamp():
    assert ui.price_stamp(None, None) == ""


def test_accepts_timestamps_too():
    assert "Market closed" in ui.price_stamp("CLOSED", pd.Timestamp("2026-09-25 20:04", tz="UTC"))
