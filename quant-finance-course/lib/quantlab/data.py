"""Price data loading: yfinance with a local CSV cache, plus a synthetic GBM generator.

The cache-first design is deliberate: tests and offline work never touch the network, and a
downloaded dataset is frozen on disk so results stay reproducible even if the vendor restates
history. The cache key includes ticker and date range; delete files under the cache dir to force
a refresh.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data"


def _cache_path(cache_dir: Path, ticker: str, start: str, end: str) -> Path:
    safe = ticker.replace("/", "-").replace("^", "_")
    return cache_dir / f"{safe}_{start}_{end}.csv"


def load_prices(
    tickers: Sequence[str],
    start: str,
    end: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Daily adjusted close prices, one column per ticker, DatetimeIndex ascending.

    Cache-first: a ticker whose CSV exists under ``cache_dir`` is read from disk and the
    network is never touched for it. Cache misses are fetched via yfinance (auto-adjusted
    closes — dividends and splits folded in) and written back to the cache.

    Raises RuntimeError if a ticker can't be served from cache and yfinance is unavailable
    or returns nothing — callers that want to keep working offline should catch it and fall
    back to :func:`synthetic_prices`.

    Note the survivorship caveat: anything loaded by *today's* ticker list is a
    current-constituents universe. Fine for single liquid ETFs; a known bias for
    cross-sectional stock studies — say so in any write-up that uses it that way.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    series: dict[str, pd.Series] = {}
    for ticker in tickers:
        path = _cache_path(cache_dir, ticker, start, end)
        if use_cache and path.exists():
            s = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
        else:
            s = _download_one(ticker, start, end)
            s.to_frame(name=ticker).to_csv(path)
        s.index = pd.DatetimeIndex(s.index)
        series[ticker] = s.astype(float).sort_index().rename(ticker)

    df = pd.concat(series.values(), axis=1)
    df.index.name = "date"
    return df


def _download_one(ticker: str, start: str, end: str) -> pd.Series:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(
            f"{ticker}: not in cache and yfinance is not installed "
            "(pip install yfinance, or use synthetic_prices offline)"
        ) from exc

    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if raw is None or len(raw) == 0:
        raise RuntimeError(f"{ticker}: yfinance returned no data for {start}..{end}")
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):  # yfinance returns MultiIndex columns for some calls
        close = close.iloc[:, 0]
    return close.rename(ticker)


def synthetic_prices(
    tickers: Sequence[str],
    start: str,
    end: str,
    seed: int,
    mu: float = 0.06,
    sigma: float = 0.18,
    s0: float = 100.0,
) -> pd.DataFrame:
    """Geometric Brownian motion price paths on business days — the offline stand-in.

    ``mu`` and ``sigma`` are annualized (drift of log returns is mu - sigma^2/2, per GBM).
    Deterministic given ``seed``; each ticker gets an independent path derived from the same
    seed, so the panel as a whole is reproducible.

    By construction these paths have i.i.d. normal log returns — no fat tails, no volatility
    clustering. Module 00 Exercise 1 exploits exactly that contrast with real data.
    """
    index = pd.bdate_range(start=start, end=end)
    n = len(index)
    if n == 0:
        raise ValueError(f"empty business-day range {start}..{end}")

    rng = np.random.default_rng(seed)
    dt = 1.0 / 252.0
    drift = (mu - 0.5 * sigma**2) * dt
    shocks = rng.standard_normal((n, len(tickers))) * (sigma * np.sqrt(dt))
    log_paths = np.cumsum(drift + shocks, axis=0)
    prices = s0 * np.exp(log_paths)

    df = pd.DataFrame(prices, index=index, columns=list(tickers))
    df.index.name = "date"
    return df
