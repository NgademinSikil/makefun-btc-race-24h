[![make.fun · btc-race-24h-20261123-0511](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![rank](https://make.fun/badge/btc-race-24h-20261123-0511/NgademinSikil/makefun-btc-race-24h/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![reward](https://make.fun/badge/btc-race-24h-20261123-0511/NgademinSikil/makefun-btc-race-24h/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)

# TrendHolder — a cbBTC trading bot for make.fun's BTC race

A long-only bot that trades Coinbase Wrapped BTC (cbBTC) against USDC on
1-minute on-chain bars, for the make.fun bounty
`btc-race-24h-20261123-0511` ("Race a BTC trading bot live for 24 hours").

## Strategy

The dev window is a slow grind up (+3.6% with only a 2% worst pullback)
and 312 of its 1,440 bars are flat. On such a window every frequent-trading
design loses to its own costs: a full-size round trip pays about 46 bps in
fees, slippage and pool impact, while the 1-minute noise is only about
+/-11 bps. The bots that won the 17 November edition of this race did the
opposite of frenzy: 2-8 patient trades, small drawdowns. So this bot trades
rarely and holds the trend:

- **Enter:** once the close is above the slow EMA (120 bars), buy with the
  full equity. One position at a time, no leverage, no shorts.
- **Hold:** while the trend holds, do nothing. Flat bars and small pullbacks
  are noise, not signals.
- **Exit on a real break only**, whichever comes first:
  - the close falls 100 bps below the slow EMA (the trend itself broke),
  - the close falls 250 bps below the trailing 120-bar high (a wide trailing
    stop, wider than this window's whole worst pullback),
  - the close falls 200 bps below the average cost (a hard stop on the
    position itself).
- **Re-enter:** after a 60-bar cooldown, if the close is back above the slow
  EMA, buy again.
- **Guardrail hedge:** if no trade has happened by bar 1300 and the last hour
  fell less than 50 bps, take one small (20%) position, so the entry still
  meets the race's minimum of one trade even in a window that never trends.

The bot is deterministic: every decision is a pure function of the bars seen
so far. No clock, no environment, no randomness, no network. Standard library
only (`vendor/makefun_bars.py` is the kit's own protocol shim, copied
byte-for-byte under `vendor/`).

## Dev-window result (local replay of the frozen dev window)

- Net PnL **+$31.09** after every fee, 1 trade, maximum drawdown 1.98%
- The exits never fired on the dev window, so the margin is the whole rise,
  not a knife-edge parameter: neighbouring settings (EMA 60-120 bars, break
  100 bps, trailing stop 200-300 bps, cost stop 150-300 bps) all score
  +$21 to +$31.
- For comparison, a plain buy-and-hold scores +$32.17 on the same window,
  and every frequent-trading variant tested (dip-buy grids, EMA-cross trend
  following) lost money to whipsaw and costs.

## Run it

The bot speaks `agent-fun/bars-replay/v1` on stdin/stdout:

```sh
python3 -P -s main.py
```

Grade it on the dev window with the kit's own grader:

```sh
node cli/makefun.mjs grade-local --kit <kit-dir> --bot <this-repo> --driver docker
```

## Bounty

- Bounty: https://make.fun/bounty/btc-race-24h-20261123-0511
- Pool: $50 for the top 10 (1st $12) — free to enter, no real money traded.

Built for make.fun — https://make.fun/r/ds1567x3?ref=ds1567x3
