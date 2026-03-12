from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import analytics
from .data_loader import (
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    build_series_lookup,
    get_latest_value,
    load_rate_rows,
    normalize_series,
    resolve_base_rows,
)
from .indicators import IndicatorCache
from .rules import evaluate_rule_config


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_ROOT = Path.home() / "strategy_workbench_outputs"

DEFAULT_COMMISSION_RATE = 0.001
DEFAULT_TAX_RATE = 0.22
DEFAULT_EXPENSE_RATIO = 0.0095
DEFAULT_BORROW_SPREAD = 1.0


@dataclass
class RuntimeSettings:
    commission_rate: float = DEFAULT_COMMISSION_RATE
    tax_rate: float = DEFAULT_TAX_RATE
    expense_ratio: float = DEFAULT_EXPENSE_RATIO
    borrow_spread: float = DEFAULT_BORROW_SPREAD


@dataclass
class Position:
    shares: float = 0.0
    basis: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.shares > 1e-12


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def ensure_output_dir(name: str) -> Path:
    output_path = OUTPUT_ROOT / name
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


def interval_cash_multiplier(days: int, dff_percent: float) -> float:
    return math.exp((dff_percent / 100.0) * days / 360.0)


def annual_financing_rate(dff_percent: float, leverage: float, settings: RuntimeSettings) -> float:
    borrow_multiple = max(leverage - 1.0, 0.0)
    expense_ratio = settings.expense_ratio if leverage > 1.0 else 0.0
    return borrow_multiple * ((dff_percent + settings.borrow_spread) / 100.0) + expense_ratio


def interval_cost_multiplier(days: int, dff_percent: float, leverage: float, settings: RuntimeSettings) -> float:
    return math.exp(-annual_financing_rate(dff_percent, leverage, settings) * days / 360.0)


def build_leveraged_series(
    index_rows: list[tuple[date, float]],
    rate_dates: list[date],
    rate_map: dict[date, float],
    leverage: float,
    include_financing_cost: bool,
    settings: RuntimeSettings,
) -> list[tuple[date, float]]:
    synthetic: list[tuple[date, float]] = [(index_rows[0][0], 100.0)]
    for idx in range(1, len(index_rows)):
        prev_date, prev_close = index_rows[idx - 1]
        current_date, current_close = index_rows[idx]
        days = max((current_date - prev_date).days, 1)
        index_return = current_close / prev_close - 1.0
        gross_multiplier = max(1e-12, 1.0 + leverage * index_return)
        if include_financing_cost:
            rate = get_latest_value(prev_date, rate_dates, rate_map)
            gross_multiplier *= interval_cost_multiplier(days, rate, leverage, settings)
        synthetic.append((current_date, synthetic[-1][1] * gross_multiplier))
    return synthetic


def canonical_asset_name(name: str, base_series_name: str) -> str:
    lowered = name.lower()
    mapping = {
        "cash": "cash",
        "sgov": "cash",
        "spy": "spx",
        "spx": "spx",
        "qqq": "ndx",
        "ndx": "ndx",
        "base": base_series_name,
        "traded": "traded",
    }
    if lowered not in mapping:
        raise ValueError(f"Unsupported destination asset: {name}")
    return mapping[lowered]


def normalize_config(config: dict) -> dict:
    if "strategies" in config:
        return config

    global_keys = {
        "start_date",
        "end_date",
        "commission_rate",
        "tax_rate",
        "expense_ratio",
        "borrow_spread",
        "strategies",
        "output_name",
    }
    strategy_config = {key: value for key, value in config.items() if key not in global_keys}
    normalized = {key: value for key, value in config.items() if key in global_keys}
    normalized["strategies"] = [strategy_config]
    return normalized


def build_runtime_settings(config: dict) -> RuntimeSettings:
    return RuntimeSettings(
        commission_rate=float(config.get("commission_rate", DEFAULT_COMMISSION_RATE)),
        tax_rate=float(config.get("tax_rate", DEFAULT_TAX_RATE)),
        expense_ratio=float(config.get("expense_ratio", DEFAULT_EXPENSE_RATIO)),
        borrow_spread=float(config.get("borrow_spread", DEFAULT_BORROW_SPREAD)),
    )


