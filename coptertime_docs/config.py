from pathlib import Path

APP_NAME = "CopterTime Docs"
APP_VERSION = "0.4.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "coptertime_docs.db"
LEGACY_GLOSSARY_PATH = PROJECT_ROOT / "glossary.csv"

DEFAULT_BRANDS = (
    "General",
    "QYSEA",
    "DJI",
    "BETAFPV",
    "FIMI",
    "MJX",
    "ToolkitRC",
)

MAX_TRANSLATION_CHARS = 4200
