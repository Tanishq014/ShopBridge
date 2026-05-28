from pathlib import Path
import os


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent


def _path_from_env(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default))).expanduser()


DATA_DIR = _path_from_env("SHOPBRIDGE_DATA_DIR", PROJECT_ROOT / "data")
PRINT_JOBS_DIR = _path_from_env("SHOPBRIDGE_PRINT_JOBS_DIR", PROJECT_ROOT / "print_jobs")
EXPORTS_DIR = _path_from_env("SHOPBRIDGE_EXPORTS_DIR", PROJECT_ROOT / "exports")
PREVIEWS_DIR = _path_from_env("SHOPBRIDGE_PREVIEWS_DIR", EXPORTS_DIR / "previews")
BARTENDER_TEMPLATES_DIR = _path_from_env(
    "SHOPBRIDGE_BARTENDER_TEMPLATES_DIR",
    PROJECT_ROOT / "bartender_templates",
)

DB_PATH = DATA_DIR / "shopbridge.db"
DATABASE_URL = os.getenv("SHOPBRIDGE_DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")

TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

BARTEND_EXE_PATH = os.getenv(
    "SHOPBRIDGE_BARTEND_EXE_PATH",
    r"C:\Program Files (x86)\Seagull\BarTender Suite\bartend.exe",
)
DEFAULT_TALLY_DSN = os.getenv("SHOPBRIDGE_TALLY_DSN", "TallyODBC64_9000")

BARTENDER_MODE = os.getenv("SHOPBRIDGE_BARTENDER_MODE", "activex").strip().lower()
SHOW_BARTENDER_WINDOW = os.getenv("SHOPBRIDGE_SHOW_BARTENDER_WINDOW", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
