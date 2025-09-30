# file: watermark_app.py
# Python 3.9+
# deps: pip install PySide6

from __future__ import annotations

import json
import math
import os
import sys
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple, Dict

from PySide6.QtCore import (
    Qt,
    QSize,
    QRect,
    QRectF,
    QPoint,
    QPointF,
    QMimeData,
    QDir,
    QStandardPaths,
    Signal,
    QObject,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QImage,
    QImageReader,
    QImageWriter,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QTransform,
    QIntValidator,
    QDoubleValidator,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QStyle,
    QToolBar,
    QStatusBar,
    QMessageBox,
    QSlider,
    QLineEdit,
    QComboBox,
    QColorDialog,
    QCheckBox,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QScrollArea,
    QProgressDialog,
    QRadioButton,
    QButtonGroup,
    QGridLayout,
)

# -------- utility paths --------

APP_ORG = "CodeCopilot"
APP_NAME = "WatermarkApp"
APP_ID = f"{APP_ORG}_{APP_NAME}"


def app_data_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def templates_dir() -> Path:
    p = app_data_dir() / "templates"
    p.mkdir(parents=True, exist_ok=True)
    return p


def last_settings_path() -> Path:
    return app_data_dir() / "last.json"