def build_base_cache(
    *,
    start_date: date,
    end_date: date,
) -> dict[str, dict[str, object]]:
    cache: dict[str, dict[str, object]] = {}
    for name in ("ndx", "spx", "composite_splice"):
        rows = resolve_base_rows(DATA_DIR, name, start_date, end_date)
        normalized = normalize_series(rows)
        dates, value_map = build_series_lookup(normalized)
        cache[name] = {
            "raw_rows": rows,
            "normalized_rows": normalized,
            "dates": dates,
            "map": value_map,
        }
    return cache


def build_strategy_series(
    *,
    strategy: dict,
    settings: RuntimeSettings,
    base_cache: dict[str, dict[str, object]],
    rate_dates: list[date],
    rate_map: dict[date, float],
) -> dict[str, object]:
    base_series_name = strategy.get("base_series", "ndx")
    leverage = float(strategy.get("leverage", 1.0))
    include_financing_cost = bool(strategy.get("include_financing_cost", leverage > 1.0))

    base_rows = base_cache[base_series_name]["raw_rows"]
    base_series = base_cache[base_series_name]["normalized_rows"]
    if leverage <= 1.0:
        traded_series = base_series
    else:
        leveraged_rows = build_leveraged_series(
            base_rows,
            rate_dates,
            rate_map,
            leverage=leverage,
            include_financing_cost=include_financing_cost,
            settings=settings,
        )
        traded_series = normalize_series(leveraged_rows)

    traded_dates, traded_map = build_series_lookup(traded_series)
    series_by_name = {
        "traded": traded_series,
        "base": base_series,
        "ndx": base_cache["ndx"]["normalized_rows"],
        "spx": base_cache["spx"]["normalized_rows"],
        "composite_splice": base_cache["composite_splice"]["normalized_rows"],
    }
    series_lookup = {
        "traded": {"dates": traded_dates, "map": traded_map},
        "base": {"dates": base_cache[base_series_name]["dates"], "map": base_cache[base_series_name]["map"]},
        "ndx": {"dates": base_cache["ndx"]["dates"], "map": base_cache["ndx"]["map"]},
        "spx": {"dates": base_cache["spx"]["dates"], "map": base_cache["spx"]["map"]},
        "composite_splice": {
            "dates": base_cache["composite_splice"]["dates"],
            "map": base_cache["composite_splice"]["map"],
        },
    }

    return {
        "base_series_name": base_series_name,
        "series_by_name": series_by_name,
        "series_lookup": series_lookup,
    }


