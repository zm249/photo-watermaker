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



# -------- image helpers --------

SUPPORTED_READ = {fmt.data().decode("utf-8").lower() for fmt in QImageReader.supportedImageFormats()}
VALID_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"} & {f".{e}" for e in SUPPORTED_READ}
THUMB_SIZE = QSize(120, 120)


def is_image_file(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in VALID_EXTS


def enumerate_images(paths: List[Path]) -> List[Path]:
    out: List[Path] = []
    for path in paths:
        if path.is_file():
            if is_image_file(path):
                out.append(path)
        elif path.is_dir():
            for root, _, files in os.walk(path):
                for fn in files:
                    fp = Path(root) / fn
                    if is_image_file(fp):
                        out.append(fp)
    return out


def load_qimage(path: Path) -> Optional[QImage]:
    reader = QImageReader(str(path))
    img = reader.read()
    if img.isNull():
        return None
    return img.convertToFormat(QImage.Format.Format_ARGB32)


def save_qimage(img: QImage, dest: Path, fmt: str, jpeg_quality: int) -> bool:
    writer = QImageWriter(str(dest), fmt.encode("utf-8"))
    if fmt.upper() == "JPEG":
        writer.setQuality(jpeg_quality)
    return writer.write(img)


def qcolor_from_rgba_str(s: str) -> QColor:
    # Accept #RRGGBB or #RRGGBBAA
    c = QColor(s)
    if not c.isValid():
        return QColor(255, 255, 255, 180)
    return c
