"""Return and risk metrics. Pure, vectorized, and explicit about conventions.

Conventions (stated once, relied on everywhere):
- Input "prices" are levels; input "returns" are per-period simple returns unless a function
  says log. Works on Series or DataFrame alike via pandas broadcasting.
- Annualization assumes ``periods_per_year`` equally-spaced observations (252 for daily).
- Sample statistics use ddof=1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def simple_returns(prices: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Per-period simple returns P_t / P_{t-1} - 1. First row is NaN by construction."""
    return prices / prices.shift(1) - 1.0


def log_returns(prices: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Per-period log returns ln(P_t / P_{t-1}). Additive across time, ideal for aggregation."""
    return np.log(prices / prices.shift(1))


def annualized_return(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    """Geometric annualized return from simple returns: compounding, not mean*252."""
    r = returns.dropna()
    if len(r) == 0:
        return np.nan
    total = float((1.0 + r).prod())
    if total <= 0:  # a -100% period makes geometric annualization meaningless
        return -1.0
    return total ** (periods_per_year / len(r)) - 1.0


def annualized_vol(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    """Sample std (ddof=1) scaled by sqrt(periods). Assumes serially uncorrelated returns —
    an assumption that volatility clustering violates; fine as a first-order summary."""
    r = returns.dropna()
    if len(r) < 2:
        return np.nan
    return float(r.std(ddof=1)) * np.sqrt(periods_per_year)


def sharpe_ratio(
    returns: pd.Series,
    rf_annual: float = 0.0,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """Annualized Sharpe: mean excess return over its std, scaled by sqrt(periods).

    ``rf_annual`` is de-annualized arithmetically (rf/periods) — adequate at realistic rates.
    Remember what this number is NOT: it says nothing about tails, autocorrelation, or how many
    configurations were tried to find it. Deflation lives in Module 06.
    """
    r = returns.dropna()
    if len(r) < 2:
        return np.nan
    excess = r - rf_annual / periods_per_year
    sd = float(excess.std(ddof=1))
    # A constant series has zero variance mathematically but ~1e-18 in floating point;
    # no real strategy has per-period vol below 1e-15, so treat that as degenerate.
    if sd < 1e-15:
        return np.nan
    return float(excess.mean()) / sd * np.sqrt(periods_per_year)


def drawdown_series(prices_or_equity: pd.Series) -> pd.Series:
    """Drawdown at each point: level / running max - 1. Always <= 0; 0 at new highs."""
    running_max = prices_or_equity.cummax()
    return prices_or_equity / running_max - 1.0


def max_drawdown(prices_or_equity: pd.Series) -> float:
    """Most negative drawdown over the sample (e.g. -0.25 for a 25% peak-to-trough loss)."""
    dd = drawdown_series(prices_or_equity.dropna())
    if len(dd) == 0:
        return np.nan
    return float(dd.min())
