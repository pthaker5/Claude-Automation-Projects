"""Module 00 exercise starter.

Fill in the TODOs. Keep every function pure and importable — the tutor will import and poke at
them during review, and some may graduate into lib/quantlab if they're good enough.

Run:  python ex_starter.py          (prints your tables)
      python -m pytest lib/tests    (quantlab itself must stay green)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.data import load_prices, synthetic_prices
from quantlab.metrics import log_returns

# --------------------------------------------------------------------------- #
# Exercise 1 — moments & tails
# --------------------------------------------------------------------------- #


def skewness(x: np.ndarray) -> float:
    """Sample skewness: E[(x-mu)^3] / sigma^3.

    TODO: implement with numpy only. Decide (and document) your ddof convention.
    """
    raise NotImplementedError


def excess_kurtosis(x: np.ndarray) -> float:
    """Sample excess kurtosis: E[(x-mu)^4] / sigma^4 - 3.

    TODO: implement with numpy only.
    """
    raise NotImplementedError


def tail_counts(x: np.ndarray, sigmas: tuple[float, ...] = (3.0, 5.0)) -> pd.DataFrame:
    """Observed vs normal-expected counts of |standardized x| > k for each k in `sigmas`.

    TODO: return a DataFrame with columns ['threshold', 'observed', 'expected_normal'].
    Hint: expected under normality = len(x) * P(|Z| > k). You may hardcode the two tail
    probabilities from the exercise sheet rather than importing scipy.
    """
    raise NotImplementedError


def moment_report(returns: pd.Series, label: str) -> dict:
    """Assemble mean, std (annualized too), skew, excess kurtosis for one return series."""
    # TODO: build the dict; keep raw (daily) and annualized where meaningful.
    raise NotImplementedError


# --------------------------------------------------------------------------- #
# Exercise 2 — CLT and aggregation
# --------------------------------------------------------------------------- #


def aggregate_nonoverlapping(returns: pd.Series, horizon: int) -> pd.Series:
    """Sum log returns over consecutive non-overlapping windows of `horizon` days.

    TODO: implement WITHOUT a python loop over windows. Hint: integer-divide a positional
    index to form group labels, then groupby-sum; drop the final partial window.
    """
    raise NotImplementedError


def kurtosis_decay_table(returns: pd.Series, horizons: tuple[int, ...] = (1, 5, 21, 63)) -> pd.DataFrame:
    """Excess kurtosis at each horizon, alongside the i.i.d. prediction kappa_daily / n."""
    # TODO
    raise NotImplementedError


# --------------------------------------------------------------------------- #
# Exercise 3 — covariance eigenstructure
# --------------------------------------------------------------------------- #

ETF_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "USO", "HYG"]


def eigen_report(returns: pd.DataFrame) -> dict:
    """Eigen-analysis of the correlation matrix of a returns panel.

    TODO: return {'eigenvalues': ..., 'explained_frac_top1': ..., 'top2_loadings': DataFrame}.
    Use np.linalg.eigvalsh / eigh (symmetric!), sorted descending. Document your NaN policy for
    the panel BEFORE computing anything.
    """
    raise NotImplementedError


def portfolio_variance_check(returns: pd.DataFrame) -> bool:
    """Verify w' Sigma w == var(portfolio series) for equal weights, via np.allclose."""
    # TODO — if this fails, suspect ddof or index alignment, not numpy.
    raise NotImplementedError


# --------------------------------------------------------------------------- #


def main() -> None:
    # Real data when online; synthetic fallback keeps you unblocked offline.
    try:
        spy = load_prices(["SPY"], start="2005-01-01", end="2024-12-31")["SPY"]
        source = "yfinance"
    except Exception as exc:  # noqa: BLE001 — offline fallback is deliberate here
        print(f"[data] falling back to synthetic GBM ({exc})")
        spy = synthetic_prices(["SPY"], start="2005-01-01", end="2024-12-31", seed=0)["SPY"]
        source = "synthetic"

    r = log_returns(spy).dropna()
    print(f"Loaded {len(r)} daily log returns from {source}.")

    # TODO: call your functions, print the three reports.


if __name__ == "__main__":
    main()
