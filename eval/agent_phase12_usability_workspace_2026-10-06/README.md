# Kestrel Inventory Service

Kestrel Inventory is a small synthetic Python service used only for read-only agent evaluation.
It tracks warehouse stock levels for the fictional Northwind Depot.

## Key facts

- Service port: 8421
- Entry point: `python -m src.app`
- Configuration lives in `src/config.py`.
- Architecture notes live in `docs/architecture.md`.

## Status

Version 0.3.0. Synthetic fixture, not for production use.
