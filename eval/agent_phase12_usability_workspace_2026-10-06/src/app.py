"""Synthetic entry point for Kestrel Inventory."""

from src.config import load_config
from src.utils import clamp_quantity, format_sku


def build_app() -> dict:
    config = load_config()
    return {"name": "kestrel-inventory", "port": config["port"]}


def restock(sku: str, quantity: int) -> str:
    # TODO(app): emit an audit event after restock
    return f"{format_sku(sku)}:{clamp_quantity(quantity)}"


if __name__ == "__main__":
    print(build_app())
