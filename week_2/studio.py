#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Watermark Studio – 本地批量图片文字/图片水印工具（Windows / macOS）

依赖：
  - Python 3.8+
  - PySide6 (GUI 与图像读写)

安装：
  pip install PySide6

运行：
  python watermark_studio.py

功能覆盖（与需求对照）
1. 文件处理
   1.1 导入图片：单张/多张/整文件夹，支持拖拽；左侧缩略图列表
   1.2 支持格式：输入 JPEG/PNG（透明）/BMP/TIFF；输出 JPEG/PNG
   1.3 导出图片：
       - 指定输出目录（默认阻止导出到任意源图片所在目录）
       - 命名规则：保留原名 / 前缀 / 后缀
       - JPEG 质量滑块；可选按宽/高/百分比缩放
2. 水印类型
   2.1 文本水印：内容/字体（系统字体）/字号/粗体/斜体/颜色/透明度/描边/阴影
   2.2 图片水印：本地 PNG（含透明）、缩放、透明度
3. 布局与样式
   - 实时预览：中央预览区
   - 位置：九宫格一键定位 + 预览中拖拽到任意位置
   - 旋转：任意角度
4. 配置管理
   - 水印模板保存/加载/删除；
   - 退出自动保存最近一次配置并在启动时加载

技术说明：
 - 统一使用 Qt 的 QImage/QPainter 完成预览与导出（避免字体文件路径平台差异）。
 - 位置采用“归一化中心坐标”（0..1）表示，保证不同尺寸图像一致的布局。
 - 预览中的拖拽直接更新归一化坐标；导出时按原图尺寸精确计算。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import (Qt, QPointF, QRectF, QSize, Signal)
from PySide6.QtGui import (QAction, QColor, QFont, QFontDatabase, QIcon, QImage,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QProgressDialog, QPushButton, QRadioButton,
    QSlider, QSpinBox, QStyle, QTabWidget, QToolBar, QVBoxLayout, QWidget)

APP_NAME = "Watermark Studio"
SUPPORTED_INPUT_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff'}
DEFAULT_CONFIG_DIR = Path.home() / ".watermark_studio"
DEFAULT_TPL_DIR = DEFAULT_CONFIG_DIR / "templates"
LAST_CONFIG_FILE = DEFAULT_CONFIG_DIR / "last.json"


def ensure_dirs():
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_TPL_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TextWatermark:
    enabled: bool = True
    text: str = "示例水印 Sample"
    font_family: str = "Arial"
    font_size_pt: int = 36
    bold: bool = False
    italic: bool = False
    color_rgba: Tuple[int, int, int, int] = (255, 255, 255, 200)  # RGBA
    stroke_enabled: bool = False
    stroke_color_rgba: Tuple[int, int, int, int] = (0, 0, 0, 180)
    stroke_width_px: int = 2
    shadow_enabled: bool = False
    shadow_offset_px: int = 2
    shadow_alpha: int = 120


@dataclass
class ImageWatermark:
    enabled: bool = False
    image_path: str = ""
    scale_percent: int = 30  # 相对原图宽度的百分比
    opacity: int = 70  # 0..100


@dataclass
class LayoutStyle:
    # 位置用归一化中心坐标（0..1）
    pos_x: float = 0.5
    pos_y: float = 0.5
    rotation_deg: int = 0
    margin_percent: float = 2.0  # 九宫格边距（相对短边）


@dataclass
class ExportSettings:
    output_dir: str = str(Path.home() / "Pictures" / "watermarked")
    forbid_source_dir: bool = True
    format: str = "PNG"  # PNG or JPEG
    jpeg_quality: int = 90  # 0..100
    resize_mode: str = "None"  # None | Width | Height | Percent
    resize_value: int = 100
    naming_rule: str = "suffix"  # keep | prefix | suffix
    prefix: str = "wm_"
    suffix: str = "_watermarked"


@dataclass
class WatermarkConfig:
    text: TextWatermark = TextWatermark()
    image: ImageWatermark = ImageWatermark()
    layout: LayoutStyle = LayoutStyle()
    export: ExportSettings = ExportSettings()

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @staticmethod
    def from_json(s: str) -> "WatermarkConfig":
        d = json.loads(s)
        return WatermarkConfig(
            text=TextWatermark(**d.get('text', {})),
            image=ImageWatermark(**d.get('image', {})),
            layout=LayoutStyle(**d.get('layout', {})),
            export=ExportSettings(**d.get('export', {})),
        )


