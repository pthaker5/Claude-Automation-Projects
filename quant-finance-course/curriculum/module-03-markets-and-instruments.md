# Module 03 — Financial Markets & Instruments

**Status:** stub — deep material generated when you start it.
**Weight (QR):** ★★ (context; ★★★ for quant trader track)

## Learning objectives

- Explain how modern electronic markets actually work: venues, order types, matching engines,
  the limit order book, auctions, fragmentation, and who the participants are.
- Know the mechanics of equities, futures, and options well enough to model their costs:
  ticks, lots, margin, expiry/rolls, settlement, short-selling mechanics and borrow costs.
- Market microstructure basics: bid-ask spread decomposition, market impact, adverse selection,
  why the spread exists (inventory + information), simple impact models (square-root law).
- Turn all of the above into **defensible transaction-cost assumptions** for backtests.

## Topics

1. Market structure: exchanges, ECNs, dark pools, opening/closing auctions
2. The limit order book: order types, priority rules, reading L1/L2 data
3. Equities mechanics: corporate actions, indices, ETFs and the create/redeem mechanism
4. Futures: specs, margin, basis, roll yield, term structure
5. Options mechanics (pricing deferred to Module 07): contracts, moneyness, exercise, put-call parity
6. Microstructure: spread, impact, adverse selection; realistic cost & slippage modeling

## Deliverables (planned)

- Exercise: build the cost model used by later projects (spread + impact as a function of ADV),
  documented with sources and assumptions.
- Quiz incl. intuition questions ("why do spreads widen at the open?", "you must trade 5% of ADV —
  how do you think about impact?").
