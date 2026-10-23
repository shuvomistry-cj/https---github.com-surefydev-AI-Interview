import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from config import load_env

load_env()

from models import init_db


if __name__ == "__main__":
    init_db()
    print("Database ready.")
