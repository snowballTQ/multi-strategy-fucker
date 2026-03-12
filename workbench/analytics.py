from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .data_loader import get_latest_value


@dataclass
class MetricRow:
    name: str
    final_value: float
    cagr: float
    mdd: float
    calmar: float
    volatility: float
    sharpe: float
    sortino: float
    trades: int
    entries: int
    full_exits: int
    take_profit_hits: int
    entries_without_take_profit: int
    time_in_market: float


@dataclass
class DrawdownEpisode:
    strategy: str
    rank: int
    peak_date: date
    trough_date: date
    recovery_date: date | None
    drawdown: float
    peak_to_trough_days: int
    peak_to_recovery_days: int | None
    recovered: bool


def calculate_drawdown(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        if value > peak:
            peak = value
        drawdown = value / peak - 1.0
        if drawdown < worst:
            worst = drawdown
    return worst


def compute_period_returns(curve: list[tuple[date, float]]) -> list[tuple[date, int, float]]:
    rows: list[tuple[date, int, float]] = []
    for (prev_date, prev_value), (current_date, current_value) in zip(curve, curve[1:]):
        if prev_value <= 0.0:
            continue
        days = max((current_date - prev_date).days, 1)
        rows.append((prev_date, days, current_value / prev_value - 1.0))
    return rows


def compute_risk_metrics(
    curve: list[tuple[date, float]],
    rate_dates: list[date],
    rate_map: dict[date, float],
) -> tuple[float, float, float]:
    period_rows = compute_period_returns(curve)
    if len(period_rows) < 2:
        return float("nan"), float("nan"), float("nan")

    avg_days = sum(days for _, days, _ in period_rows) / len(period_rows)
    periods_per_year = 365.2425 / avg_days

    raw_returns = [period_return for _, _, period_return in period_rows]
    mean_return = sum(raw_returns) / len(raw_returns)
    variance = sum((value - mean_return) ** 2 for value in raw_returns) / (len(raw_returns) - 1)
    volatility = math.sqrt(variance) * math.sqrt(periods_per_year)

    excess_returns: list[float] = []
    for row_date, days, period_return in period_rows:
        rate = get_latest_value(row_date, rate_dates, rate_map)
        risk_free_return = math.exp((rate / 100.0) * days / 360.0) - 1.0
        excess_returns.append(period_return - risk_free_return)

    mean_excess = sum(excess_returns) / len(excess_returns)
    excess_variance = sum((value - mean_excess) ** 2 for value in excess_returns) / (len(excess_returns) - 1)
    excess_std = math.sqrt(excess_variance)
    sharpe = (
        mean_excess * periods_per_year / (excess_std * math.sqrt(periods_per_year))
        if excess_std > 0.0
        else float("nan")
    )

    downside_values = [min(value, 0.0) for value in excess_returns]
    downside_variance = sum(value * value for value in downside_values) / len(downside_values)
    downside_dev = math.sqrt(downside_variance) * math.sqrt(periods_per_year)
    sortino = (
        mean_excess * periods_per_year / downside_dev
        if downside_dev > 0.0
        else float("nan")
    )
    return volatility, sharpe, sortino


def compute_summary_stats(
    *,
    name: str,
    equity_curve: list[tuple[date, float]],
    final_value: float,
    trades: int,
    entries: int,
    full_exits: int,
    take_profit_hits: int,
    entries_without_take_profit: int,
    time_in_market: float,
    rate_dates: list[date],
    rate_map: dict[date, float],
) -> MetricRow:
    start = equity_curve[0][0]
    end = equity_curve[-1][0]
    total_days = (end - start).days
    cagr = final_value ** (365.2425 / total_days) - 1.0 if total_days > 0 else float("nan")
    values = [value for _, value in equity_curve]
    mdd = calculate_drawdown(values)
    calmar = cagr / abs(mdd) if mdd < 0 else float("inf")
    volatility, sharpe, sortino = compute_risk_metrics(equity_curve, rate_dates, rate_map)
    return MetricRow(
        name=name,
        final_value=final_value,
        cagr=cagr,
        mdd=mdd,
        calmar=calmar,
        volatility=volatility,
        sharpe=sharpe,
        sortino=sortino,
        trades=trades,
        entries=entries,
        full_exits=full_exits,
        take_profit_hits=take_profit_hits,
        entries_without_take_profit=entries_without_take_profit,
        time_in_market=time_in_market,
    )


def compute_calendar_year_returns(curve: list[tuple[date, float]]) -> list[dict[str, object]]:
    year_end: dict[int, tuple[date, float]] = {}
    year_first: dict[int, tuple[date, float]] = {}
    for current_date, current_value in curve:
        year_end[current_date.year] = (current_date, current_value)
        year_first.setdefault(current_date.year, (current_date, current_value))

    years = sorted(year_end)
    rows: list[dict[str, object]] = []
    previous_end_value: float | None = None
    for year in years:
        start_date, start_value = year_first[year]
        end_date, end_value = year_end[year]
        basis = previous_end_value if previous_end_value is not None else start_value
        annual_return = end_value / basis - 1.0 if basis > 0 else float("nan")
        rows.append(
            {
                "year": year,
                "start_date": start_date,
                "end_date": end_date,
                "return": annual_return,
                "is_partial": year == years[0] or year == years[-1],
            }
        )
        previous_end_value = end_value
    return rows


def compute_drawdown_episodes(strategy_name: str, curve: list[tuple[date, float]]) -> list[DrawdownEpisode]:
    peak_date, peak_value = curve[0]
    episode_peak_date, episode_peak_value = peak_date, peak_value
    trough_date, trough_value = peak_date, peak_value
    in_drawdown = False
    episodes: list[DrawdownEpisode] = []

    for current_date, current_value in curve[1:]:
        if current_value >= peak_value:
            if in_drawdown and trough_value < episode_peak_value:
                episodes.append(
                    DrawdownEpisode(
                        strategy=strategy_name,
                        rank=0,
                        peak_date=episode_peak_date,
                        trough_date=trough_date,
                        recovery_date=current_date,
                        drawdown=trough_value / episode_peak_value - 1.0,
                        peak_to_trough_days=(trough_date - episode_peak_date).days,
                        peak_to_recovery_days=(current_date - episode_peak_date).days,
                        recovered=True,
                    )
                )
                in_drawdown = False
            peak_date, peak_value = current_date, current_value
            episode_peak_date, episode_peak_value = peak_date, peak_value
            trough_date, trough_value = current_date, current_value
            continue

        if not in_drawdown:
            in_drawdown = True
            trough_date, trough_value = current_date, current_value
        elif current_value < trough_value:
            trough_date, trough_value = current_date, current_value

    if in_drawdown and trough_value < episode_peak_value:
        episodes.append(
            DrawdownEpisode(
                strategy=strategy_name,
                rank=0,
                peak_date=episode_peak_date,
                trough_date=trough_date,
                recovery_date=None,
                drawdown=trough_value / episode_peak_value - 1.0,
                peak_to_trough_days=(trough_date - episode_peak_date).days,
                peak_to_recovery_days=None,
                recovered=False,
            )
        )

    episodes.sort(key=lambda item: item.drawdown)
    ranked: list[DrawdownEpisode] = []
    for rank, item in enumerate(episodes, start=1):
        ranked.append(
            DrawdownEpisode(
                strategy=item.strategy,
                rank=rank,
                peak_date=item.peak_date,
                trough_date=item.trough_date,
                recovery_date=item.recovery_date,
                drawdown=item.drawdown,
                peak_to_trough_days=item.peak_to_trough_days,
                peak_to_recovery_days=item.peak_to_recovery_days,
                recovered=item.recovered,
            )
        )
    return ranked


def write_metrics_csv(path: Path, rows: list[MetricRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "strategy",
                "final_multiple",
                "cagr",
                "mdd",
                "calmar",
                "volatility",
                "sharpe",
                "sortino",
                "trades",
                "entries",
                "full_exits",
                "take_profit_hits",
                "entries_without_take_profit",
                "time_in_market",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.name,
                    f"{row.final_value:.6f}",
                    f"{row.cagr:.6f}",
                    f"{row.mdd:.6f}",
                    f"{row.calmar:.6f}",
                    f"{row.volatility:.6f}",
                    f"{row.sharpe:.6f}",
                    f"{row.sortino:.6f}",
                    row.trades,
                    row.entries,
                    row.full_exits,
                    row.take_profit_hits,
                    row.entries_without_take_profit,
                    f"{row.time_in_market:.6f}",
                ]
            )


def write_annual_returns_csv(path: Path, annual_by_strategy: dict[str, list[dict[str, object]]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["strategy", "year", "start_date", "end_date", "period_type", "return"])
        for strategy_name, rows in annual_by_strategy.items():
            for row in rows:
                writer.writerow(
                    [
                        strategy_name,
                        row["year"],
                        row["start_date"].isoformat(),
                        row["end_date"].isoformat(),
                        "partial" if row["is_partial"] else "full",
                        f"{row['return']:.6f}",
                    ]
                )


def write_drawdowns_csv(path: Path, drawdowns_by_strategy: dict[str, list[DrawdownEpisode]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "strategy",
                "rank",
                "peak_date",
                "trough_date",
                "recovery_date",
                "drawdown",
                "peak_to_trough_days",
                "peak_to_recovery_days",
                "recovered",
            ]
        )
        for strategy_name, episodes in drawdowns_by_strategy.items():
            for episode in episodes:
                writer.writerow(
                    [
                        strategy_name,
                        episode.rank,
                        episode.peak_date.isoformat(),
                        episode.trough_date.isoformat(),
                        episode.recovery_date.isoformat() if episode.recovery_date else "",
                        f"{episode.drawdown:.6f}",
                        episode.peak_to_trough_days,
                        episode.peak_to_recovery_days if episode.peak_to_recovery_days is not None else "",
                        int(episode.recovered),
                    ]
                )


def write_equity_curves_csv(path: Path, curves_by_strategy: dict[str, list[tuple[date, float]]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["strategy", "date", "equity"])
        for strategy_name, curve in curves_by_strategy.items():
            for row_date, equity in curve:
                writer.writerow([strategy_name, row_date.isoformat(), f"{equity:.6f}"])


def write_rows_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["empty"])
        return

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
