"""Main entrypoint for running ingestion loaders CLI directly."""

import sys

from ingestion.loaders import run_cli

if __name__ == "__main__":
    sys.exit(run_cli())
