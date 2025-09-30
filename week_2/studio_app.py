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


# -------- data model --------

@dataclass
class WatermarkSettings:
    # general
    wm_type: str = "text"  # "text" | "image"
    opacity: int = 70  # 0-100
    rotation: float = 0.0  # degrees
    pos_rel: Tuple[float, float] = (0.5, 0.5)  # center anchor, 0..1
    margin_rel: float = 0.03  # for nine-grid presets

    # text wm
    text: str = "Sample Watermark"
    font_family: str = "Arial"
    font_point: int = 36
    font_bold: bool = False
    font_italic: bool = False
    color_rgba: str = "#FFFFFFB3"  # white ~70%
    shadow: bool = True  # soft shadow for readability

    # image wm
    image_path: str = ""
    image_scale_pct: int = 30  # relative to shorter side of base image

    # export
    out_dir: str = ""
    out_format: str = "PNG"  # "PNG" | "JPEG"
    jpeg_quality: int = 90  # 0-100

    # resize
    resize_mode: str = "none"  # "none" | "width" | "height" | "percent"
    resize_value: int = 0

    # naming
    name_mode: str = "original"  # "original" | "prefix" | "suffix"
    name_prefix: str = "wm_"
    name_suffix: str = "_watermarked"

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: Dict) -> "WatermarkSettings":
        obj = WatermarkSettings()
        for k, v in d.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        return obj
