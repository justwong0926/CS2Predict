from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DUCKDB_PATH = DATA_DIR / "cs2.duckdb"

# --- data sources ---
# Match/team/player stats
BO3_BASE = "https://api.bo3.gg"          # HLTV-equivalent, does not block automation
GRID_BASE = "https://api.grid.gg"         # official data (Open Access, requires approved key)

# Odds benchmark (Pinnacle + others via third-party feed; Pinnacle's own API closed 2025)
ODDSPAPI_BASE = "https://api.oddspapi.io"

# Tradeable venue
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"

DATA_DIR.mkdir(parents=True, exist_ok=True)
