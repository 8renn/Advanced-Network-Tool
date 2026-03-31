import logging
import os

from core.runtime_paths import user_data_dir

LOG_FILE = str(user_data_dir() / "advanced_ip_scanner.log")

def setup_logger():
    logger = logging.getLogger("advanced_ip_scanner")
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    # Clear log file each run
    if os.path.exists(LOG_FILE):
        try:
            os.remove(LOG_FILE)
        except OSError:
            # If another process/session holds the file, continue with append mode.
            pass

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.debug("=== APPLICATION STARTED ===")

    return logger


logger = setup_logger()
