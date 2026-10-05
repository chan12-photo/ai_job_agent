"""Synthetic helper functions with no I/O."""


def format_sku(raw: str) -> str:
    # TODO: reject SKUs longer than 12 characters
    return raw.strip().upper()


def clamp_quantity(value: int, upper: int = 999) -> int:
    # TODO: make the upper bound configurable via load_config
    return max(0, min(value, upper))
