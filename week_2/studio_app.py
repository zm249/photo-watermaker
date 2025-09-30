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


# -------- UI: Control panel --------

class ControlPanel(QWidget):
    settingsChanged = Signal(WatermarkSettings)
    exportRequested = Signal()
    addFilesRequested = Signal()
    addFolderRequested = Signal()

    def __init__(self):
        super().__init__()
        self.st = WatermarkSettings()
        self.font_db = QFontDatabase()

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignTop)

        # Import group
        grp_import = QGroupBox("文件处理")
        ly_imp = QHBoxLayout()
        btn_add_files = QPushButton("导入图片…")
        btn_add_dir = QPushButton("导入文件夹…")
        btn_add_files.clicked.connect(self.addFilesRequested.emit)
        btn_add_dir.clicked.connect(self.addFolderRequested.emit)
        ly_imp.addWidget(btn_add_files)
        ly_imp.addWidget(btn_add_dir)
        grp_import.setLayout(ly_imp)
        root.addWidget(grp_import)

        # Watermark type
        grp_type = QGroupBox("水印类型")
        ly_type = QHBoxLayout()
        self.rb_text = QRadioButton("文本")
        self.rb_img = QRadioButton("图片")
        self.rb_text.setChecked(True)
        self.rb_text.toggled.connect(self.on_type_changed)
        ly_type.addWidget(self.rb_text)
        ly_type.addWidget(self.rb_img)
        grp_type.setLayout(ly_type)
        root.addWidget(grp_type)

        # Text settings
        grp_text = QGroupBox("文本水印")
        form_t = QFormLayout()
        self.ed_text = QLineEdit(self.st.text)
        self.cmb_font = QComboBox()
        self.cmb_font.addItems(self.font_db.families())
        # default select
        idx = self.cmb_font.findText(self.st.font_family)
        if idx >= 0: self.cmb_font.setCurrentIndex(idx)
        self.spin_font = QSpinBox()
        self.spin_font.setRange(6, 512)
        self.spin_font.setValue(self.st.font_point)
        self.chk_bold = QCheckBox("粗体")
        self.chk_bold.setChecked(self.st.font_bold)
        self.chk_italic = QCheckBox("斜体")
        self.chk_italic.setChecked(self.st.font_italic)
        self.btn_color = QPushButton("颜色…")
        self.lbl_color = QLabel(self.st.color_rgba)
        self.btn_color.clicked.connect(self.pick_color)
        self.chk_shadow = QCheckBox("阴影")
        self.chk_shadow.setChecked(self.st.shadow)
        form_t.addRow("内容", self.ed_text)
        row_font = QHBoxLayout()
        row_font.addWidget(self.cmb_font)
        row_font.addWidget(self.spin_font)
        row_font.addWidget(self.chk_bold)
        row_font.addWidget(self.chk_italic)
        w_row_font = QWidget()
        w_row_font.setLayout(row_font)
        form_t.addRow("字体/字号", w_row_font)
        row_col = QHBoxLayout()
        row_col.addWidget(self.btn_color)
        row_col.addWidget(self.lbl_color)
        w_row_col = QWidget()
        w_row_col.setLayout(row_col)
        form_t.addRow("颜色", w_row_col)
        form_t.addRow(self.chk_shadow)
        grp_text.setLayout(form_t)
        root.addWidget(grp_text)

        # Image watermark
        grp_img = QGroupBox("图片水印")
        form_i = QFormLayout()
        self.ed_img = QLineEdit(self.st.image_path)
        self.btn_img = QPushButton("选择图片…")
        self.btn_img.clicked.connect(self.pick_image)
        row_img = QHBoxLayout()
        row_img.addWidget(self.ed_img)
        row_img.addWidget(self.btn_img)
        w_row_img = QWidget()
        w_row_img.setLayout(row_img)
        self.sld_img_scale = QSlider(Qt.Horizontal)
        self.sld_img_scale.setRange(5, 300)
        self.sld_img_scale.setValue(self.st.image_scale_pct)
        form_i.addRow("文件", w_row_img)
        form_i.addRow("缩放(%)", self.sld_img_scale)
        grp_img.setLayout(form_i)
        root.addWidget(grp_img)

        # Common style
        grp_style = QGroupBox("样式")
        form_s = QFormLayout()
        self.sld_opacity = QSlider(Qt.Horizontal)
        self.sld_opacity.setRange(0, 100)
        self.sld_opacity.setValue(self.st.opacity)
        self.spin_rotation = QSpinBox()
        self.spin_rotation.setRange(-180, 180)
        self.spin_rotation.setValue(int(self.st.rotation))
        form_s.addRow("透明度(%)", self.sld_opacity)
        form_s.addRow("旋转(°)", self.spin_rotation)
        grp_style.setLayout(form_s)
        root.addWidget(grp_style)

        # Position
        grp_pos = QGroupBox("位置")
        grid = QGridLayout()
        self.pos_buttons: List[QPushButton] = []
        positions = [
            ("↖", 0.0, 0.0), ("↑", 0.5, 0.0), ("↗", 1.0, 0.0),
            ("←", 0.0, 0.5), ("●", 0.5, 0.5), ("→", 1.0, 0.5),
            ("↙", 0.0, 1.0), ("↓", 0.5, 1.0), ("↘", 1.0, 1.0),
        ]
        for i, (txt, x, y) in enumerate(positions):
            btn = QPushButton(txt)
            btn.clicked.connect(lambda _, xx=x, yy=y: self.set_nine_grid(xx, yy))
            self.pos_buttons.append(btn)
            grid.addWidget(btn, i // 3, i % 3)
        grp_pos.setLayout(grid)
        root.addWidget(grp_pos)

        # Export
        grp_exp = QGroupBox("导出")
        form_e = QFormLayout()
        self.ed_out = QLineEdit(self.st.out_dir)
        self.btn_out = QPushButton("选择输出目录…")
        self.btn_out.clicked.connect(self.pick_out_dir)
        row_out = QHBoxLayout()
        row_out.addWidget(self.ed_out)
        row_out.addWidget(self.btn_out)
        w_row_out = QWidget()
        w_row_out.setLayout(row_out)
        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItems(["PNG", "JPEG"])
        self.cmb_fmt.setCurrentText(self.st.out_format)
        self.sld_quality = QSlider(Qt.Horizontal)
        self.sld_quality.setRange(0, 100)
        self.sld_quality.setValue(self.st.jpeg_quality)
        self.lbl_quality = QLabel(f"{self.st.jpeg_quality}")
        row_q = QHBoxLayout()
        row_q.addWidget(self.sld_quality)
        row_q.addWidget(self.lbl_quality)
        w_row_q = QWidget()
        w_row_q.setLayout(row_q)

        # resize
        self.cmb_resize = QComboBox()
        self.cmb_resize.addItems(["不缩放", "按宽", "按高", "按百分比"])
        self.cmb_resize.setCurrentIndex(0)
        self.ed_resize = QLineEdit()
        self.ed_resize.setPlaceholderText("像素或百分比")
        self.ed_resize.setValidator(QIntValidator(0, 10000))
        row_r = QHBoxLayout()
        row_r.addWidget(self.cmb_resize)
        row_r.addWidget(self.ed_resize)
        w_row_r = QWidget()
        w_row_r.setLayout(row_r)

        # naming
        self.cmb_name = QComboBox()
        self.cmb_name.addItems(["保留原名", "前缀", "后缀"])
        self.ed_prefix = QLineEdit(self.st.name_prefix)
        self.ed_suffix = QLineEdit(self.st.name_suffix)
        row_n = QHBoxLayout()
        row_n.addWidget(self.cmb_name)
        row_n.addWidget(QLabel("前缀:"))
        row_n.addWidget(self.ed_prefix)
        row_n.addWidget(QLabel("后缀:"))
        row_n.addWidget(self.ed_suffix)
        w_row_n = QWidget()
        w_row_n.setLayout(row_n)

        self.btn_export = QPushButton("开始导出")
        self.btn_export.clicked.connect(self.exportRequested.emit)

        form_e.addRow("输出目录", w_row_out)
        form_e.addRow("格式", self.cmb_fmt)
        form_e.addRow("JPEG质量", w_row_q)
        form_e.addRow("尺寸调整", w_row_r)
        form_e.addRow("命名规则", w_row_n)
        form_e.addRow(self.btn_export)
        grp_exp.setLayout(form_e)
        root.addWidget(grp_exp)

        # Templates
        grp_tpl = QGroupBox("水印模板")
        ly_tpl = QHBoxLayout()
        self.cmb_tpl = QComboBox()
        self.btn_tpl_save = QPushButton("保存…")
        self.btn_tpl_del = QPushButton("删除")
        self.btn_tpl_save.clicked.connect(self.save_template)
        self.btn_tpl_del.clicked.connect(self.delete_template)
        ly_tpl.addWidget(self.cmb_tpl)
        ly_tpl.addWidget(self.btn_tpl_save)
        ly_tpl.addWidget(self.btn_tpl_del)
        grp_tpl.setLayout(ly_tpl)
        root.addWidget(grp_tpl)

        root.addStretch(1)

        # signal wiring
        for w in [
            self.ed_text, self.cmb_font, self.spin_font,
            self.chk_bold, self.chk_italic, self.chk_shadow,
            self.sld_opacity, self.spin_rotation, self.ed_img,
            self.sld_img_scale, self.cmb_fmt, self.sld_quality,
            self.cmb_resize, self.ed_resize, self.rb_text, self.rb_img,
            self.ed_out, self.cmb_name, self.ed_prefix, self.ed_suffix
        ]:
            if isinstance(w, (QLineEdit,)):
                w.textChanged.connect(self.emit_settings)
            elif isinstance(w, (QComboBox,)):
                w.currentIndexChanged.connect(self.emit_settings)
            elif isinstance(w, (QCheckBox, QRadioButton)):
                w.toggled.connect(self.emit_settings)
            elif isinstance(w, (QSpinBox,)):
                w.valueChanged.connect(self.emit_settings)
            elif isinstance(w, (QSlider,)):
                w.valueChanged.connect(self.emit_settings)

        self.sld_quality.valueChanged.connect(lambda v: self.lbl_quality.setText(str(v)))
        self.cmb_fmt.currentTextChanged.connect(self.toggle_quality_enabled)
        self.toggle_quality_enabled(self.cmb_fmt.currentText())

        self.reload_templates_combo()
        # try load last settings
        self.try_load_last()

    def on_type_changed(self, checked: bool):
        self.emit_settings()

    def toggle_quality_enabled(self, fmt: str):
        enabled = (fmt.upper() == "JPEG")
        self.sld_quality.setEnabled(enabled)
        self.lbl_quality.setEnabled(enabled)

    def pick_color(self):
        c0 = qcolor_from_rgba_str(self.st.color_rgba)
        c = QColorDialog.getColor(c0, self, "选择颜色", QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self.st.color_rgba = c.name(QColor.HexArgb)
            self.lbl_color.setText(self.st.color_rgba)
            self.emit_settings()

    def pick_image(self):
        fn, _ = QFileDialog.getOpenFileName(self, "选择水印图片", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if fn:
            self.ed_img.setText(fn)

    def pick_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.ed_out.setText(d)

    def set_nine_grid(self, x: float, y: float):
        # apply margin
        m = self.st.margin_rel
        rx = (x * (1 - 2 * m)) + m
        ry = (y * (1 - 2 * m)) + m
        rx = min(1.0, max(0.0, rx))
        ry = min(1.0, max(0.0, ry))
        self.st.pos_rel = (rx, ry)
        self.emit_settings()

    def emit_settings(self):
        # gather UI -> settings
        st = self.st
        st.wm_type = "text" if self.rb_text.isChecked() else "image"
        st.text = self.ed_text.text()
        st.font_family = self.cmb_font.currentText()
        st.font_point = self.spin_font.value()
        st.font_bold = self.chk_bold.isChecked()
        st.font_italic = self.chk_italic.isChecked()
        st.shadow = self.chk_shadow.isChecked()
        st.opacity = self.sld_opacity.value()
        st.rotation = float(self.spin_rotation.value())
        st.image_path = self.ed_img.text()
        st.image_scale_pct = self.sld_img_scale.value()
        st.out_dir = self.ed_out.text()
        st.out_format = self.cmb_fmt.currentText()
        st.jpeg_quality = self.sld_quality.value()
        idx_resize = self.cmb_resize.currentIndex()
        st.resize_mode = ["none", "width", "height", "percent"][idx_resize]
        st.resize_value = int(self.ed_resize.text() or "0")
        nm_idx = self.cmb_name.currentIndex()
        st.name_mode = ["original", "prefix", "suffix"][nm_idx]
        st.name_prefix = self.ed_prefix.text()
        st.name_suffix = self.ed_suffix.text()
        self.settingsChanged.emit(st)

    # templates
    def reload_templates_combo(self):
        self.cmb_tpl.clear()
        tdir = templates_dir()
        names = [p.stem for p in tdir.glob("*.json")]
        self.cmb_tpl.addItems(sorted(names))
        if self.cmb_tpl.count() > 0:
            self.cmb_tpl.setCurrentIndex(0)
            self.cmb_tpl.currentTextChanged.connect(self.load_template)

    def save_template(self):
        name, ok = QFileDialog.getSaveFileName(self, "保存模板为…", str(templates_dir() / "template.json"),
                                               "JSON (*.json)")
        if not name:
            return
        self.emit_settings()
        try:
            with open(name, "w", encoding="utf-8") as f:
                json.dump(self.st.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：\n{e}")
            return
        self.reload_templates_combo()

    def load_template(self, stem: str):
        p = templates_dir() / f"{stem}.json"
        if not p.exists():
            return
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            self.st = WatermarkSettings.from_dict(d)
            self.sync_ui_from_settings()
            self.settingsChanged.emit(self.st)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载失败：\n{e}")

    def delete_template(self):
        stem = self.cmb_tpl.currentText()
        if not stem:
            return
        p = templates_dir() / f"{stem}.json"
        if p.exists():
            p.unlink()
        self.reload_templates_combo()

    def sync_ui_from_settings(self):
        st = self.st
        self.rb_text.setChecked(st.wm_type == "text")
        self.rb_img.setChecked(st.wm_type == "image")
        self.ed_text.setText(st.text)
        i = self.cmb_font.findText(st.font_family)
        if i >= 0: self.cmb_font.setCurrentIndex(i)
        self.spin_font.setValue(st.font_point)
        self.chk_bold.setChecked(st.font_bold)
        self.chk_italic.setChecked(st.font_italic)
        self.lbl_color.setText(st.color_rgba)
        self.chk_shadow.setChecked(st.shadow)
        self.sld_opacity.setValue(st.opacity)
        self.spin_rotation.setValue(int(st.rotation))
        self.ed_img.setText(st.image_path)
        self.sld_img_scale.setValue(st.image_scale_pct)
        self.ed_out.setText(st.out_dir)
        self.cmb_fmt.setCurrentText(st.out_format)
        self.sld_quality.setValue(st.jpeg_quality)
        self.cmb_resize.setCurrentIndex(["none", "width", "height", "percent"].index(st.resize_mode))
        self.ed_resize.setText(str(st.resize_value or ""))
        self.cmb_name.setCurrentIndex(["original", "prefix", "suffix"].index(st.name_mode))
        self.ed_prefix.setText(st.name_prefix)
        self.ed_suffix.setText(st.name_suffix)
        self.toggle_quality_enabled(st.out_format)
        # note: pos_rel stays in preview

    def try_load_last(self):
        p = last_settings_path()
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                self.st = WatermarkSettings.from_dict(d)
                self.sync_ui_from_settings()
                self.settingsChanged.emit(self.st)
            except Exception:
                pass


# -------- Main Window --------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("水印工具 - Code Copilot")
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self.images = ImageListPanel()
        self.preview = PreviewCanvas()
        self.controls = ControlPanel()

        self.controls.settingsChanged.connect(self.on_settings_changed)
        self.controls.exportRequested.connect(self.on_export)
        self.controls.addFilesRequested.connect(self.on_add_files)
        self.controls.addFolderRequested.connect(self.on_add_folder)
        self.preview.positionChanged.connect(self.on_preview_pos_changed)
        self.images.itemSelectionChanged.connect(self.on_selection_changed)

        # Layout
        splitter = QSplitter()
        splitter.addWidget(self.images)
        # Right composite: preview + controls (scroll)
        right = QSplitter(Qt.Vertical)
        right.addWidget(self.preview)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.controls)
        right.addWidget(scroll)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self.setCentralWidget(splitter)

        # toolbar
        tb = QToolBar("主工具栏")
        self.addToolBar(tb)
        act_add = QAction("导入图片", self)
        act_add.triggered.connect(self.on_add_files)
        act_add_dir = QAction("导入文件夹", self)
        act_add_dir.triggered.connect(self.on_add_folder)
        act_rm = QAction("移除所选", self)
        act_rm.triggered.connect(self.images.remove_selected)
        act_clear = QAction("清空列表", self)
        act_clear.triggered.connect(self.images.clear_all)
        tb.addActions([act_add, act_add_dir, act_rm, act_clear])

        self.setStatusBar(QStatusBar(self))

        # load last selected preview
        self.images.filesChanged.connect(self.ensure_preview_loaded)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        urls = e.mimeData().urls()
        paths = [Path(u.toLocalFile()) for u in urls]
        imgs = enumerate_images(paths)
        self.images.add_images(imgs)
        self.ensure_preview_loaded()

    def ensure_preview_loaded(self):
        # pick first if none selected
        if self.images.count() > 0 and len(self.images.selectedItems()) == 0:
            self.images.setCurrentRow(0)
            self.on_selection_changed()

    def on_selection_changed(self):
        row = self.images.currentRow()
        if row < 0 or row >= len(self.images.paths):
            self.preview.set_image(None)
            return
        img = load_qimage(self.images.paths[row])
        self.preview.set_image(img)

    def on_settings_changed(self, st: WatermarkSettings):
        self.preview.set_settings(st)
        # persist last
        try:
            last_settings_path().write_text(json.dumps(st.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def on_preview_pos_changed(self, rel: tuple):
        # nothing to do settings already updated by canvas
        pass

    def on_add_files(self):
        fns, _ = QFileDialog.getOpenFileNames(self, "导入图片", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if fns:
            self.images.add_images([Path(f) for f in fns])
            self.ensure_preview_loaded()

    def on_add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "导入文件夹")
        if d:
            imgs = enumerate_images([Path(d)])
            self.images.add_images(imgs)
            self.ensure_preview_loaded()

    # --- export pipeline ---

    def build_watermark_layer(self, base_size: QSize, st: WatermarkSettings) -> Optional[QPixmap]:
        canvas = PreviewCanvas()  # reuse logic why: single source of truth for wm rendering
        canvas.settings = st
        # Build wm pixmap for full-size base (not scaled preview)
        wm = canvas.build_watermark_pixmap(base_size)
        return wm

    def compose_image(self, src_img: QImage, st: WatermarkSettings) -> QImage:
        base = src_img
        # optional resize
        if st.resize_mode != "none" and st.resize_value > 0:
            w, h = base.width(), base.height()
            if st.resize_mode == "width" and st.resize_value < w:
                new_w = st.resize_value
                new_h = int(h * (new_w / w))
                base = base.scaled(new_w, new_h, Qt.IgnoreAspectRatio if new_h == 0 else Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation)
            elif st.resize_mode == "height" and st.resize_value < h:
                new_h = st.resize_value
                new_w = int(w * (new_h / h))
                base = base.scaled(new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            elif st.resize_mode == "percent":
                scale = max(1, st.resize_value) / 100.0
                base = base.scaled(int(w * scale), int(h * scale), Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # watermark
        wm = self.build_watermark_layer(base.size(), st)
        if wm is None:
            return base

        # compute draw position
        painter = QPainter()
        out = QImage(base.size(), QImage.Format.Format_ARGB32)
        out.fill(Qt.transparent)
        painter.begin(out)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(0, 0, base)
        cx = st.pos_rel[0] * base.width()
        cy = st.pos_rel[1] * base.height()
        x = int(cx - wm.width() / 2)
        y = int(cy - wm.height() / 2)
        painter.setOpacity(max(0.0, min(1.0, st.opacity / 100.0)))
        painter.drawPixmap(x, y, wm)
        painter.end()
        return out

    def compute_out_name(self, src: Path, st: WatermarkSettings, fmt: str) -> str:
        stem = src.stem
        if st.name_mode == "prefix":
            stem = f"{st.name_prefix}{stem}"
        elif st.name_mode == "suffix":
            stem = f"{stem}{st.name_suffix}"
        ext = ".png" if fmt.upper() == "PNG" else ".jpg"
        return stem + ext

    def on_export(self):
        st = self.preview.settings
        # validations
        if len(self.images.paths) == 0:
            QMessageBox.warning(self, "提示", "请先导入图片。")
            return
        if not st.out_dir:
            QMessageBox.warning(self, "提示", "请选择输出目录。")
            return
        out_dir = Path(st.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # forbid exporting to source directories by default
        src_dirs = {p.parent.resolve() for p in self.images.paths}
        if out_dir.resolve() in src_dirs:
            QMessageBox.warning(self, "提示", "为防覆盖，禁止导出到原图所在目录，请选择其他目录。")
            return

        # watermark validity
        if st.wm_type == "text" and not st.text.strip():
            QMessageBox.warning(self, "提示", "文本水印内容不能为空。")
            return
        if st.wm_type == "image" and not Path(st.image_path).exists():
            QMessageBox.warning(self, "提示", "请选择有效的图片水印文件。")
            return

        fmt = st.out_format.upper()
        errors = []
        progress = QProgressDialog("正在导出…", "取消", 0, len(self.images.paths), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        for i, src in enumerate(self.images.paths):
            progress.setValue(i)
            progress.setLabelText(f"处理：{src.name}")
            QApplication.processEvents()
            if progress.wasCanceled():
                break
            try:
                img = load_qimage(src)
                if img is None:
                    raise RuntimeError("无法读取图片")
                out_img = self.compose_image(img, st)
                out_name = self.compute_out_name(src, st, fmt)
                dest = out_dir / out_name
                if not save_qimage(out_img, dest, fmt, st.jpeg_quality):
                    raise RuntimeError("保存失败")
            except Exception as e:
                errors.append(f"{src.name}: {e}")
        progress.setValue(len(self.images.paths))

        if errors:
            QMessageBox.warning(self, "完成但有错误",
                                "以下文件失败：\n" + "\n".join(errors[:20]) + ("\n..." if len(errors) > 20 else ""))
        else:
            QMessageBox.information(self, "完成", f"已导出到：\n{out_dir}")


# -------- entry --------

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
