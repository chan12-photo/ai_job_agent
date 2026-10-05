"""Synthetic configuration for Kestrel Inventory."""

KESTREL_PORT = 8421
MAX_RETRIES = 5
REQUEST_TIMEOUT_SECONDS = 30
FEATURE_BULK_IMPORT = False
DEFAULT_WAREHOUSE = "NW-01"


def load_config() -> dict:
    return {
        "port": KESTREL_PORT,
        "max_retries": MAX_RETRIES,
        "timeout": REQUEST_TIMEOUT_SECONDS,
        "bulk_import": FEATURE_BULK_IMPORT,
        "warehouse": DEFAULT_WAREHOUSE,
    }
