# Kestrel Inventory Architecture

- The HTTP layer listens on port 8421.
- `src/config.py` is the single source of configuration values.
- `src/utils.py` holds pure helper functions with no I/O.
- Stock data is kept in memory; there is no database in this fixture.
- Release codename: BLUE HERON.
