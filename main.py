import sys

from PyQt5.QtWidgets import QApplication

from desktop_app.window import QualityControlWindow


def main():
    app = QApplication(sys.argv)
    window = QualityControlWindow()
    window.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