class PreviewWidget(QLabel):
    """中央预览区：显示当前图片并绘制水印，支持拖拽调整位置。"""
    positionChanged = Signal(float, float)  # pos_x, pos_y

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 360)
        self._base_image: Optional[QImage] = None  # 原图
        self._display_pixmap: Optional[QPixmap] = None  # 适配窗口后的预览图
        self._config: Optional[WatermarkConfig] = None
        self._dragging = False
        self._last_mouse = None
        self._wm_bbox_screen = QRectF()  # 水印在屏幕坐标下的外接矩形（用于点中判断）

    def setImage(self, img: Optional[QImage]):
        self._base_image = img
        self._updateDisplayPixmap()
        self.update()

    def setConfig(self, cfg: WatermarkConfig):
        self._config = cfg
        self.update()

    def resizeEvent(self, e):
        self._updateDisplayPixmap()
        super().resizeEvent(e)

    def _updateDisplayPixmap(self):
        if self._base_image is None:
            self._display_pixmap = None
            return
        area = self.size()
        px = QPixmap.fromImage(self._base_image)
        self._display_pixmap = px.scaled(area, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._display_pixmap is None or self._config is None:
            return
        painter = QPainter(self)
        # 将预览图居中绘制
        pix = self._display_pixmap
        x = (self.width() - pix.width()) // 2
        y = (self.height() - pix.height()) // 2
        painter.drawPixmap(x, y, pix)

        # 在预览尺寸上绘制水印（按归一化坐标）
        img_w, img_h = pix.width(), pix.height()
        cx = x + self._config.layout.pos_x * img_w
        cy = y + self._config.layout.pos_y * img_h

        # 先生成水印图层（透明 QImage）
        wm_img, wm_rect_local = self._render_watermark_layer(int(img_w), int(img_h))
        if wm_img is None:
            return
        # 计算旋转后的外接矩形，用于命中测试与可视化
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._config.layout.rotation_deg)
        painter.translate(-wm_img.width()/2, -wm_img.height()/2)
        painter.drawImage(0, 0, wm_img)
        painter.restore()

        # 估算屏幕坐标下的包围盒（不考虑旋转的精确包围盒，这里用旋转后的近似）
        # 用四个角点旋转后再取外接矩形
        from math import cos, sin, radians
        rad = radians(self._config.layout.rotation_deg)
        c, s = cos(rad), sin(rad)
        w, h = wm_img.width(), wm_img.height()
        corners = [QPointF(-w/2, -h/2), QPointF(w/2, -h/2), QPointF(w/2, h/2), QPointF(-w/2, h/2)]
        rotated = [QPointF(c*p.x()-s*p.y(), s*p.x()+c*p.y()) for p in corners]
        minx = min(p.x() for p in rotated) + cx
        maxx = max(p.x() for p in rotated) + cx
        miny = min(p.y() for p in rotated) + cy
        maxy = max(p.y() for p in rotated) + cy
        self._wm_bbox_screen = QRectF(minx, miny, maxx-minx, maxy-miny)

    def _render_watermark_layer(self, view_w: int, view_h: int) -> Tuple[Optional[QImage], QRectF]:
        cfg = self._config
        if cfg is None:
            return None, QRectF()
        # 生成尽可能紧凑的水印图层（包含文本和/或图片）
        # 文本按字号绘制到几乎贴边的透明画布；图片水印按比例缩放到指定宽度。
        # 最终合成为一个透明 QImage，便于统一旋转和平移。
        # 先估计文本图层大小
        layers: List[QImage] = []
        # 文本
        if cfg.text.enabled and cfg.text.text.strip():
            layers.append(self._render_text_layer(cfg.text))
        # 图片
        if cfg.image.enabled and cfg.image.image_path:
            img_layer = self._render_logo_layer(cfg.image, view_w)
            if img_layer is not None:
                layers.append(img_layer)
        if not layers:
            return None, QRectF()
        # 将多层（如果都启用）合成，采用“叠加并排”策略：
        # 为简化，这里选择“上层覆盖下层”，并取最大宽高的画布。
        W = max(im.width() for im in layers)
        H = max(im.height() for im in layers)
        canvas = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        canvas.fill(0)
        p = QPainter(canvas)
        for im in layers:
            x = (W - im.width()) // 2
            y = (H - im.height()) // 2
            p.drawImage(x, y, im)
        p.end()
        return canvas, QRectF(0, 0, W, H)

    def _render_text_layer(self, tcfg: TextWatermark) -> QImage:
        # 先用一个较大画布估算文字外接矩形，再裁剪
        tmp_w, tmp_h = 4096, 1024
        img = QImage(tmp_w, tmp_h, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        painter = QPainter(img)
        font = QFont(tcfg.font_family, tcfg.font_size_pt)
        font.setBold(tcfg.bold)
        font.setItalic(tcfg.italic)
        painter.setFont(font)

        path = QPainterPath()
        path.addText(20, 80, font, tcfg.text)
        br = path.boundingRect()

        # 重新创建紧凑画布
        W = max(1, int(br.width()) + 40)
        H = max(1, int(br.height()) + 40)
        img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setFont(font)

        # 阴影
        if tcfg.shadow_enabled:
            shadow_col = QColor(0, 0, 0, max(0, min(255, tcfg.shadow_alpha)))
            painter.translate(tcfg.shadow_offset_px, tcfg.shadow_offset_px)
            painter.setPen(Qt.NoPen)
            painter.setBrush(shadow_col)
            painter.drawPath(path.translated(-br.left()+20, -br.top()+20))
            painter.translate(-tcfg.shadow_offset_px, -tcfg.shadow_offset_px)

        # 文字主体
        fill_col = QColor(*tcfg.color_rgba)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill_col)
        painter.drawPath(path.translated(-br.left()+20, -br.top()+20))

        # 描边
        if tcfg.stroke_enabled and tcfg.stroke_width_px > 0:
            pen = QPen(QColor(*tcfg.stroke_color_rgba))
            pen.setWidth(max(1, tcfg.stroke_width_px))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path.translated(-br.left()+20, -br.top()+20))

        painter.end()
        # 透明度整体控制（通过全局 alpha 调整）
        if tcfg.color_rgba[3] < 255:
            # 已在 fill 颜色中包含 alpha；若需要整体再降透明，可在绘制时 setOpacity。
            pass
        return img

    def _render_logo_layer(self, icfg: ImageWatermark, view_w: int) -> Optional[QImage]:
        path = Path(icfg.image_path)
        if not path.exists():
            return None
        src = QImage(str(path))
        if src.isNull():
            return None
        # 目标宽度（相对预览宽度比例以获得更直观的缩放体验）
        target_w = max(1, int(view_w * max(1, icfg.scale_percent) / 100.0))
        scaled = src.scaledToWidth(target_w, Qt.SmoothTransformation)
        if icfg.opacity < 100:
            # 通过绘制到透明画布并设置 painter 不透明度控制
            canvas = QImage(scaled.size(), QImage.Format_ARGB32_Premultiplied)
            canvas.fill(0)
            p = QPainter(canvas)
            p.setOpacity(max(0.0, min(1.0, icfg.opacity / 100.0)))
            p.drawImage(0, 0, scaled)
            p.end()
            return canvas
        return scaled

    # ---- 拖拽移动水印 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._display_pixmap is not None:
            if self._wm_bbox_screen.contains(event.position().toPoint()):
                self._dragging = True
                self._last_mouse = event.position()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._display_pixmap is not None and self._config is not None:
            delta = event.position() - self._last_mouse
            self._last_mouse = event.position()
            # 将像素位移转换到归一化坐标（相对当前预览图尺寸）
            img_w, img_h = self._display_pixmap.width(), self._display_pixmap.height()
            dx = delta.x() / max(1, img_w)
            dy = delta.y() / max(1, img_h)
            self._config.layout.pos_x = min(1.0, max(0.0, self._config.layout.pos_x + dx))
            self._config.layout.pos_y = min(1.0, max(0.0, self._config.layout.pos_y + dy))
            self.positionChanged.emit(self._config.layout.pos_x, self._config.layout.pos_y)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ControlPanel(QWidget):
    """右侧控制面板：文本水印、图片水印、布局旋转、导出设置。"""
    configChanged = Signal()

    def __init__(self, cfg: WatermarkConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg

        tabs = QTabWidget()
        tabs.addTab(self._build_text_tab(), "文本水印")
        tabs.addTab(self._build_image_tab(), "图片水印")
        tabs.addTab(self._build_layout_tab(), "布局与旋转")
        tabs.addTab(self._build_export_tab(), "导出设置")

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addStretch(1)

    # ---- 文本水印 ----
    def _build_text_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        tcfg = self.cfg.text

        self.chk_text_enabled = QCheckBox("启用文本水印")
        self.chk_text_enabled.setChecked(tcfg.enabled)
        self.chk_text_enabled.toggled.connect(self._on_changed)

        self.edt_text = QLineEdit(tcfg.text)
        self.edt_text.textChanged.connect(self._on_changed)

        self.font_combo = QComboBox()
        self.font_combo.addItems(QFontDatabase().families())
        idx = self.font_combo.findText(tcfg.font_family)
        if idx >= 0: self.font_combo.setCurrentIndex(idx)
        self.font_combo.currentTextChanged.connect(self._on_changed)

        self.spin_fontsize = QSpinBox(); self.spin_fontsize.setRange(6, 400)
        self.spin_fontsize.setValue(tcfg.font_size_pt)
        self.spin_fontsize.valueChanged.connect(self._on_changed)

        self.chk_bold = QCheckBox("粗体"); self.chk_bold.setChecked(tcfg.bold)
        self.chk_bold.toggled.connect(self._on_changed)
        self.chk_italic = QCheckBox("斜体"); self.chk_italic.setChecked(tcfg.italic)
        self.chk_italic.toggled.connect(self._on_changed)

        def make_color_button(init_col: Tuple[int,int,int,int], onpick):
            btn = QPushButton("选择颜色")
            col = QColor(*init_col)
            def update_btn_style(c: QColor):
                btn.setStyleSheet(f"background-color: rgba({c.red()},{c.green()},{c.blue()},{c.alpha()});")
            update_btn_style(col)
            def pick():
                c = QColorDialog.getColor(col, self, "选择颜色", QColorDialog.ShowAlphaChannel)
                if c.isValid():
                    update_btn_style(c)
                    onpick(c)
            btn.clicked.connect(pick)
            return btn

        self.btn_text_color = make_color_button(tcfg.color_rgba, lambda c: self._on_color_pick('text', c))

        self.sld_text_opacity = QSlider(Qt.Horizontal); self.sld_text_opacity.setRange(0, 100)
        self.sld_text_opacity.setValue(int(tcfg.color_rgba[3]*100/255))
        self.sld_text_opacity.valueChanged.connect(self._on_changed)

        # 高级：描边 & 阴影
        self.chk_stroke = QCheckBox("描边"); self.chk_stroke.setChecked(tcfg.stroke_enabled); self.chk_stroke.toggled.connect(self._on_changed)
        self.btn_stroke_color = make_color_button(tcfg.stroke_color_rgba, lambda c: self._on_color_pick('stroke', c))
        self.spin_stroke_w = QSpinBox(); self.spin_stroke_w.setRange(1, 20); self.spin_stroke_w.setValue(tcfg.stroke_width_px); self.spin_stroke_w.valueChanged.connect(self._on_changed)

        self.chk_shadow = QCheckBox("阴影"); self.chk_shadow.setChecked(tcfg.shadow_enabled); self.chk_shadow.toggled.connect(self._on_changed)
        self.spin_shadow_off = QSpinBox(); self.spin_shadow_off.setRange(0, 20); self.spin_shadow_off.setValue(tcfg.shadow_offset_px); self.spin_shadow_off.valueChanged.connect(self._on_changed)
        self.spin_shadow_alpha = QSpinBox(); self.spin_shadow_alpha.setRange(0, 255); self.spin_shadow_alpha.setValue(tcfg.shadow_alpha); self.spin_shadow_alpha.valueChanged.connect(self._on_changed)

        f.addRow(self.chk_text_enabled)
        f.addRow("内容", self.edt_text)
        f.addRow("字体", self.font_combo)
        f.addRow("字号", self.spin_fontsize)
        lay_bi = QHBoxLayout(); lay_bi.addWidget(self.chk_bold); lay_bi.addWidget(self.chk_italic); fb = QWidget(); fb.setLayout(lay_bi)
        f.addRow("样式", fb)
        f.addRow("颜色", self.btn_text_color)
        f.addRow("透明度(%)", self.sld_text_opacity)

        gb_adv = QGroupBox("高级（可选）")
        fa = QFormLayout(gb_adv)
        fa.addRow(self.chk_stroke)
        fa.addRow("描边颜色", self.btn_stroke_color)
        fa.addRow("描边像素", self.spin_stroke_w)
        fa.addRow(self.chk_shadow)
        fa.addRow("阴影偏移", self.spin_shadow_off)
        fa.addRow("阴影透明度(0-255)", self.spin_shadow_alpha)
        f.addRow(gb_adv)

        return w

    def _on_color_pick(self, which: str, c: QColor):
        if which == 'text':
            r, g, b, a = c.red(), c.green(), c.blue(), c.alpha()
            # 维持 slider 显示为 0..100
            self.sld_text_opacity.blockSignals(True)
            self.sld_text_opacity.setValue(int(a*100/255))
            self.sld_text_opacity.blockSignals(False)
            self.cfg.text.color_rgba = (r, g, b, a)
        elif which == 'stroke':
            self.cfg.text.stroke_color_rgba = (c.red(), c.green(), c.blue(), c.alpha())
        self.configChanged.emit()

    # ---- 图片水印 ----
    def _build_image_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        icfg = self.cfg.image
        self.chk_img_enabled = QCheckBox("启用图片水印"); self.chk_img_enabled.setChecked(icfg.enabled); self.chk_img_enabled.toggled.connect(self._on_changed)
        self.edt_img_path = QLineEdit(icfg.image_path)
        btn_browse = QPushButton("浏览…")
        def browse():
            p, _ = QFileDialog.getOpenFileName(self, "选择水印图片（建议 PNG 透明）", str(Path.home()), "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
            if p:
                self.edt_img_path.setText(p)
                self._on_changed()
        btn_browse.clicked.connect(browse)
        hb = QHBoxLayout(); hbw = QWidget(); hb.addWidget(self.edt_img_path); hb.addWidget(btn_browse); hbw.setLayout(hb)

        self.sld_img_scale = QSlider(Qt.Horizontal); self.sld_img_scale.setRange(5, 200); self.sld_img_scale.setValue(icfg.scale_percent); self.sld_img_scale.valueChanged.connect(self._on_changed)
        self.sld_img_opacity = QSlider(Qt.Horizontal); self.sld_img_opacity.setRange(0, 100); self.sld_img_opacity.setValue(icfg.opacity); self.sld_img_opacity.valueChanged.connect(self._on_changed)

        f.addRow(self.chk_img_enabled)
        f.addRow("图片路径", hbw)
        f.addRow("缩放(相对宽度%)", self.sld_img_scale)
        f.addRow("透明度(%)", self.sld_img_opacity)
        return w

    # ---- 布局与旋转 ----
    def _build_layout_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        lcfg = self.cfg.layout

        self.sld_rot = QSlider(Qt.Horizontal); self.sld_rot.setRange(-180, 180); self.sld_rot.setValue(lcfg.rotation_deg); self.sld_rot.valueChanged.connect(self._on_changed)

        # 九宫格
        grid = QWidget(); gl = QHBoxLayout(grid)
        left = QVBoxLayout(); mid = QVBoxLayout(); right = QVBoxLayout()
        def add_btn(vbox: QVBoxLayout, text: str, pos: Tuple[float,float]):
            b = QPushButton(text)
            def click():
                self.cfg.layout.pos_x, self.cfg.layout.pos_y = pos
                self.configChanged.emit()
            b.clicked.connect(click)
            vbox.addWidget(b)
        m = self.cfg.layout.margin_percent / 100.0
        # (x, y) 以 0..1 表示，边距基于 0.02 缓冲
        add_btn(left,  "左上", (0.0+m, 0.0+m))
        add_btn(left,  "左中", (0.0+m, 0.5))
        add_btn(left,  "左下", (0.0+m, 1.0-m))
        add_btn(mid,   "中上", (0.5, 0.0+m))
        add_btn(mid,   "正中", (0.5, 0.5))
        add_btn(mid,   "中下", (0.5, 1.0-m))
        add_btn(right, "右上", (1.0-m, 0.0+m))
        add_btn(right, "右中", (1.0-m, 0.5))
        add_btn(right, "右下", (1.0-m, 1.0-m))
        gl.addLayout(left); gl.addLayout(mid); gl.addLayout(right)

        f.addRow("旋转(°)", self.sld_rot)
        f.addRow(QLabel("九宫格一键定位"))
        f.addRow(grid)
        return w

    # ---- 导出设置 ----
    def _build_export_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        ecfg = self.cfg.export
        # 输出目录
        self.edt_outdir = QLineEdit(ecfg.output_dir)
        btn_dir = QPushButton("选择…")
        def pick_dir():
            d = QFileDialog.getExistingDirectory(self, "选择输出文件夹", ecfg.output_dir)
            if d:
                self.edt_outdir.setText(d)
                self._on_changed()
        btn_dir.clicked.connect(pick_dir)
        hb = QHBoxLayout(); hbw = QWidget(); hb.addWidget(self.edt_outdir); hb.addWidget(btn_dir); hbw.setLayout(hb)

        # 禁止导出到原文件夹
        self.chk_forbid_src = QCheckBox("禁止导出到任意源图片所在目录（推荐）")
        self.chk_forbid_src.setChecked(ecfg.forbid_source_dir)
        self.chk_forbid_src.toggled.connect(self._on_changed)

        # 输出格式
        self.rb_png = QRadioButton("PNG")
        self.rb_jpg = QRadioButton("JPEG")
        bg = QButtonGroup(w); bg.addButton(self.rb_png); bg.addButton(self.rb_jpg)
        if ecfg.format.upper() == 'PNG': self.rb_png.setChecked(True)
        else: self.rb_jpg.setChecked(True)
        self.rb_png.toggled.connect(self._on_changed)
        fmt_row = QWidget(); hl = QHBoxLayout(fmt_row); hl.addWidget(self.rb_png); hl.addWidget(self.rb_jpg)

        # JPEG 质量
        self.sld_quality = QSlider(Qt.Horizontal); self.sld_quality.setRange(0, 100); self.sld_quality.setValue(ecfg.jpeg_quality)
        self.sld_quality.valueChanged.connect(self._on_changed)

        # 缩放
        self.cmb_resize = QComboBox(); self.cmb_resize.addItems(["None", "Width", "Height", "Percent"]) ; self.cmb_resize.setCurrentText(ecfg.resize_mode); self.cmb_resize.currentTextChanged.connect(self._on_changed)
        self.spin_resize = QSpinBox(); self.spin_resize.setRange(1, 10000); self.spin_resize.setValue(ecfg.resize_value); self.spin_resize.valueChanged.connect(self._on_changed)
        rr = QWidget(); rrl = QHBoxLayout(rr); rrl.addWidget(self.cmb_resize); rrl.addWidget(self.spin_resize)

        # 命名规则
        self.rb_keep = QRadioButton("保留原文件名")
        self.rb_prefix = QRadioButton("前缀")
        self.rb_suffix = QRadioButton("后缀")
        nbg = QButtonGroup(w); nbg.addButton(self.rb_keep); nbg.addButton(self.rb_prefix); nbg.addButton(self.rb_suffix)
        if ecfg.naming_rule == 'keep': self.rb_keep.setChecked(True)
        elif ecfg.naming_rule == 'prefix': self.rb_prefix.setChecked(True)
        else: self.rb_suffix.setChecked(True)
        self.edt_prefix = QLineEdit(ecfg.prefix)
        self.edt_suffix = QLineEdit(ecfg.suffix)
        nr = QWidget(); nrl = QHBoxLayout(nr); nrl.addWidget(self.rb_keep); nrl.addWidget(self.rb_prefix); nrl.addWidget(self.edt_prefix); nrl.addWidget(self.rb_suffix); nrl.addWidget(self.edt_suffix)

        f.addRow("输出目录", hbw)
        f.addRow(self.chk_forbid_src)
        f.addRow("输出格式", fmt_row)
        f.addRow("JPEG 质量", self.sld_quality)
        f.addRow("缩放模式/值", rr)
        f.addRow("命名规则", nr)
        return w

    def _on_changed(self, *args):
        # 将控件值同步回 cfg 并通知刷新
        # 文本
        t = self.cfg.text
        t.enabled = self.chk_text_enabled.isChecked()
        t.text = self.edt_text.text()
        t.font_family = self.font_combo.currentText()
        t.font_size_pt = self.spin_fontsize.value()
        t.bold = self.chk_bold.isChecked()
        t.italic = self.chk_italic.isChecked()
        # 透明度来自滑块，更新 RGBA 的 A 分量
        r, g, b, _ = t.color_rgba
        a = int(self.sld_text_opacity.value() * 255 / 100)
        t.color_rgba = (r, g, b, a)
        t.stroke_enabled = self.chk_stroke.isChecked()
        t.stroke_width_px = self.spin_stroke_w.value()
        t.shadow_enabled = self.chk_shadow.isChecked()
        t.shadow_offset_px = self.spin_shadow_off.value()
        t.shadow_alpha = self.spin_shadow_alpha.value()
        # 图片
        i = self.cfg.image
        i.enabled = self.chk_img_enabled.isChecked()
        i.image_path = self.edt_img_path.text()
        i.scale_percent = self.sld_img_scale.value()
        i.opacity = self.sld_img_opacity.value()
        # 布局
        self.cfg.layout.rotation_deg = self.sld_rot.value()
        # 导出
        e = self.cfg.export
        e.output_dir = self.edt_outdir.text()
        e.forbid_source_dir = self.chk_forbid_src.isChecked()
        e.format = 'PNG' if self.rb_png.isChecked() else 'JPEG'
        e.jpeg_quality = self.sld_quality.value()
        e.resize_mode = self.cmb_resize.currentText()
        e.resize_value = self.spin_resize.value()
        if self.rb_keep.isChecked(): e.naming_rule = 'keep'
        elif self.rb_prefix.isChecked(): e.naming_rule = 'prefix'
        else: e.naming_rule = 'suffix'
        e.prefix = self.edt_prefix.text()
        e.suffix = self.edt_suffix.text()

        self.configChanged.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setWindowIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))

        ensure_dirs()
        self.cfg = self._load_last_or_default()

        # 左侧：图片列表（缩略图）
        self.list = QListWidget(); self.list.setIconSize(QSize(96, 96)); self.list.currentRowChanged.connect(self._on_select_change)
        self.list.setSelectionMode(self.list.SingleSelection)
        self.list.setAcceptDrops(True)
        self.list.setDragDropMode(self.list.DropOnly)

        # 中间：预览
        self.preview = PreviewWidget(); self.preview.setConfig(self.cfg)
        self.preview.positionChanged.connect(self._on_pos_changed)

        # 右侧：控制面板
        self.panel = ControlPanel(self.cfg); self.panel.configChanged.connect(self._on_cfg_changed)

        # 布局
        central = QWidget(); self.setCentralWidget(central)
        h = QHBoxLayout(central)
        left = QVBoxLayout(); left.addWidget(QLabel("已导入图片")); left.addWidget(self.list)
        h.addLayout(left, 2)
        h.addWidget(self.preview, 6)
        h.addWidget(self.panel, 3)

        self._build_toolbar()

        # 状态栏
        self.statusBar().showMessage("拖拽图片或点击左上角 ‘导入’ 开始")

        # 数据
        self.images: List[Path] = []

    # 工具栏与菜单
    def _build_toolbar(self):
        tb = QToolBar("主工具栏"); self.addToolBar(tb)
        act_import = QAction("导入图片", self); act_import.triggered.connect(self.import_images)
        act_import_dir = QAction("导入文件夹", self); act_import_dir.triggered.connect(self.import_folder)
        act_clear = QAction("清空列表", self); act_clear.triggered.connect(self.clear_list)
        act_export = QAction("导出", self); act_export.triggered.connect(self.export_all)
        act_save_tpl = QAction("保存模板", self); act_save_tpl.triggered.connect(self.save_template)
        act_load_tpl = QAction("加载模板", self); act_load_tpl.triggered.connect(self.load_template)
        act_manage_tpl = QAction("管理模板", self); act_manage_tpl.triggered.connect(self.manage_templates)

        tb.addAction(act_import)
        tb.addAction(act_import_dir)
        tb.addAction(act_clear)
        tb.addSeparator()
        tb.addAction(act_export)
        tb.addSeparator()
        tb.addAction(act_save_tpl)
        tb.addAction(act_load_tpl)
        tb.addAction(act_manage_tpl)

    # 事件
    def _on_cfg_changed(self):
        self.preview.setConfig(self.cfg)
        self.preview.update()
        self._save_last()

    def _on_pos_changed(self, x: float, y: float):
        self.statusBar().showMessage(f"水印位置：x={x:.3f}, y={y:.3f}")
        self._save_last()

    def _on_select_change(self, row: int):
        img = self._load_qimage_for_preview(row)
        self.preview.setImage(img)

    # 数据加载
    def import_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择图片", str(Path.home()),
                                                "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if not files:
            return
        self._append_files(files)

    def import_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择图片文件夹", str(Path.home()))
        if not d:
            return
        files = []
        for root, _, names in os.walk(d):
            for n in names:
                if Path(n).suffix.lower() in SUPPORTED_INPUT_EXTS:
                    files.append(str(Path(root)/n))
        self._append_files(files)

    def clear_list(self):
        self.images.clear()
        self.list.clear()
        self.preview.setImage(None)
        self.statusBar().showMessage("已清空")

    def _append_files(self, files: List[str]):
        added = 0
        for f in files:
            p = Path(f)
            if not p.exists():
                continue
            if p.suffix.lower() not in SUPPORTED_INPUT_EXTS:
                continue
            if p in self.images:
                continue
            img = QImage(str(p))
            if img.isNull():
                continue
            icon = QPixmap.fromImage(img).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            item = QListWidgetItem(QIcon(icon), p.name)
            item.setToolTip(str(p))
            self.list.addItem(item)
            self.images.append(p)
            added += 1
        if added:
            self.list.setCurrentRow(self.list.count()-1)
            self.statusBar().showMessage(f"导入成功 {added} 张图片")

    def _load_qimage_for_preview(self, row: int) -> Optional[QImage]:
        if row < 0 or row >= len(self.images):
            return None
        p = self.images[row]
        img = QImage(str(p))
        if img.isNull():
            QMessageBox.warning(self, APP_NAME, f"无法读取图片：\n{p}")
            return None
        return img

    # 导出
    def export_all(self):
        if not self.images:
            QMessageBox.information(self, APP_NAME, "请先导入图片。")
            return
        outdir = Path(self.cfg.export.output_dir)
        outdir.mkdir(parents=True, exist_ok=True)
        # 禁止导出到原文件夹
        if self.cfg.export.forbid_source_dir:
            src_dirs = {str(p.parent.resolve()) for p in self.images}
            if str(outdir.resolve()) in src_dirs:
                QMessageBox.warning(self, APP_NAME, "为防止覆盖原图，已禁止导出到源图片所在目录。\n请在‘导出设置’中更换输出目录或取消该限制。")
                return

        prog = QProgressDialog("正在导出…", "取消", 0, len(self.images), self)
        prog.setWindowModality(Qt.ApplicationModal)
        prog.show()

        success, fail = 0, 0
        for i, p in enumerate(self.images, 1):
            prog.setValue(i-1)
            prog.setLabelText(f"处理：{p.name}")
            QApplication.processEvents()
            if prog.wasCanceled():
                break
            try:
                ok = self._export_single(p, outdir)
                success += 1 if ok else 0
                fail += 0 if ok else 1
            except Exception as ex:
                fail += 1
                print("Export error:", ex)
        prog.setValue(len(self.images))
        QMessageBox.information(self, APP_NAME, f"导出完成：成功 {success}，失败 {fail}")

    def _export_single(self, path: Path, outdir: Path) -> bool:
        img = QImage(str(path))
        if img.isNull():
            return False
        # 先缩放（若需要）
        img = self._apply_resize(img)
        # 合成水印
        composed = self._composite_watermark(img)
        # 生成文件名
        out_name = self._build_output_name(path.stem, path.suffix.lower())
        out_path = outdir / out_name
        # 写出
        fmt = self.cfg.export.format.upper()
        if fmt == 'PNG':
            return composed.save(str(out_path.with_suffix('.png')), 'PNG')
        else:
            # JPEG：可调质量（不支持透明，Qt 会自动以白底合成）
            return composed.save(str(out_path.with_suffix('.jpg')), 'JPEG', quality=self.cfg.export.jpeg_quality)

    def _apply_resize(self, img: QImage) -> QImage:
        e = self.cfg.export
        mode = e.resize_mode
        v = max(1, e.resize_value)
        if mode == 'None':
            return img
        if mode == 'Width':
            return img.scaledToWidth(v, Qt.SmoothTransformation)
        if mode == 'Height':
            return img.scaledToHeight(v, Qt.SmoothTransformation)
        if mode == 'Percent':
            w = max(1, int(img.width() * v / 100.0))
            h = max(1, int(img.height() * v / 100.0))
            return img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return img

    def _composite_watermark(self, base: QImage) -> QImage:
        # 在原图尺寸上渲染水印
        out = QImage(base)  # 复制
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        # 生成水印层（与预览逻辑一致，但尺寸依据原图宽度估计图片水印比例）
        wm_layer, _ = self.preview._render_watermark_layer(base.width(), base.height())
        if wm_layer is not None:
            # 计算中心坐标
            cx = self.cfg.layout.pos_x * base.width()
            cy = self.cfg.layout.pos_y * base.height()
            p.translate(cx, cy)
            p.rotate(self.cfg.layout.rotation_deg)
            p.translate(-wm_layer.width()/2, -wm_layer.height()/2)
            p.drawImage(0, 0, wm_layer)
        p.end()
        return out

    def _build_output_name(self, stem: str, orig_ext: str) -> str:
        e = self.cfg.export
        if e.naming_rule == 'keep':
            name = stem
        elif e.naming_rule == 'prefix':
            name = f"{e.prefix}{stem}"
        else:
            name = f"{stem}{e.suffix}"
        # 扩展名由输出格式决定（_export_single 中覆盖）
        return name

    # 模板
    def save_template(self):
        name, ok = QFileDialog.getSaveFileName(self, "保存模板", str(DEFAULT_TPL_DIR / "my_template.json"), "JSON (*.json)")
        if not ok or not name:
            return
        try:
            Path(name).parent.mkdir(parents=True, exist_ok=True)
            Path(name).write_text(self.cfg.to_json(), encoding='utf-8')
            QMessageBox.information(self, APP_NAME, "模板已保存。")
        except Exception as ex:
            QMessageBox.warning(self, APP_NAME, f"保存失败：{ex}")

    def load_template(self):
        name, _ = QFileDialog.getOpenFileName(self, "加载模板", str(DEFAULT_TPL_DIR), "JSON (*.json)")
        if not name:
            return
        try:
            s = Path(name).read_text(encoding='utf-8')
            self.cfg = WatermarkConfig.from_json(s)
            # 重新绑定到面板与预览
            self.panel.cfg = self.cfg
            self.panel._on_changed()  # 从控件刷新一次
            self.preview.setConfig(self.cfg)
            self.preview.update()
            QMessageBox.information(self, APP_NAME, "模板已加载。")
            self._save_last()
        except Exception as ex:
            QMessageBox.warning(self, APP_NAME, f"加载失败：{ex}")

    def manage_templates(self):
        # 简易管理：列出模板文件并允许删除
        tpl_files = list(DEFAULT_TPL_DIR.glob('*.json'))
        if not tpl_files:
            QMessageBox.information(self, APP_NAME, "当前无可管理的模板。")
            return
        items = "\n".join(f.name for f in tpl_files)
        ret = QMessageBox.question(self, APP_NAME, f"共 {len(tpl_files)} 个模板：\n{items}\n\n是否删除全部模板？", QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            for f in tpl_files:
                try: f.unlink()
                except: pass
            QMessageBox.information(self, APP_NAME, "已删除全部模板。")

    # 最近配置
    def _save_last(self):
        try:
            LAST_CONFIG_FILE.write_text(self.cfg.to_json(), encoding='utf-8')
        except Exception:
            pass

    def _load_last_or_default(self) -> WatermarkConfig:
        try:
            if LAST_CONFIG_FILE.exists():
                return WatermarkConfig.from_json(LAST_CONFIG_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
        # 初始化：选择系统常见可用字体
        fam = QFontDatabase().families()
        default_font = 'Arial' if 'Arial' in fam else fam[0] if fam else 'Sans Serif'
        cfg = WatermarkConfig()
        cfg.text.font_family = default_font
        return cfg

    # 拖拽到列表小部件
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            files = []
            for u in e.mimeData().urls():
                p = Path(u.toLocalFile())
                if p.is_dir():
                    for root, _, names in os.walk(p):
                        for n in names:
                            if Path(n).suffix.lower() in SUPPORTED_INPUT_EXTS:
                                files.append(str(Path(root)/n))
                elif p.suffix.lower() in SUPPORTED_INPUT_EXTS:
                    files.append(str(p))
            if files:
                self._append_files(files)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


def main():
    QApplication.setApplicationName(APP_NAME)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
