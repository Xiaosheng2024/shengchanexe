import logging
from pathlib import Path
import sys

from PyQt5.QtWidgets import QApplication

from desktop_app.window import QualityControlWindow


def setup_crash_logging():
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "app_crash.log",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )

    def handle_exception(exc_type, exc_value, exc_traceback):
        logging.critical("未捕获异常", exc_info=(exc_type, exc_value, exc_traceback))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle_exception


def main():
    setup_crash_logging()
    app = QApplication(sys.argv)
    window = QualityControlWindow()
    window.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
