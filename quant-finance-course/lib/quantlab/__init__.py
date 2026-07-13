"""quantlab — shared, tested toolkit for the quant-finance course.

Grows module by module:
- data:     price loaders (yfinance + local cache) and synthetic generators   [Module 00/02]
- metrics:  returns, risk and performance statistics                          [Module 00/05]
- backtest: event-driven backtesting engine                                   [Module 06 — not yet built]

Design rules (enforced in code review):
- Pure functions over stateful objects wherever possible.
- Vectorized numpy/pandas; no row loops.
- Deterministic: anything random takes an explicit seed.
- Nothing lands here without tests in lib/tests.
"""

__version__ = "0.1.0"

from quantlab import data, metrics  # noqa: F401