def simulate_strategy(
    *,
    strategy: dict,
    settings: RuntimeSettings,
    strategy_series: dict[str, object],
    rate_dates: list[date],
    rate_map: dict[date, float],
) -> dict[str, object]:
    name = strategy.get("name", "Unnamed Strategy")
    base_series_name = strategy_series["base_series_name"]
    series_by_name = strategy_series["series_by_name"]
    series_lookup = strategy_series["series_lookup"]
    traded_series = series_by_name["traded"]

    entry_config = strategy.get("entry", {"type": "always_true"})
    exit_config = strategy.get("exit", {"type": "always_true"})
    take_profit_ladder = sorted(
        strategy.get("take_profit_ladder", []),
        key=lambda row: float(row["trigger_gain_multiple"]),
    )
    trailing_config = strategy.get("trailing_stop", {"enabled": False})
    exit_destination = canonical_asset_name(strategy.get("exit_destination", "cash"), base_series_name)

    cache = IndicatorCache(series_by_name=series_by_name)
    entry_flags = evaluate_rule_config(entry_config, cache)
    exit_flags = evaluate_rule_config(exit_config, cache)

    cash = 1.0
    traded_position = Position()
    parked_positions: dict[str, Position] = {}
    realized_by_year: dict[int, float] = {}
    trade_rows: list[dict[str, object]] = []
    tp_counts = {str(float(row["trigger_gain_multiple"])): 0 for row in take_profit_ladder}

    equity_curve: list[tuple[date, float]] = [(traded_series[0][0], 1.0)]
    trades = 0
    entries = 0
    full_exits = 0
    take_profit_hits = 0
    entries_without_take_profit = 0
    days_in_market = 0

    entry_price: float | None = None
    current_entry_tp_hits = 0
    triggered_levels: set[float] = set()
    trailing_active = False
    trailing_peak_price: float | None = None

    def add_trade_row(
        *,
        row_date: date,
        action: str,
        asset: str,
        price: float,
        shares: float,
        gross_value: float,
        net_value: float,
        realized_gain: float,
        destination: str,
        note: str,
    ) -> None:
        trade_rows.append(
            {
                "strategy": name,
                "date": row_date.isoformat(),
                "action": action,
                "asset": asset,
                "price": f"{price:.6f}",
                "shares": f"{shares:.6f}",
                "gross_value": f"{gross_value:.6f}",
                "net_value": f"{net_value:.6f}",
                "realized_gain": f"{realized_gain:.6f}",
                "destination": destination,
                "note": note,
            }
        )

    def get_asset_price(asset_name: str, row_date: date) -> float:
        lookup = series_lookup[asset_name]
        return get_latest_value(row_date, lookup["dates"], lookup["map"])

    def total_parked_value(row_date: date) -> float:
        total = 0.0
        for asset_name, position in parked_positions.items():
            if position.is_open:
                total += position.shares * get_asset_price(asset_name, row_date)
        return total

    def total_portfolio_value(row_date: date, traded_price: float) -> float:
        return cash + traded_position.shares * traded_price + total_parked_value(row_date)

    def scale_portfolio(row_date: date, ratio: float) -> None:
        nonlocal cash
        cash *= ratio
        traded_position.shares *= ratio
        traded_position.basis *= ratio
        for position in parked_positions.values():
            position.shares *= ratio
            position.basis *= ratio
        add_trade_row(
            row_date=row_date,
            action="tax_scale",
            asset="portfolio",
            price=1.0,
            shares=ratio,
            gross_value=0.0,
            net_value=0.0,
            realized_gain=0.0,
            destination="cash",
            note="Applied proportional annual tax payment.",
        )

    def allocate_proceeds(destination: str, amount: float, row_date: date, note: str) -> None:
        nonlocal cash, trades
        if amount <= 0.0:
            return
        if destination == "cash":
            cash += amount
            return
        price = get_asset_price(destination, row_date)
        gross_purchase = amount / (1.0 + settings.commission_rate)
        shares = gross_purchase / price
        position = parked_positions.setdefault(destination, Position())
        position.shares += shares
        position.basis += amount
        trades += 1
        add_trade_row(
            row_date=row_date,
            action="buy_destination",
            asset=destination,
            price=price,
            shares=shares,
            gross_value=amount,
            net_value=amount,
            realized_gain=0.0,
            destination=destination,
            note=note,
        )

    def liquidate_parked_positions(row_date: date, note: str) -> None:
        nonlocal cash, trades
        for asset_name in list(parked_positions):
            position = parked_positions[asset_name]
            if not position.is_open:
                parked_positions.pop(asset_name, None)
                continue
            price = get_asset_price(asset_name, row_date)
            gross_sale = position.shares * price
            net_sale = gross_sale * (1.0 - settings.commission_rate)
            realized_gain = net_sale - position.basis
            realized_by_year[row_date.year] = realized_by_year.get(row_date.year, 0.0) + realized_gain
            cash += net_sale
            trades += 1
            add_trade_row(
                row_date=row_date,
                action="sell_destination",
                asset=asset_name,
                price=price,
                shares=position.shares,
                gross_value=gross_sale,
                net_value=net_sale,
                realized_gain=realized_gain,
                destination="cash",
                note=note,
            )
            parked_positions.pop(asset_name, None)

    def reset_entry_state() -> None:
        nonlocal entry_price, current_entry_tp_hits, trailing_active, trailing_peak_price, triggered_levels
        entry_price = None
        current_entry_tp_hits = 0
        triggered_levels = set()
        trailing_active = False
        trailing_peak_price = None

    def mark_full_exit_without_tp_if_needed() -> None:
        nonlocal entries_without_take_profit
        if entry_price is not None and current_entry_tp_hits == 0:
            entries_without_take_profit += 1

    def close_traded_position(row_date: date, price: float, reason: str, destination: str) -> None:
        nonlocal trades, full_exits
        if not traded_position.is_open:
            return
        gross_sale = traded_position.shares * price
        net_sale = gross_sale * (1.0 - settings.commission_rate)
        realized_gain = net_sale - traded_position.basis
        realized_by_year[row_date.year] = realized_by_year.get(row_date.year, 0.0) + realized_gain
        trades += 1
        full_exits += 1
        add_trade_row(
            row_date=row_date,
            action="sell_traded",
            asset="traded",
            price=price,
            shares=traded_position.shares,
            gross_value=gross_sale,
            net_value=net_sale,
            realized_gain=realized_gain,
            destination=destination,
            note=reason,
        )
        mark_full_exit_without_tp_if_needed()
        traded_position.shares = 0.0
        traded_position.basis = 0.0
        allocate_proceeds(destination, net_sale, row_date, reason)
        reset_entry_state()

    def maybe_activate_trailing(current_price: float) -> None:
        nonlocal trailing_active, trailing_peak_price
        if not trailing_config.get("enabled", False):
            return
        if trailing_config.get("activate_after_first_take_profit", True):
            trailing_active = True
            trailing_peak_price = current_price

    def execute_take_profit(
        *,
        row_date: date,
        current_price: float,
        trigger_gain_multiple: float,
        sell_fraction: float,
        destination: str,
    ) -> bool:
        nonlocal trades, take_profit_hits, current_entry_tp_hits, full_exits
        if not traded_position.is_open or sell_fraction <= 0.0:
            return False

        actual_fraction = min(sell_fraction, 1.0)
        shares_to_sell = traded_position.shares * actual_fraction
        if shares_to_sell <= 1e-12:
            return False

        basis_sold = traded_position.basis * actual_fraction
        gross_sale = shares_to_sell * current_price
        net_sale = gross_sale * (1.0 - settings.commission_rate)
        realized_gain = net_sale - basis_sold
        realized_by_year[row_date.year] = realized_by_year.get(row_date.year, 0.0) + realized_gain

        traded_position.shares -= shares_to_sell
        traded_position.basis -= basis_sold
        trades += 1
        take_profit_hits += 1
        current_entry_tp_hits += 1
        tp_counts[str(trigger_gain_multiple)] += 1

        add_trade_row(
            row_date=row_date,
            action="take_profit",
            asset="traded",
            price=current_price,
            shares=shares_to_sell,
            gross_value=gross_sale,
            net_value=net_sale,
            realized_gain=realized_gain,
            destination=destination,
            note=f"Triggered at {trigger_gain_multiple:.2f}x",
        )
        allocate_proceeds(destination, net_sale, row_date, f"take profit {trigger_gain_multiple:.2f}x")
        if current_entry_tp_hits == 1:
            maybe_activate_trailing(current_price)

        if traded_position.shares <= 1e-12:
            traded_position.shares = 0.0
            traded_position.basis = 0.0
            full_exits += 1
            reset_entry_state()
            return True
        return False

    def open_traded_position(row_date: date, price: float) -> None:
        nonlocal cash, trades, entries, entry_price, trailing_active, trailing_peak_price
        liquidate_parked_positions(row_date, "Rotated parked assets into the traded position.")
        if cash <= 0.0:
            return
        gross_purchase = cash / (1.0 + settings.commission_rate)
        shares = gross_purchase / price
        traded_position.shares = shares
        traded_position.basis = cash
        cash = 0.0
        trades += 1
        entries += 1
        entry_price = price
        trailing_active = bool(trailing_config.get("enabled", False)) and not bool(
            trailing_config.get("activate_after_first_take_profit", True)
        )
        trailing_peak_price = price if trailing_active else None
        add_trade_row(
            row_date=row_date,
            action="buy_traded",
            asset="traded",
            price=price,
            shares=shares,
            gross_value=traded_position.basis,
            net_value=traded_position.basis,
            realized_gain=0.0,
            destination="traded",
            note="Opened a new traded position.",
        )

    first_date, first_price = traded_series[0]
    if entry_flags[0]:
        open_traded_position(first_date, first_price)
        equity_curve[0] = (first_date, total_portfolio_value(first_date, first_price))

    for idx in range(1, len(traded_series)):
        prev_date, _ = traded_series[idx - 1]
        current_date, current_price = traded_series[idx]
        days = max((current_date - prev_date).days, 1)
        rate = get_latest_value(prev_date, rate_dates, rate_map)

        if traded_position.is_open:
            days_in_market += days
        cash *= interval_cash_multiplier(days, rate)

        if current_date.year != prev_date.year:
            tax_due = max(realized_by_year.get(prev_date.year, 0.0), 0.0) * settings.tax_rate
            if tax_due > 0.0:
                portfolio_value = total_portfolio_value(current_date, current_price)
                ratio = max((portfolio_value - tax_due) / portfolio_value, 0.0) if portfolio_value > 0.0 else 0.0
                scale_portfolio(current_date, ratio)
            realized_by_year.setdefault(current_date.year, 0.0)

        did_full_exit = False

        if traded_position.is_open and trailing_active:
            trailing_peak_price = current_price if trailing_peak_price is None else max(trailing_peak_price, current_price)
            drawdown_from_peak = float(trailing_config.get("drawdown_from_peak", 0.15))
            if trailing_peak_price is not None and current_price <= trailing_peak_price * (1.0 - drawdown_from_peak):
                trailing_destination = canonical_asset_name(
                    trailing_config.get("destination", exit_destination),
                    base_series_name,
                )
                close_traded_position(current_date, current_price, "Trailing stop exit.", trailing_destination)
                did_full_exit = True

        if traded_position.is_open and not did_full_exit and exit_flags[idx]:
            close_traded_position(current_date, current_price, "Rule-based exit.", exit_destination)
            did_full_exit = True

        if traded_position.is_open and not did_full_exit and entry_price is not None:
            gain_multiple = current_price / entry_price
            for row in take_profit_ladder:
                trigger = float(row["trigger_gain_multiple"])
                if trigger in triggered_levels or gain_multiple < trigger:
                    continue
                destination = canonical_asset_name(row.get("destination", "cash"), base_series_name)
                position_closed = execute_take_profit(
                    row_date=current_date,
                    current_price=current_price,
                    trigger_gain_multiple=trigger,
                    sell_fraction=float(row["sell_fraction"]),
                    destination=destination,
                )
                triggered_levels.add(trigger)
                if position_closed:
                    did_full_exit = True
                    break

        if not traded_position.is_open and not did_full_exit and entry_flags[idx]:
            open_traded_position(current_date, current_price)

        equity_curve.append((current_date, total_portfolio_value(current_date, current_price)))

    last_date, last_price = traded_series[-1]
    if traded_position.is_open:
        close_traded_position(last_date, last_price, "Final close.", "cash")
    liquidate_parked_positions(last_date, "Final close.")
    final_tax = max(realized_by_year.get(last_date.year, 0.0), 0.0) * settings.tax_rate
    final_value = cash - final_tax
    equity_curve[-1] = (last_date, final_value)

    total_days = (traded_series[-1][0] - traded_series[0][0]).days
    time_in_market = days_in_market / total_days if total_days > 0 else 0.0

    metrics = analytics.compute_summary_stats(
        name=name,
        equity_curve=equity_curve,
        final_value=final_value,
        trades=trades,
        entries=entries,
        full_exits=full_exits,
        take_profit_hits=take_profit_hits,
        entries_without_take_profit=entries_without_take_profit,
        time_in_market=time_in_market,
        rate_dates=rate_dates,
        rate_map=rate_map,
    )

    take_profit_rows: list[dict[str, object]] = []
    for row in take_profit_ladder:
        trigger = float(row["trigger_gain_multiple"])
        take_profit_rows.append(
            {
                "strategy": name,
                "trigger_gain_multiple": f"{trigger:.6f}",
                "sell_fraction": f"{float(row['sell_fraction']):.6f}",
                "destination": canonical_asset_name(row.get("destination", "cash"), base_series_name),
                "hits": tp_counts[str(trigger)],
            }
        )

    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "annual_rows": analytics.compute_calendar_year_returns(equity_curve),
        "drawdowns": analytics.compute_drawdown_episodes(name, equity_curve),
        "trade_rows": trade_rows,
        "take_profit_rows": take_profit_rows,
    }


