# Strategy Workbench

`Strategy Workbench` is a separate, config-driven backtesting project for testing more complex rule sets than a simple one-strategy script.

Quick links:

- GitHub: [snowballTQ/multi-strategy-fucker](https://github.com/snowballTQ/multi-strategy-fucker)
- Colab: [Open in Colab](https://colab.research.google.com/github/snowballTQ/multi-strategy-fucker/blob/main/strategy_workbench_colab.ipynb)

The Colab notebook is set up as a guided form:

- dates use calendar pickers
- leverage, windows, take-profit levels, and trailing-stop values are numeric inputs
- base series, rule types, sources, and destinations are dropdowns
- three strategy slots are provided out of the box

It is built for cases like:

- comparing two or more strategies in the same run
- testing multi-moving-average rules such as `3-161-185`
- adding partial exits with configurable sell ratios
- sending proceeds to `cash`, `SGOV` proxy, `SPY` proxy, or `QQQ` proxy
- measuring Sharpe, Sortino, drawdowns, and trade-level behavior

## What works in the current MVP

The current version supports:

- multiple strategies in one config file
- `price_above_sma`
- `price_below_sma`
- `sma_chain_above`
- `sma_chain_below`
- `fast_above_slow`
- `fast_below_slow`
- composite rules with `all_of` and `any_of`
- partial exits with `trigger_gain_multiple` + `sell_fraction`
- post-sale destination routing into `cash`, `sgov`, `spy`, `qqq`, or `base`
- trailing stop after the first take-profit
- metrics including CAGR, MDD, Calmar, volatility, Sharpe, and Sortino
- output files for metrics, annual returns, drawdowns, equity curves, trades, and take-profit summaries

## Quick start

From the project root:

```bash
python run_workbench.py --config example_strategy_config.json --output-name demo_run
```

Outputs are written under:

```text
%USERPROFILE%\strategy_workbench_outputs\demo_run
```

## Example config shape

The top-level config contains global settings and a `strategies` list.

```json
{
  "start_date": "1985-10-01",
  "end_date": "2026-03-09",
  "commission_rate": 0.001,
  "tax_rate": 0.22,
  "expense_ratio": 0.0095,
  "borrow_spread": 1.0,
  "strategies": [
    {
      "name": "Price vs 200 SMA | 3x",
      "base_series": "ndx",
      "leverage": 3.0,
      "entry": {
        "type": "price_above_sma",
        "source": "traded",
        "window": 200,
        "confirm_days": 3
      },
      "exit": {
        "type": "price_below_sma",
        "source": "traded",
        "window": 200,
        "confirm_days": 1
      }
    }
  ]
}
```

## Supported base series

- `ndx`
- `spx`
- `composite_splice`

## Supported rule types

### Atomic rules

- `price_above_sma`
- `price_below_sma`
- `sma_chain_above`
- `sma_chain_below`
- `fast_above_slow`
- `fast_below_slow`
- `always_true`

### Composite rules

- `all_of`
- `any_of`

### Rule fields

- `source`
  - `traded` means the rule uses the actual traded series for that strategy
  - `base` means the rule uses the underlying base series
- `confirm_days`
  - consecutive days required before the rule is treated as active

## Partial exits

Each strategy can define a `take_profit_ladder` like this:

```json
[
  {
    "trigger_gain_multiple": 1.15,
    "sell_fraction": 0.50,
    "destination": "cash"
  },
  {
    "trigger_gain_multiple": 1.68,
    "sell_fraction": 0.35,
    "destination": "spy"
  }
]
```

This means:

- at `+15%`, sell `50%` of the remaining traded position
- at `+68%`, sell `35%` of the remaining traded position
- proceeds are routed to the destination asset immediately

Supported destinations:

- `cash`
- `sgov` (cash-yield proxy)
- `spy`
- `qqq`
- `base`

## Trailing stop

Trailing stop is optional and can be activated after the first take-profit.

```json
{
  "enabled": true,
  "activate_after_first_take_profit": true,
  "drawdown_from_peak": 0.15,
  "destination": "cash"
}
```

## Output files

Each run writes:

- `metrics.csv`
- `annual_returns.csv`
- `drawdowns.csv`
- `equity_curves.csv`
- `trades.csv`
- `take_profit_summary.csv`
- `config.json`

## Trade log notes

`trades.csv` includes:

- traded-asset entries
- traded-asset exits
- take-profit sells
- destination-asset buys
- destination-asset liquidations when the strategy rotates back in

This makes it much easier to review:

- how often entries never reached a profit-taking level
- which take-profit tiers were actually hit
- how often the strategy churned back out before any staged exit

## Project structure

```text
strategy_workbench/
  README.md
  example_strategy_config.json
  run_workbench.py
  requirements.txt
  strategy_workbench_colab.ipynb
  workbench/
    __init__.py
    analytics.py
    data_loader.py
    indicators.py
    rules.py
    runner.py
```

## Why this is separate from the lighter toolbox

This project is intentionally separate from a lightweight backtest helper.

The goal here is not just to reproduce one result quickly.
The goal is to make it easier to:

- test richer signal logic
- compare multiple strategies side by side
- inspect exits and whipsaw behavior
- expand later into parameter sweeps and more detailed rebalancing logic
