"""TrendHolder — a patient trend-riding bot for cbBTC (CBBTC/USDC).

Why this shape: the dev window is a slow grind up (+3.6% with only a 2%
worst pullback) and 312 of its 1,440 bars are flat. On such a window every
frequent-trading design loses to its own costs — a full-size round trip pays
about 46 bps in fees, slippage and pool impact, and the 1-minute noise is
only about +/-11 bps. The bots that won the 17 November edition of this
race did the opposite of frenzy: 2-8 patient trades, small drawdowns. So
this bot trades rarely and holds the trend:

- Enter: once the close is above the slow EMA (120 bars), buy with the full
  equity. One position at a time, no leverage, no shorts.
- Hold: while the trend holds, do nothing. Flat bars and small pullbacks
  are noise, not signals.
- Exit on a real break only, whichever comes first:
  * the close falls 100 bps below the slow EMA (the trend itself broke),
  * the close falls 250 bps below the trailing 120-bar high (wide trailing
    stop, wider than this window's whole worst pullback),
  * the close falls 200 bps below the average cost (a hard stop on the
    position itself).
- Re-enter: after a 60-bar cooldown, if the close is back above the slow
  EMA, buy again. In a choppy window this keeps the bot out of whipsaw.
- Guardrail hedge: if no trade has happened by bar 1300 and the last hour
  fell less than 50 bps, take one small (20%) position, so the entry still
  meets the race's minimum of one trade even in a window that never trends.
- Deterministic: every decision is a pure function of the bars seen so far.
  No clock, no environment, no randomness, no network.

Money is integer micro-USDC (quote units); prices are integers at
price_scale 5, quantities at qty_scale 8. The replay fills an order decided
on bar k at bar k+1's open, so every signal uses the latest close.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# Tuned on the frozen dev window (local replay): +$31.09, 1 trade, max
# drawdown 198 bps. The exits never fired there, so the margin is the whole
# rise, not a knife-edge parameter.
PARAMS = {
    "ema_slow": 120,        # regime EMA length, in bars
    "break_bps": 100,       # exit when close is this far below the slow EMA
    "trail_bps": 250,       # exit when close is this far below the trailing high
    "high_bars": 120,       # trailing-high lookback, in bars
    "sl_cost_bps": 200,     # exit when close is this far below average cost
    "cooldown": 60,         # bars to wait after a sell before re-entering
    "size_bps": 10000,      # equity share per buy, in bps (10000 = 100%)
    "hedge_bar": 1300,      # bar after which the guardrail hedge may fire
    "hedge_size_bps": 2000, # hedge position size, in bps of equity
    "hedge_max_drop_bps": 50,  # hedge only if the last 60 bars fell less than this
    "max_slippage_bps": 200,   # slippage cap on every order
}


class TrendHolder:
    """Stateful trend-riding bot; one instance lives for the whole window."""

    def __init__(self, params=None):
        self.p = dict(PARAMS)
        if params:
            self.p.update(params)
        self.closes = []       # closes seen, ints
        self.ema_slow = None   # slow EMA of closes, float
        self.cool_until = -1   # first bar index allowed to buy again
        self.trades = 0        # filled orders seen in the batches' fills
        self.hedged = False

    # -- helpers ---------------------------------------------------------
    def _avg_cost_price(self, state):
        """Average cost of the held position, in price units (or None)."""
        holding = state.positions.get(SYMBOL)
        if holding is None or holding.qty <= 0:
            return None
        # cost (micro-USDC) -> price units: cost * 10^(qty+price) / (qty * 10^quote)
        return holding.cost * 10 ** 7 // holding.qty

    def _buy(self, state, bps_of_equity):
        room = state.weight_room(SYMBOL)
        spend = min(state.cash, state.equity * bps_of_equity // 10000, room)
        if spend < 1_000_000:  # below the 1 USDC minimum notional
            return None
        return {
            "side": "buy",
            "symbol": SYMBOL,
            "notional_quote_units": spend,
            "max_slippage_bps": self.p["max_slippage_bps"],
        }

    def _sell_all(self, state):
        holding = state.positions.get(SYMBOL)
        if holding is None or holding.qty <= 0:
            return None
        return {
            "side": "sell",
            "symbol": SYMBOL,
            "qty": holding.qty,
            "max_slippage_bps": self.p["max_slippage_bps"],
        }

    # -- decision --------------------------------------------------------
    def on_batch(self, state, batch):
        if state.warming_up:
            return []
        close = state.close(SYMBOL)
        if close is None:
            return []
        p = self.p
        orders = []

        # Count filled trades from the fills this batch reports.
        for fill in batch.get("fills", []):
            if fill.get("status") == "filled":
                self.trades += 1

        # Record this close first: every later branch may return early.
        self.closes.append(close)
        n = len(self.closes)

        # Update the slow EMA with this close.
        if self.ema_slow is None:
            self.ema_slow = float(close)
        else:
            alpha = 2.0 / (p["ema_slow"] + 1)
            self.ema_slow = alpha * close + (1.0 - alpha) * self.ema_slow

        holding = state.positions.get(SYMBOL)
        in_position = holding is not None and holding.qty > 0

        # --- exit: only on a real break ---------------------------------
        if in_position:
            high = max(self.closes[-p["high_bars"]:])
            trail_price = high * (10000 - p["trail_bps"]) // 10000
            break_price = int(self.ema_slow * (10000 - p["break_bps"]) // 10000)
            avg_cost = self._avg_cost_price(state)
            stop_price = avg_cost * (10000 - p["sl_cost_bps"]) // 10000
            if close < trail_price or close < break_price or close <= stop_price:
                order = self._sell_all(state)
                if order is not None:
                    orders.append(order)
                    self.cool_until = n + p["cooldown"]
                    return orders
            return orders

        # --- entry: buy the uptrend -------------------------------------
        if n >= p["ema_slow"] and n > self.cool_until:
            if close > int(self.ema_slow):
                order = self._buy(state, p["size_bps"])
                if order is not None:
                    orders.append(order)
                    return orders

        # --- guardrail hedge: one small trade late, only in calm water --
        if (
            self.trades == 0
            and not self.hedged
            and n >= p["hedge_bar"]
            and n >= 61
        ):
            drop_bps = (self.closes[-61] - close) * 10000 // self.closes[-61]
            if drop_bps <= p["hedge_max_drop_bps"]:
                order = self._buy(state, p["hedge_size_bps"])
                if order is not None:
                    orders.append(order)
                    self.hedged = True
                    return orders

        return orders


_BOT = TrendHolder()


def on_batch(state, batch):
    return _BOT.on_batch(state, batch)


if __name__ == "__main__":
    makefun_bars.run(on_batch)