def run_from_config(config: dict, output_name: str | None = None) -> dict[str, object]:
    config = normalize_config(config)
    start_date = parse_date(config.get("start_date", DEFAULT_START_DATE.isoformat()))
    end_date = parse_date(config.get("end_date", DEFAULT_END_DATE.isoformat()))
    if start_date >= end_date:
        raise ValueError("start_date must be earlier than end_date.")

    settings = build_runtime_settings(config)
    output_dir = ensure_output_dir(output_name or config.get("output_name", "strategy_workbench_run"))
    rate_rows = load_rate_rows(DATA_DIR, None, end_date)
    rate_dates = [row_date for row_date, _ in rate_rows]
    rate_map = dict(rate_rows)
    base_cache = build_base_cache(start_date=start_date, end_date=end_date)

    metric_rows: list[analytics.MetricRow] = []
    annual_by_strategy: dict[str, list[dict[str, object]]] = {}
    drawdowns_by_strategy: dict[str, list[analytics.DrawdownEpisode]] = {}
    curves_by_strategy: dict[str, list[tuple[date, float]]] = {}
    trade_rows: list[dict[str, object]] = []
    take_profit_rows: list[dict[str, object]] = []

    for strategy in config["strategies"]:
        strategy_series = build_strategy_series(
            strategy=strategy,
            settings=settings,
            base_cache=base_cache,
            rate_dates=rate_dates,
            rate_map=rate_map,
        )
        result = simulate_strategy(
            strategy=strategy,
            settings=settings,
            strategy_series=strategy_series,
            rate_dates=rate_dates,
            rate_map=rate_map,
        )
        metrics = result["metrics"]
        metric_rows.append(metrics)
        annual_by_strategy[metrics.name] = result["annual_rows"]
        drawdowns_by_strategy[metrics.name] = result["drawdowns"]
        curves_by_strategy[metrics.name] = result["equity_curve"]
        trade_rows.extend(result["trade_rows"])
        take_profit_rows.extend(result["take_profit_rows"])

    metrics_path = output_dir / "metrics.csv"
    annual_path = output_dir / "annual_returns.csv"
    drawdowns_path = output_dir / "drawdowns.csv"
    curves_path = output_dir / "equity_curves.csv"
    trades_path = output_dir / "trades.csv"
    take_profit_path = output_dir / "take_profit_summary.csv"
    config_path = output_dir / "config.json"

    analytics.write_metrics_csv(metrics_path, metric_rows)
    analytics.write_annual_returns_csv(annual_path, annual_by_strategy)
    analytics.write_drawdowns_csv(drawdowns_path, drawdowns_by_strategy)
    analytics.write_equity_curves_csv(curves_path, curves_by_strategy)
    analytics.write_rows_csv(trades_path, trade_rows)
    analytics.write_rows_csv(take_profit_path, take_profit_rows)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    return {
        "output_dir": output_dir,
        "metrics_path": metrics_path,
        "annual_path": annual_path,
        "drawdowns_path": drawdowns_path,
        "curves_path": curves_path,
        "trades_path": trades_path,
        "take_profit_path": take_profit_path,
        "config_path": config_path,
        "metrics": metric_rows,
    }


