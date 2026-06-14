import os
import logging
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
load_dotenv()

# Ensure data/ exists before configuring the file handler
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(_DATA_DIR, exist_ok=True)

_fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=_fmt,
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            os.path.join(_DATA_DIR, "app.log"),
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=3,
            encoding="utf-8",
        ),
    ],
)

log = logging.getLogger(__name__)

from src.database import init_db
from src.gui.app import MainWindow

if __name__ == "__main__":
    log.info("TBH Market Tracker starting.")
    init_db()
    MainWindow().mainloop()
    log.info("TBH Market Tracker closed.")
