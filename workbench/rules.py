from __future__ import annotations

from .indicators import IndicatorCache


def apply_confirm_days(raw_flags: list[bool], confirm_days: int) -> list[bool]:
    if confirm_days < 1:
        raise ValueError("confirm_days must be at least 1.")
    output: list[bool] = []
    streak = 0
    for flag in raw_flags:
        streak = streak + 1 if flag else 0
        output.append(streak >= confirm_days)
    return output


def evaluate_rule_config(rule_config: dict, cache: IndicatorCache) -> list[bool]:
    rule_type = rule_config["type"]

    if rule_type in {"all_of", "any_of"}:
        children = [evaluate_rule_config(child, cache) for child in rule_config.get("rules", [])]
        if not children:
            raise ValueError(f"{rule_type} requires at least one child rule.")
        if rule_type == "all_of":
            raw_flags = [all(values) for values in zip(*children, strict=True)]
        else:
            raw_flags = [any(values) for values in zip(*children, strict=True)]
    elif rule_type == "always_true":
        length = len(cache.get_series(rule_config.get("source", "traded")))
        raw_flags = [True] * length
    else:
        raw_flags = evaluate_atomic_rule(rule_config, cache)

    confirm_days = int(rule_config.get("confirm_days", 1))
    return apply_confirm_days(raw_flags, confirm_days)


def evaluate_atomic_rule(rule_config: dict, cache: IndicatorCache) -> list[bool]:
    rule_type = rule_config["type"]
    source = rule_config.get("source", "traded")
    series = cache.get_series(source)

    if rule_type == "price_above_sma":
        window = int(rule_config["window"])
        sma = cache.get_sma(source, window)
        return [value is not None and price > value for (_, price), value in zip(series, sma, strict=True)]

    if rule_type == "price_below_sma":
        window = int(rule_config["window"])
        sma = cache.get_sma(source, window)
        return [value is not None and price < value for (_, price), value in zip(series, sma, strict=True)]

    if rule_type in {"sma_chain_above", "sma_chain_below"}:
        windows = [int(window) for window in rule_config["windows"]]
        if len(windows) < 2:
            raise ValueError(f"{rule_type} requires at least two windows.")
        sma_values = [cache.get_sma(source, window) for window in windows]
        output: list[bool] = []
        for idx in range(len(series)):
            current = [values[idx] for values in sma_values]
            if any(value is None for value in current):
                output.append(False)
                continue
            if rule_type == "sma_chain_above":
                output.append(all(left > right for left, right in zip(current, current[1:])))
            else:
                output.append(all(left < right for left, right in zip(current, current[1:])))
        return output

    if rule_type in {"fast_above_slow", "fast_below_slow"}:
        fast_window = int(rule_config["fast_window"])
        slow_window = int(rule_config["slow_window"])
        fast = cache.get_sma(source, fast_window)
        slow = cache.get_sma(source, slow_window)
        if rule_type == "fast_above_slow":
            return [
                fast_value is not None and slow_value is not None and fast_value > slow_value
                for fast_value, slow_value in zip(fast, slow, strict=True)
            ]
        return [
            fast_value is not None and slow_value is not None and fast_value < slow_value
            for fast_value, slow_value in zip(fast, slow, strict=True)
        ]

    raise ValueError(f"Unsupported rule type: {rule_type}")
