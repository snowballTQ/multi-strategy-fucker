from __future__ import annotations

import csv
import urllib.request
from bisect import bisect_right
from datetime import date, datetime
from pathlib import Path


DEFAULT_START_DATE = date(1985, 10, 1)
DEFAULT_END_DATE = date(2026, 3, 9)

NDX_URL = "https://stooq.com/q/d/l/?s=%5Endx&i=d"
SPX_URL = "https://stooq.com/q/d/l/?s=%5Espx&i=d"
DFF_TEXT_URL = "https://fred.stlouisfed.org/data/DFF.txt"
NASDAQ_COMPOSITE_TEXT_URL = "https://fred.stlouisfed.org/data/NASDAQCOM.txt"


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def read_snapshot_or_fetch(data_dir: Path, snapshot_names: list[str], fallback_url: str) -> str:
    for name in snapshot_names:
        path = data_dir / name
        if path.exists():
            return path.read_text(encoding="utf-8")
    return fetch_text(fallback_url)


def parse_stooq_csv(raw_text: str, start_date: date, end_date: date) -> list[tuple[date, float]]:
    rows: list[tuple[date, float]] = []
    reader = csv.DictReader(raw_text.splitlines())
    for row in reader:
        try:
            row_date = datetime.strptime(row["Date"], "%Y-%m-%d").date()
            close = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            continue
        if start_date <= row_date <= end_date:
            rows.append((row_date, close))
    if not rows:
        raise RuntimeError("No price rows parsed.")
    return rows


def parse_fred_series(
    raw_text: str,
    value_column: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[tuple[date, float]]:
    rows: list[tuple[date, float]] = []

    if "observation_date" in raw_text:
        reader = csv.DictReader(raw_text.splitlines())
        for row in reader:
            try:
                row_date = datetime.strptime(row["observation_date"], "%Y-%m-%d").date()
                raw_value = row.get(value_column, "")
            except (KeyError, TypeError, ValueError):
                continue
            if not raw_value or raw_value == ".":
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            if start_date and row_date < start_date:
                continue
            if end_date and row_date > end_date:
                continue
            rows.append((row_date, value))
    else:
        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line.startswith("#"):
                continue
            try:
                raw_date, raw_value = line[1:].split("|", 1)
                row_date = datetime.strptime(raw_date.strip(), "%Y-%m-%d").date()
                value = float(raw_value.strip())
            except (ValueError, TypeError):
                continue
            if start_date and row_date < start_date:
                continue
            if end_date and row_date > end_date:
                continue
            rows.append((row_date, value))

    if not rows:
        raise RuntimeError(f"No rows parsed for {value_column}.")
    return rows


def load_ndx_rows(data_dir: Path, start_date: date, end_date: date) -> list[tuple[date, float]]:
    raw_text = read_snapshot_or_fetch(data_dir, ["ndx.csv"], NDX_URL)
    return parse_stooq_csv(raw_text, start_date, end_date)


def load_spx_rows(data_dir: Path, start_date: date, end_date: date) -> list[tuple[date, float]]:
    raw_text = read_snapshot_or_fetch(data_dir, ["spx.csv"], SPX_URL)
    return parse_stooq_csv(raw_text, start_date, end_date)


def load_rate_rows(
    data_dir: Path,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[tuple[date, float]]:
    raw_text = read_snapshot_or_fetch(data_dir, ["dff.csv", "dff.txt"], DFF_TEXT_URL)
    return parse_fred_series(raw_text, "DFF", start_date, end_date)


def load_composite_rows(
    data_dir: Path,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[tuple[date, float]]:
    raw_text = read_snapshot_or_fetch(data_dir, ["nasdaqcom.csv", "nasdaqcom.txt"], NASDAQ_COMPOSITE_TEXT_URL)
    return parse_fred_series(raw_text, "NASDAQCOM", start_date, end_date)


def build_spliced_series(
    early_rows: list[tuple[date, float]],
    later_rows: list[tuple[date, float]],
    splice_date: date,
) -> list[tuple[date, float]]:
    early_map = dict(early_rows)
    if splice_date not in early_map:
        raise RuntimeError(f"Unable to splice at {splice_date.isoformat()}: missing early-series value.")
    later_start_price = next(price for row_date, price in later_rows if row_date == splice_date)
    scale = early_map[splice_date] / later_start_price
    return (
        [(row_date, price) for row_date, price in early_rows if row_date < splice_date]
        + [(row_date, price * scale) for row_date, price in later_rows]
    )


def resolve_base_rows(
    data_dir: Path,
    base_series_name: str,
    start_date: date,
    end_date: date,
) -> list[tuple[date, float]]:
    if base_series_name == "ndx":
        return load_ndx_rows(data_dir, start_date, end_date)
    if base_series_name == "spx":
        return load_spx_rows(data_dir, start_date, end_date)
    if base_series_name == "composite_splice":
        later_rows = load_ndx_rows(data_dir, start_date, end_date)
        early_rows = load_composite_rows(data_dir, None, end_date)
        splice_date = later_rows[0][0]
        return build_spliced_series(early_rows, later_rows, splice_date)
    raise ValueError(f"Unsupported base series: {base_series_name}")


def normalize_series(series: list[tuple[date, float]]) -> list[tuple[date, float]]:
    first_price = series[0][1]
    return [(row_date, price / first_price) for row_date, price in series]


def build_series_lookup(series: list[tuple[date, float]]) -> tuple[list[date], dict[date, float]]:
    dates = [row_date for row_date, _ in series]
    return dates, dict(series)


def get_latest_value(target_date: date, series_dates: list[date], series_map: dict[date, float]) -> float:
    idx = bisect_right(series_dates, target_date) - 1
    if idx < 0:
        raise RuntimeError(f"No observation on or before {target_date.isoformat()}.")
    return series_map[series_dates[idx]]
