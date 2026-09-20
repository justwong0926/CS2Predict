import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DUCKDB_PATH = DATA_DIR / "cs2.duckdb"


def _load_env() -> None:
    envf = REPO_ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY")

# --- data sources ---
# Match/team/player stats
BO3_BASE = "https://api.bo3.gg"          # HLTV-equivalent, does not block automation
GRID_BASE = "https://api.grid.gg"         # official data (Open Access, requires approved key)

# Odds benchmark (Pinnacle + others via third-party feed; Pinnacle's own API closed 2025)
ODDSPAPI_BASE = "https://api.oddspapi.io"

# Tradeable venue
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"

DATA_DIR.mkdir(parents=True, exist_ok=True)
