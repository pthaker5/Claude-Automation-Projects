import numpy as np
import pandas as pd
import pytest

from quantlab.data import load_prices, synthetic_prices
from quantlab.metrics import log_returns


class TestSyntheticPrices:
    def test_deterministic_given_seed(self):
        a = synthetic_prices(["X", "Y"], "2020-01-01", "2021-12-31", seed=42)
        b = synthetic_prices(["X", "Y"], "2020-01-01", "2021-12-31", seed=42)
        pd.testing.assert_frame_equal(a, b)

    def test_different_seeds_differ(self):
        a = synthetic_prices(["X"], "2020-01-01", "2020-12-31", seed=1)
        b = synthetic_prices(["X"], "2020-01-01", "2020-12-31", seed=2)
        assert not a.equals(b)

    def test_shape_and_positivity(self):
        df = synthetic_prices(["A", "B", "C"], "2020-01-01", "2020-06-30", seed=0)
        assert list(df.columns) == ["A", "B", "C"]
        assert (df > 0).all().all()
        assert df.index.equals(pd.bdate_range("2020-01-01", "2020-06-30"))

    def test_tickers_are_independent_paths(self):
        df = synthetic_prices(["A", "B"], "2015-01-01", "2024-12-31", seed=3)
        r = log_returns(df).dropna()
        assert abs(r["A"].corr(r["B"])) < 0.1  # independent draws, long sample

    def test_moments_match_requested_parameters(self):
        mu, sigma = 0.05, 0.20
        df = synthetic_prices(["A"] , "1990-01-01", "2024-12-31", seed=5, mu=mu, sigma=sigma)
        r = log_returns(df["A"]).dropna()
        ann_vol = r.std(ddof=1) * np.sqrt(252)
        ann_drift = r.mean() * 252
        assert ann_vol == pytest.approx(sigma, rel=0.05)
        # Log-return drift under GBM is mu - sigma^2/2, but the standard error of an annual
        # mean is sigma/sqrt(years) — huge relative to the drift itself (Module 00 §6: means
        # are hard to estimate). Assert within 3 standard errors, not a magic tolerance.
        years = len(r) / 252
        se_drift = sigma / np.sqrt(years)
        assert abs(ann_drift - (mu - sigma**2 / 2)) < 3 * se_drift

    def test_empty_range_raises(self):
        with pytest.raises(ValueError):
            synthetic_prices(["A"], "2020-01-04", "2020-01-05", seed=0)  # Sat-Sun


class TestLoadPricesCache:
    def test_reads_from_cache_without_network(self, tmp_path):
        # Pre-seed the cache exactly as load_prices writes it; a cache hit must not
        # require yfinance at all.
        idx = pd.bdate_range("2024-01-01", periods=5)
        cached = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx, name="FAKE")
        path = tmp_path / "FAKE_2024-01-01_2024-01-08.csv"
        cached.to_frame().to_csv(path)

        df = load_prices(["FAKE"], start="2024-01-01", end="2024-01-08", cache_dir=tmp_path)
        assert list(df.columns) == ["FAKE"]
        assert df["FAKE"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
        assert isinstance(df.index, pd.DatetimeIndex)

    def test_cache_miss_offline_raises_runtime_error(self, tmp_path, monkeypatch):
        # Simulate "no yfinance installed": the import inside _download_one must fail.
        import builtins

        real_import = builtins.__import__

        def no_yfinance(name, *args, **kwargs):
            if name == "yfinance":
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_yfinance)
        with pytest.raises(RuntimeError, match="MISSING"):
            load_prices(["MISSING"], start="2024-01-01", end="2024-01-08", cache_dir=tmp_path)

    def test_multiple_cached_tickers_align(self, tmp_path):
        idx = pd.bdate_range("2024-01-01", periods=4)
        for name, vals in {"AA": [1, 2, 3, 4], "BB": [10, 20, 30, 40]}.items():
            pd.Series(vals, index=idx, name=name, dtype=float).to_frame().to_csv(
                tmp_path / f"{name}_2024-01-01_2024-01-05.csv"
            )
        df = load_prices(["AA", "BB"], start="2024-01-01", end="2024-01-05", cache_dir=tmp_path)
        assert df.shape == (4, 2)
        assert df["BB"].iloc[-1] == 40.0