def run_from_config_path(config_path: str | Path, output_name: str | None = None) -> dict[str, object]:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return run_from_config(config, output_name=output_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Strategy Workbench with a JSON config file and compare multiple strategies in one pass.",
    )
    parser.add_argument("--config", required=True, help="Path to the strategy config JSON file.")
    parser.add_argument(
        "--output-name",
        default="strategy_workbench_run",
        help="Name of the output folder created under the output root.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = run_from_config_path(args.config, output_name=args.output_name)
    print(f"wrote {result['metrics_path']}")
    print(f"wrote {result['annual_path']}")
    print(f"wrote {result['drawdowns_path']}")
    print(f"wrote {result['curves_path']}")
    print(f"wrote {result['trades_path']}")
    print(f"wrote {result['take_profit_path']}")
    print(f"wrote {result['config_path']}")
    for row in result["metrics"]:
        print(
            f"{row.name}: final={row.final_value:.4f}, CAGR={row.cagr:.4%}, "
            f"MDD={row.mdd:.4%}, Sharpe={row.sharpe:.3f}, Sortino={row.sortino:.3f}, "
            f"trades={row.trades}, tp_hits={row.take_profit_hits}, no_tp_entries={row.entries_without_take_profit}"
        )


if __name__ == "__main__":
    main()
