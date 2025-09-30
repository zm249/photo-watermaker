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


# -------- UI: Image list --------

class ImageListPanel(QListWidget):
    filesChanged = Signal(list)

    def __init__(self):
        super().__init__()
        self.setIconSize(THUMB_SIZE)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
        self.paths: List[Path] = []

    def add_images(self, new_paths: List[Path]):
        existed = {str(p) for p in self.paths}
        added = []
        for p in new_paths:
            sp = str(p)
            if sp in existed:
                continue
            img = load_qimage(p)
            if img is None:
                continue
            thumb = QPixmap.fromImage(img.scaled(THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            item = QListWidgetItem(QIcon(thumb), p.name)
            item.setToolTip(sp)
            self.addItem(item)
            self.paths.append(p)
            added.append(p)
        if added:
            self.filesChanged.emit([str(p) for p in self.paths])

    def remove_selected(self):
        rows = sorted({i.row() for i in self.selectedIndexes()}, reverse=True)
        for r in rows:
            self.takeItem(r)
            del self.paths[r]
        self.filesChanged.emit([str(p) for p in self.paths])

    def clear_all(self):
        super().clear()
        self.paths = []
        self.filesChanged.emit([])

    # drag & drop
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        urls = e.mimeData().urls()
        paths = [Path(u.toLocalFile()) for u in urls]
        imgs = enumerate_images(paths)
        self.add_images(imgs)


# -------- UI: Preview Canvas --------

class PreviewCanvas(QWidget):
    positionChanged = Signal(tuple)  # (x_rel, y_rel)

    def __init__(self):
        super().__init__()
        self.base_img: Optional[QImage] = None
        self.base_pix: Optional[QPixmap] = None
        self.scaled_rect: QRect = QRect()
        self.settings = WatermarkSettings()
        self.setMouseTracking(True)
        self.dragging = False
        self.drag_offset = QPointF(0, 0)  # why: to preserve pointer grab relative to wm center
        self.cached_wm_pixmap: Optional[QPixmap] = None
        self.setMinimumSize(320, 240)

    def set_image(self, img: Optional[QImage]):
        self.base_img = img
        self.base_pix = QPixmap.fromImage(img) if img is not None else None
        self.update()

    def set_settings(self, st: WatermarkSettings):
        self.settings = st
        self.cached_wm_pixmap = None
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(800, 600)

    def compute_scaled_rect(self) -> QRect:
        if not self.base_pix:
            return QRect()
        avail = self.rect()
        pix = self.base_pix
        scaled = pix.scaled(avail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (avail.width() - scaled.width()) // 2
        y = (avail.height() - scaled.height()) // 2
        return QRect(QPoint(x, y), scaled.size())

    def build_text_watermark(self, target_px: int) -> QPixmap:
        st = self.settings
        font = QFont(st.font_family, st.font_point)
        font.setBold(st.font_bold)
        font.setItalic(st.font_italic)
        # measure text
        tmp_img = QImage(1, 1, QImage.Format.Format_ARGB32)
        tmp_img.fill(Qt.transparent)
        p = QPainter(tmp_img)
        p.setFont(font)
        metrics = p.fontMetrics()
        br = metrics.boundingRect(st.text)
        p.end()
        w = max(4, br.width() + 16)
        h = max(4, br.height() + 16)
        # draw text with optional shadow
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(font)
        col = qcolor_from_rgba_str(st.color_rgba)
        if st.shadow:
            shadow = QColor(0, 0, 0, int(0.5 * st.opacity * 2.55))
            painter.setPen(shadow)
            painter.drawText(9, h - metrics.descent() - 7, st.text)
        painter.setPen(col)
        painter.drawText(8, h - metrics.descent() - 8, st.text)
        painter.end()
        pix = QPixmap.fromImage(img)
        # scale text if needed relative to target pixels (no-op here font point governs size)
        return pix

    def build_image_watermark(self, base_size: QSize) -> Optional[QPixmap]:
        st = self.settings
        if not st.image_path or not Path(st.image_path).exists():
            return None
        wm_img = load_qimage(Path(st.image_path))
        if wm_img is None or wm_img.isNull():
            return None
        # scale relative to shorter side of base image
        short_side = min(base_size.width(), base_size.height())
        scale_px = max(1, int(short_side * (st.image_scale_pct / 100.0)))
        wm_pix = QPixmap.fromImage(wm_img)
        ratio = wm_pix.width() / wm_pix.height()
        if wm_pix.width() >= wm_pix.height():
            target_w = scale_px
            target_h = int(target_w / ratio)
        else:
            target_h = scale_px
            target_w = int(target_h * ratio)
        scaled = wm_pix.scaled(QSize(target_w, target_h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return scaled

    def build_watermark_pixmap(self, base_px_size: QSize) -> Optional[QPixmap]:
        if self.cached_wm_pixmap:
            return self.cached_wm_pixmap
        st = self.settings
        if st.wm_type == "text":
            pix = self.build_text_watermark(target_px=min(base_px_size.width(), base_px_size.height()))
        else:
            pix = self.build_image_watermark(base_px_size)
            if pix is None:
                return None
        # rotation
        if abs(st.rotation) > 0.01:
            tr = QTransform()
            tr.rotate(st.rotation)
            pix = pix.transformed(tr, Qt.SmoothTransformation)
        self.cached_wm_pixmap = pix
        return pix

    def wm_rect_on_scaled(self) -> Optional[QRect]:
        if not self.base_pix:
            return None
        scaled_rect = self.compute_scaled_rect()
        wm_pix = self.build_watermark_pixmap(scaled_rect.size())
        if wm_pix is None:
            return None
        st = self.settings
        cx = scaled_rect.x() + st.pos_rel[0] * scaled_rect.width()
        cy = scaled_rect.y() + st.pos_rel[1] * scaled_rect.height()
        x = int(cx - wm_pix.width() / 2)
        y = int(cy - wm_pix.height() / 2)
        return QRect(x, y, wm_pix.width(), wm_pix.height())

    def paintEvent(self, e: QPaintEvent):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        if not self.base_pix:
            painter.drawText(self.rect(), Qt.AlignCenter, "导入图片以预览")
            painter.end()
            return
        # draw scaled base
        self.scaled_rect = self.compute_scaled_rect()
        scaled_pix = self.base_pix.scaled(self.scaled_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(self.scaled_rect.topLeft(), scaled_pix)
        # draw watermark
        wm_pix = self.build_watermark_pixmap(self.scaled_rect.size())
        if wm_pix:
            st = self.settings
            rect = self.wm_rect_on_scaled()
            if rect:
                painter.setOpacity(max(0.0, min(1.0, st.opacity / 100.0)))
                painter.drawPixmap(rect.topLeft(), wm_pix)
        painter.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            rect = self.wm_rect_on_scaled()
            if rect and rect.contains(e.pos()):
                self.dragging = True
                c = rect.center()
                self.drag_offset = QPointF(e.position().x() - c.x(), e.position().y() - c.y())

    def mouseMoveEvent(self, e):
        if self.dragging and self.base_pix:
            sr = self.compute_scaled_rect()
            cx = e.position().x() - self.drag_offset.x()
            cy = e.position().y() - self.drag_offset.y()
            # clamp to scaled rect
            cx = max(sr.left(), min(sr.right(), cx))
            cy = max(sr.top(), min(sr.bottom(), cy))
            x_rel = (cx - sr.left()) / max(1, sr.width())
            y_rel = (cy - sr.top()) / max(1, sr.height())
            self.settings.pos_rel = (float(x_rel), float(y_rel))
            self.cached_wm_pixmap = None
            self.update()
            self.positionChanged.emit(self.settings.pos_rel)

    def mouseReleaseEvent(self, e):
        self.dragging = False

