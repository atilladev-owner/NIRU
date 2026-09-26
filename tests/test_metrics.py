import numpy as np
import pandas as pd
import pytest

from niru.metrics import nav, period, trade_stats

DAY = 86_400_000
D0 = 1_577_836_800_000


def test_nav_ignores_deposits():
    eq = np.array([100, 110, 190, 190.0])
    dep = np.array([100, 100, 180, 180.0])
    v = nav(eq, dep)
    assert v[1] == pytest.approx(1.10)
    assert v[2] == pytest.approx(1.10)  # $80 bought units at 1.10


def test_period_pnl_and_drawdown():
    days = D0 + np.arange(4) * DAY
    eq = np.array([100, 110, 99, 105.0])
    dep = np.full(4, 100.0)
    s = period(days, eq, dep, D0, D0 + 4 * DAY)
    assert s["pnl_usd"] == pytest.approx(5.0)
    assert s["pnl_pct"] == pytest.approx(0.05)
    assert s["dd_usd"] == pytest.approx(11.0)
    assert s["dd_pct"] == pytest.approx(1 - 99 / 110)


def test_trade_stats():
    t = pd.DataFrame({"pnl": [3.0, -1.0, 2.0], "fees": [0.1] * 3, "funding": [1.0] * 3,
                      "payments": [3, 3, 3], "positive": [3, 2, 3]})
    s = trade_stats(t)
    assert s["positions"] == 3
    assert s["accuracy"] == pytest.approx(2 / 3)
    assert s["profit_factor"] == pytest.approx(5.0)
    assert s["payment_accuracy"] == pytest.approx(8 / 9)
