from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


Series = list[tuple[date, float]]


def rolling_sma(series: Series, window: int) -> list[float | None]:
    if window < 1:
        raise ValueError("window must be at least 1.")

    output: list[float | None] = []
    running_sum = 0.0
    values = [price for _, price in series]
    for idx, value in enumerate(values):
        running_sum += value
        if idx >= window:
            running_sum -= values[idx - window]
        output.append(running_sum / window if idx + 1 >= window else None)
    return output


@dataclass
class IndicatorCache:
    series_by_name: dict[str, Series]
    sma_cache: dict[tuple[str, int], list[float | None]] = field(default_factory=dict)

    def get_series(self, name: str) -> Series:
        if name not in self.series_by_name:
            raise ValueError(f"Unknown series source: {name}")
        return self.series_by_name[name]

    def get_sma(self, source: str, window: int) -> list[float | None]:
        key = (source, window)
        if key not in self.sma_cache:
            self.sma_cache[key] = rolling_sma(self.get_series(source), window)
        return self.sma_cache[key]
