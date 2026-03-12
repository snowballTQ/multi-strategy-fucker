# Strategy Workbench

`Strategy Workbench` is a separate, config-driven backtesting project for testing more complex rule sets than a simple one-strategy script.

Quick links:

- GitHub: [snowballTQ/multi-strategy-fucker](https://github.com/snowballTQ/multi-strategy-fucker)
- Colab: [Open in Colab](https://colab.research.google.com/github/snowballTQ/multi-strategy-fucker/blob/main/strategy_workbench_colab.ipynb)

The Colab notebook is set up as a guided form with Korean-friendly field labels:

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

## Using the Colab form

The Colab notebook is designed so most people do not need to edit a raw config dictionary.

The user-facing fields are now written in Korean. The engine still converts them to the internal English config format automatically.

### 1. Common settings

- `시작일`, `종료일`
  - backtest date range
- `편도수수료`
  - one-way commission as a decimal
  - example: `0.001` = 0.10%
- `세율`
  - tax rate
  - example: `0.22` = 22%
- `연운용보수`
  - annual expense ratio assumption
- `차입스프레드`
  - borrow spread added on top of the funding rate assumption
- `결과폴더이름`
  - folder name for the run outputs

### 2. Strategy slots

The notebook includes three strategy slots out of the box:

- `전략 1`
- `전략 2`
- `전략 3`

Each slot can be enabled or disabled independently.

That means you can:

- run only one strategy
- compare two strategies side by side
- compare three strategies in one pass

### 3. What is a dropdown vs a number input

Dropdown-style inputs:

- `기준시계열`
- `전량청산후자금`
- `진입결합`
- `청산결합`
- `진입규칙X_유형`
- `청산규칙X_유형`
- `진입규칙X_기준`
- `청산규칙X_기준`
- `익절 자금이동`
- `트레일링 자금이동`

Numeric inputs:

- leverage
- moving-average windows
- take-profit trigger multiples
- take-profit sell fractions
- trailing-stop drawdown values

### 4. How the period fields work

The same form uses `기간1`, `기간2`, and `기간3` for different rule types.

- `가격>SMA`, `가격<SMA`
  - use `기간1` only
  - example: `기간1 = 200`
- `빠른선>느린선`, `빠른선<느린선`
  - use `기간1 = fast`, `기간2 = slow`
  - example: `50`, `200`
- `이평선정배열`, `이평선역배열`
  - use `기간1 / 기간2 / 기간3` in order
  - example: `3`, `161`, `185`
- `항상참`
  - ignores the period fields
- `사용안함`
  - use this to disable rule 2
  - leave the unused periods as `0`

### 5. Combine modes

- `규칙1만`
  - use only rule 1
- `둘다만족`
  - both rules must be true
- `하나만만족`
  - either rule can be true

### 6. Partial exits

Each strategy slot includes up to three take-profit steps:

- `1차익절`
- `2차익절`
- `3차익절`

For each one you can set:

- whether it is enabled
- the trigger multiple
- the sell fraction
- the destination asset

Example:

- `1차익절_배수 = 1.15`
- `1차익절_매도비율 = 0.50`
- `1차익절_자금이동 = 현금`

This means:

- when the position reaches +15%
- sell 50% of the remaining position
- send the proceeds to cash

### 7. Trailing stop

Each strategy slot also includes trailing-stop controls:

- `전략X_트레일링사용`
- `전략X_트레일링_첫익절후활성`
- `전략X_트레일링_하락폭`
- `전략X_트레일링_자금이동`

Example:

- `전략X_트레일링사용 = True`
- `전략X_트레일링_첫익절후활성 = True`
- `전략X_트레일링_하락폭 = 0.15`

This means:

- trailing stop is active
- it turns on only after the first take-profit
- the remaining position is closed if it falls 15% from its post-activation peak

### 8. Common starter setups

Price vs 200 SMA:

- `진입규칙1_유형 = 가격>SMA`
- `진입규칙1_기간1 = 200`
- `청산규칙1_유형 = 가격<SMA`
- `청산규칙1_기간1 = 200`

Dual-SMA crossover:

- `진입규칙1_유형 = 빠른선>느린선`
- `진입규칙1_기간1 = 50`
- `진입규칙1_기간2 = 200`
- `청산규칙1_유형 = 빠른선<느린선`
- `청산규칙1_기간1 = 50`
- `청산규칙1_기간2 = 200`

3-161-185 chain:

- `진입결합 = 둘다만족`
- `진입규칙1_유형 = 가격>SMA`
- `진입규칙1_기간1 = 200`
- `진입규칙2_유형 = 이평선정배열`
- `진입규칙2_기간1 = 3`
- `진입규칙2_기간2 = 161`
- `진입규칙2_기간3 = 185`

### 9. Practical tips

- Start with one or two strategies before turning on all three slots.
- Leave `사용안함` on rule 2 if you do not need a second rule.
- For `빠른선>느린선`, the natural pattern is usually `기간1 < 기간2`.
- If you are not sure where proceeds should go after a sale, start with `현금`.
- The notebook form omits `confirm_days` on purpose to keep the UI simpler.

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
        "window": 200
      },
      "exit": {
        "type": "price_below_sma",
        "source": "traded",
        "window": 200
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
