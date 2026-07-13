import numpy as np
import pandas as pd
import pytest

from quantlab.metrics import (
    TRADING_DAYS,
    annualized_return,
    annualized_vol,
    drawdown_series,
    log_returns,
    max_drawdown,
    sharpe_ratio,
    simple_returns,
)


@pytest.fixture
def prices():
    return pd.Series([100.0, 110.0, 121.0, 108.9], index=pd.bdate_range("2024-01-01", periods=4))


def test_simple_returns_hand_computed(prices):
    r = simple_returns(prices)
    assert np.isnan(r.iloc[0])
    assert r.iloc[1] == pytest.approx(0.10)
    assert r.iloc[2] == pytest.approx(0.10)
    assert r.iloc[3] == pytest.approx(-0.10)


def test_log_returns_hand_computed(prices):
    r = log_returns(prices)
    assert np.isnan(r.iloc[0])
    assert r.iloc[1] == pytest.approx(np.log(1.10))
    # log returns are additive: sum of per-period equals log of total
    assert r.iloc[1:].sum() == pytest.approx(np.log(prices.iloc[-1] / prices.iloc[0]))


def test_log_vs_simple_relationship(prices):
    s, l = simple_returns(prices).dropna(), log_returns(prices).dropna()
    assert np.allclose(np.log1p(s.to_numpy()), l.to_numpy())


def test_annualized_return_compounds():
    # +1% for 252 days: geometric annualization must give 1.01^252 - 1, not 252 * 1%
    r = pd.Series(np.full(TRADING_DAYS, 0.01))
    assert annualized_return(r) == pytest.approx(1.01**252 - 1)


def test_annualized_vol_matches_numpy():
    rng = np.random.default_rng(7)
    r = pd.Series(rng.normal(0, 0.01, 1000))
    assert annualized_vol(r) == pytest.approx(r.std(ddof=1) * np.sqrt(252))


def test_sharpe_matches_direct_formula():
    rng = np.random.default_rng(11)
    r = pd.Series(rng.normal(0.0005, 0.01, 2000))
    expected = r.mean() / r.std(ddof=1) * np.sqrt(252)
    assert sharpe_ratio(r) == pytest.approx(expected)


def test_sharpe_risk_free_reduces_sharpe_for_positive_returns():
    rng = np.random.default_rng(11)
    r = pd.Series(rng.normal(0.0005, 0.01, 2000))
    assert sharpe_ratio(r, rf_annual=0.05) < sharpe_ratio(r, rf_annual=0.0)


def test_sharpe_degenerate_cases():
    assert np.isnan(sharpe_ratio(pd.Series([0.01])))  # too short
    assert np.isnan(sharpe_ratio(pd.Series([0.01] * 100)))  # zero variance


def test_drawdown_hand_computed():
    equity = pd.Series([100.0, 120.0, 90.0, 100.0, 130.0])
    dd = drawdown_series(equity)
    assert dd.iloc[0] == 0.0  # at initial high
    assert dd.iloc[2] == pytest.approx(90 / 120 - 1)  # -25%
    assert dd.iloc[4] == 0.0  # new high
    assert (dd <= 1e-12).all()
    assert max_drawdown(equity) == pytest.approx(-0.25)


def test_metrics_broadcast_over_dataframe():
    df = pd.DataFrame(
        {"A": [100.0, 110.0, 121.0], "B": [50.0, 45.0, 49.5]},
        index=pd.bdate_range("2024-01-01", periods=3),
    )
    r = simple_returns(df)
    assert r.shape == df.shape
    assert r["B"].iloc[1] == pytest.approx(-0.10)
