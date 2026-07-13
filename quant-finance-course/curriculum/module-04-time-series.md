# Module 04 — Time Series Analysis

**Status:** stub — deep material generated when you start it.
**Weight (QR):** ★★★

## Learning objectives

- Model and forecast with ARIMA-class models, and explain why they rarely forecast *returns*
  but matter for understanding dependence structure.
- Model volatility properly: ARCH/GARCH family, volatility clustering, realized volatility;
  produce and *evaluate* vol forecasts (QLIKE, not just MSE).
- Test for cointegration (Engle–Granger, Johansen) and understand what it buys you for pairs
  and spread trading — and how easily it breaks out of sample.
- Detect regimes: rolling statistics, Markov switching intuition, structural breaks.

## Topics

1. Stationarity, autocorrelation, AR/MA/ARIMA; model selection without overfitting
2. Volatility: stylized facts, EWMA/RiskMetrics, GARCH(1,1) and friends, realized vol
3. Forecast evaluation: loss functions for vol, Diebold–Mariano tests
4. Cointegration and error-correction models; spread construction and half-life
5. Regime detection: rolling windows, CUSUM/structural breaks, Markov switching (intuition + practice)

## Deliverables (planned)

- Exercises on real data: fit GARCH(1,1) to an index, compare to EWMA and realized vol.
- Directly feeds **Project 3** (vol forecasting shootout) and **Project 5** (pairs).
