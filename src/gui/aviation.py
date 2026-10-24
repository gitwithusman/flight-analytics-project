"""Aviation-themed scenery: animated sky, clouds, airliners with contrails and an airport skyline.

Everything is drawn with QPainter (resolution independent, no external files needed).
If you want photographs instead, drop ``<scene>.jpg`` / ``.png`` into ``assets/backgrounds/``
(scene names: noon, dawn, dusk, night, storm, day) and they are used as the base layer
for the hero banners, with the animated airplanes drawn on top.

Motion can be switched off in Settings (``REDUCE_MOTION=1``); the scene is then drawn once.
"""

from __future__ import annotations

import math
import random
from typing import Dict, Optional

from PySide6.QtCore import QElapsedTimer, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPixmap, QRadialGradient, QRegion,
)
from PySide6.QtWidgets import QWidget

from src import config

from .perf import render_queue

# --------------------------------------------------------------------------- scene palettes
# (sky stops top->bottom, cloud colour, star alpha, sun/moon, ground, window light)
SCENES: Dict[str, dict] = {
    "day":   dict(sky=["#9CC7F2", "#C9E0F7", "#EEF5FC"], cloud="#FFFFFF", cloud_a=190, stars=0, orb=None,
                  ground="#8FA6C2", building="#7B94B5", light="#FFFFFF", plane="#1F4E8C", plane_a=70),
    "noon":  dict(sky=["#1F5FBF", "#4F9BE8", "#BFE0F7"], cloud="#FFFFFF", cloud_a=210, stars=0,
                  orb=("#FFF6C8", 0.82, 0.30), ground="#2C4A75", building="#27456E", light="#CFE8FF",
                  plane="#FFFFFF", plane_a=235),
    "dawn":  dict(sky=["#1B2B5E", "#6A4C93", "#F2A07B", "#FFD9A0"], cloud="#FFE3C8", cloud_a=170, stars=60,
                  orb=("#FFE6A8", 0.18, 0.80), ground="#2A2147", building="#241C40", light="#FFD27A",
                  plane="#FFFFFF", plane_a=230),
    "dusk":  dict(sky=["#0B2545", "#1F4E8C", "#E58E5B", "#F7C873"], cloud="#FFC9A0", cloud_a=150, stars=90,
                  orb=("#FFD58A", 0.78, 0.78), ground="#101F3A", building="#0C1930", light="#FFC857",
                  plane="#FFFFFF", plane_a=230),
    "night": dict(sky=["#040B1E", "#0B2545", "#173F78"], cloud="#5C7BB0", cloud_a=70, stars=170,
                  orb=("#EAF1FF", 0.84, 0.24), ground="#050C1D", building="#071230", light="#FFD27A",
                  plane="#E8F0FF", plane_a=225),
    "storm": dict(sky=["#232C42", "#4A5875", "#8793AA"], cloud="#B8C2D4", cloud_a=190, stars=0, orb=None,
                  ground="#1A2238", building="#161D32", light="#FFE9A8", plane="#EAF1FF", plane_a=220),
}


def _c(hex_color: str, alpha: int = 255) -> QColor:
    col = QColor(hex_color)
    col.setAlpha(alpha)
    return col


def _plane_path() -> QPainterPath:
    """Top-down airliner pointing to +x, about 100 units long."""
    p = QPainterPath()
    p.addRoundedRect(QRectF(-50, -4.2, 100, 8.4), 4.2, 4.2)           # fuselage
    p.moveTo(52, 0)
    p.quadTo(60, 0, 52, 3.6)
    p.quadTo(60, 0, 52, -3.6)
    for s in (1, -1):                                                    # swept wings
        w = QPainterPath()
        w.moveTo(8, s * 3)
        w.lineTo(-14, s * 46)
        w.lineTo(-26, s * 46)
        w.lineTo(-12, s * 3)
        w.closeSubpath()
        p.addPath(w)
        t = QPainterPath()                                               # tailplane
        t.moveTo(-38, s * 3)
        t.lineTo(-50, s * 17)
        t.lineTo(-57, s * 17)
        t.lineTo(-47, s * 3)
        t.closeSubpath()
        p.addPath(t)
        p.addEllipse(QPointF(-7, s * 20), 4.2, 2.4)                      # engines
    return p


_PLANE = _plane_path()


class SkyBackground(QWidget):
    """Animated sky: gradient, drifting clouds, airliners with contrails, optional airport skyline."""

    def __init__(self, scene: str = "day", planes: int = 3, airport: bool = False, clouds: int = 9,
                 seed: int = 7, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._scene_name = scene if scene in SCENES else "day"
        self._airport = airport
        self._rng = random.Random(seed)
        self._clouds = [dict(x=self._rng.random(), y=self._rng.uniform(0.06, 0.5), s=self._rng.uniform(0.5, 1.2),
                             sp=self._rng.uniform(5, 16), a=self._rng.uniform(0.5, 0.95)) for _ in range(clouds)]
        self._planes = [dict(x=self._rng.random(), y=self._rng.uniform(0.12, 0.55), sp=self._rng.uniform(34, 70),
                             s=self._rng.uniform(0.32, 0.62), bob=self._rng.uniform(0, 6.28),
                             trail=self._rng.uniform(150, 260)) for _ in range(planes)]
        self._stars = [(self._rng.random(), self._rng.random() * 0.6, self._rng.uniform(0.6, 1.8),
                        self._rng.uniform(0, 6.28)) for _ in range(SCENES[self._scene_name]["stars"])]
        self._static: Optional[QPixmap] = None
        self._photo: Optional[QPixmap] = None
        self._photo_checked = False
        self._clock = QElapsedTimer()
        self._clock.start()
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)                    # 20 fps: clouds and planes move slowly, this is smooth enough
        self._timer.timeout.connect(self._tick)
        self._animated = not config.REDUCE_MOTION
        self._static_size = None
        # The big content-area sky sits behind every chart and table. Repainting all of it every frame would repaint
        # all of them too, so it invalidates only the small rectangles where something actually moved.
        self._partial = not airport
        self._skipped = 0
        self._last_region = QRegion()

    # ---- public API ---------------------------------------------------------
    def set_animated(self, on: bool) -> None:
        self._animated = bool(on)
        self._sync_timer()
        self.update()

    def set_scene(self, scene: str) -> None:
        self._scene_name = scene if scene in SCENES else "day"
        self._static = None
        self._photo_checked = False
        self.update()

    def scene(self) -> dict:
        return SCENES[self._scene_name]

    # ---- timer handling -------------------------------------------------------
    def _sync_timer(self) -> None:
        want = self._animated and self.isVisible() and not config.REDUCE_MOTION
        if want and not self._timer.isActive():
            self._clock.restart()
            self._timer.start()
        elif not want and self._timer.isActive():
            self._timer.stop()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self._sync_timer()

    def _tick(self) -> None:
        dt = self._clock.restart() / 1000.0
        if render_queue.busy and self._skipped < 10:   # give the CPU to the chart being drawn (at most ~0.5 s)
            self._skipped += 1
            return
        self._skipped = 0
        self._t += dt
        if not self._partial:
            self.update()
            return
        region = self._moving_region(self._t)
        self.update(region.united(self._last_region))
        self._last_region = region

    def _moving_region(self, t: float) -> QRegion:
        """Rectangles covering every cloud and airliner (with contrail) at time ``t``."""
        w, h = self.width(), self.height()
        region = QRegion()
        horizon = h * (0.78 if self._airport else 1.0)
        for c in self._clouds:
            span = w + 360
            x = ((c["x"] * span + t * c["sp"]) % span) - 180
            sc = c["s"] * max(0.4, min(1.3, w / 1000.0, h / 300.0))
            y = c["y"] * horizon
            region += QRect(int(x - 108 * sc), int(y - 38 * sc), int(216 * sc) + 2, int(76 * sc) + 2)
        horizon = h * (0.70 if self._airport else 0.95)
        for pl in self._planes:
            span = w + 520
            x = ((pl["x"] * span + t * pl["sp"]) % span) - 260
            y = pl["y"] * horizon + math.sin(t * 0.6 + pl["bob"]) * 4
            size = pl["s"] * max(0.5, min(1.25, w / 1100.0, h / 190.0 + 0.2))
            tail = pl["trail"] * size * 1.6
            region += QRect(int(x - tail - 12), int(y - 52 * size - 14), int(tail + 80 * size + 24), int(104 * size + 28))
        return region

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._static = None

    # ---- static layer (sky, stars base, photo, ground) ---------------------------
    def _load_photo(self) -> Optional[QPixmap]:
        if self._photo_checked:
            return self._photo
        self._photo_checked = True
        self._photo = None
        for ext in ("jpg", "jpeg", "png"):
            path = config.ASSETS_DIR / "backgrounds" / f"{self._scene_name}.{ext}"
            if path.exists():
                pm = QPixmap(str(path))
                if not pm.isNull():
                    self._photo = pm
                    break
        return self._photo

    def _build_static(self) -> QPixmap:
        w, h = max(self.width(), 1), max(self.height(), 1)
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        sc = self.scene()
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        photo = self._load_photo()
        if photo is not None:
            scaled = photo.scaled(int(w * dpr), int(h * dpr), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            p.drawPixmap(0, 0, scaled, int((scaled.width() - w * dpr) / 2), int((scaled.height() - h * dpr) / 2),
                         int(w * dpr), int(h * dpr))
            veil = QLinearGradient(0, 0, 0, h)
            veil.setColorAt(0, _c("#0B2545", 120))
            veil.setColorAt(1, _c("#0B2545", 30))
            p.fillRect(QRectF(0, 0, w, h), veil)
        else:
            g = QLinearGradient(0, 0, 0, h)
            stops = sc["sky"]
            for i, col in enumerate(stops):
                g.setColorAt(i / (len(stops) - 1), QColor(col))
            p.fillRect(QRectF(0, 0, w, h), g)
            if sc["orb"]:
                colr, fx, fy = sc["orb"]
                cx, cy, r = w * fx, h * fy, min(w, h) * 0.42
                rg = QRadialGradient(cx, cy, r)
                rg.setColorAt(0, _c(colr, 235))
                rg.setColorAt(0.18, _c(colr, 150))
                rg.setColorAt(1, _c(colr, 0))
                p.fillRect(QRectF(0, 0, w, h), rg)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_c(colr, 255))
                p.drawEllipse(QPointF(cx, cy), min(w, h) * 0.035, min(w, h) * 0.035)
        if self._airport and h > 110:
            self._paint_airport_static(p, w, h, sc)
        p.end()
        self._static_size = (w, h)
        return pm

    def _paint_airport_static(self, p: QPainter, w: float, h: float, sc: dict) -> None:
        base = h - max(26.0, h * 0.10)
        scale = max(0.6, min(1.5, h / 220.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(sc["building"]))
        rng = random.Random(3)
        x = -10.0
        while x < w:                                       # terminal blocks
            bw = rng.uniform(46, 110) * scale
            bh = rng.uniform(14, 34) * scale
            p.drawRoundedRect(QRectF(x, base - bh, bw, bh), 2, 2)
            p.setBrush(_c(sc["light"], 150))               # lit windows
            wx = x + 6
            while wx < x + bw - 8:
                p.drawRect(QRectF(wx, base - bh + 5 * scale, 4 * scale, 2.6 * scale))
                wx += 9 * scale
            p.setBrush(_c(sc["building"]))
            x += bw + rng.uniform(8, 36) * scale
        tx = w * 0.72                                      # control tower
        p.drawRect(QRectF(tx - 4 * scale, base - 62 * scale, 8 * scale, 62 * scale))
        cab = QPainterPath()
        cab.moveTo(tx - 15 * scale, base - 62 * scale)
        cab.lineTo(tx + 15 * scale, base - 62 * scale)
        cab.lineTo(tx + 11 * scale, base - 78 * scale)
        cab.lineTo(tx - 11 * scale, base - 78 * scale)
        cab.closeSubpath()
        p.drawPath(cab)
        p.setBrush(_c(sc["light"], 200))
        p.drawRect(QRectF(tx - 10 * scale, base - 74 * scale, 20 * scale, 5 * scale))
        p.setBrush(_c(sc["building"]))
        p.drawRect(QRectF(tx - 1, base - 92 * scale, 2, 14 * scale))
        p.setBrush(_c(sc["ground"]))                       # apron + runway
        p.drawRect(QRectF(0, base, w, h - base))
        p.setBrush(_c("#FFFFFF", 70))
        for i in range(int(w / (34 * scale)) + 1):         # runway centre dashes
            p.drawRect(QRectF(i * 34 * scale + 6, base + (h - base) * 0.46, 18 * scale, 2))
        self._base_y, self._scale = base, scale

    # ---- painting -----------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        w, h = self.width(), self.height()
        if w < 4 or h < 4:
            return
        if self._static is None or self._static_size != (w, h):
            self._static = self._build_static()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self._static)
        sc = self.scene()
        t = self._t if self._animated and not config.REDUCE_MOTION else 0.0
        if sc["stars"]:
            p.setPen(Qt.PenStyle.NoPen)
            for sx, sy, sr, ph in self._stars:
                a = int(120 + 110 * (0.5 + 0.5 * math.sin(t * 1.4 + ph)))
                p.setBrush(_c("#FFFFFF", a))
                p.drawEllipse(QPointF(sx * w, sy * h), sr * 0.6, sr * 0.6)
        self._paint_clouds(p, w, h, t, sc)
        self._paint_planes(p, w, h, t, sc)
        if self._airport and h > 110:
            self._paint_airport_dynamic(p, w, h, t, sc)
        p.end()

    def _paint_clouds(self, p: QPainter, w: float, h: float, t: float, sc: dict) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        horizon = h * (0.78 if self._airport else 1.0)
        for c in self._clouds:
            span = w + 360
            x = ((c["x"] * span + t * c["sp"]) % span) - 180
            y = c["y"] * horizon
            s = c["s"] * max(0.4, min(1.3, w / 1000.0, h / 300.0))
            alpha = int(sc["cloud_a"] * c["a"])
            col = _c(sc["cloud"], alpha)
            p.setBrush(col)
            for dx, dy, rx, ry in ((0, 0, 70, 20), (-48, 6, 46, 15), (46, 7, 52, 16), (-14, -12, 40, 17), (24, -9, 34, 14)):
                p.drawEllipse(QPointF(x + dx * s, y + dy * s), rx * s, ry * s)

    def _paint_planes(self, p: QPainter, w: float, h: float, t: float, sc: dict) -> None:
        horizon = h * (0.70 if self._airport else 0.95)
        for pl in self._planes:
            span = w + 520
            x = ((pl["x"] * span + t * pl["sp"]) % span) - 260
            y = pl["y"] * horizon + math.sin(t * 0.6 + pl["bob"]) * 4
            size = pl["s"] * max(0.5, min(1.25, w / 1100.0, h / 190.0 + 0.2))
            ang = -5.0 + math.sin(t * 0.5 + pl["bob"]) * 1.5
            # contrail (drawn in the plane's rotated frame so the gradient follows it)
            tail = pl["trail"] * size * 1.6
            p.save()
            p.translate(x, y)
            p.rotate(ang)
            g = QLinearGradient(-tail, 0, -44 * size, 0)
            g.setColorAt(0, _c("#FFFFFF", 0))
            g.setColorAt(1, _c("#FFFFFF", 150 if self._scene_name != "day" else 170))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawRoundedRect(QRectF(-tail, -1.6 * size - 0.6, tail - 44 * size, 3.2 * size + 1.2), 2, 2)
            p.restore()
            p.save()
            p.translate(x, y)
            p.rotate(ang)
            p.scale(size, size)
            p.setBrush(_c(sc["plane"], sc["plane_a"]))
            p.drawPath(_PLANE)
            p.restore()

    def _paint_airport_dynamic(self, p: QPainter, w: float, h: float, t: float, sc: dict) -> None:
        base, scale = getattr(self, "_base_y", h * 0.9), getattr(self, "_scale", 1.0)
        p.setPen(Qt.PenStyle.NoPen)
        n = int(w / (26 * scale)) + 1                      # runway edge lights chasing along the runway
        for i in range(n):
            a = int(60 + 190 * max(0.0, math.sin(t * 5 - i * 0.55)))
            p.setBrush(_c("#FFE8A6", a))
            p.drawEllipse(QPointF(i * 26 * scale + 10, base + (h - base) * 0.12), 1.8, 1.8)
            p.drawEllipse(QPointF(i * 26 * scale + 10, base + (h - base) * 0.86), 1.8, 1.8)
        tx = w * 0.72                                      # tower beacon
        beacon = 0.5 + 0.5 * math.sin(t * 3.2)
        rg = QRadialGradient(QPointF(tx, base - 92 * scale), 16 * scale)
        rg.setColorAt(0, _c("#FF5A4F", int(60 + 190 * beacon)))
        rg.setColorAt(1, _c("#FF5A4F", 0))
        p.setBrush(QBrush(rg))
        p.drawEllipse(QPointF(tx, base - 92 * scale), 16 * scale, 16 * scale)
        span = w + 300                                     # taxiing airliner
        x = ((t * 22) % span) - 150
        p.save()
        p.translate(x, base + (h - base) * 0.46)
        p.scale(0.22 * scale, 0.22 * scale)
        p.setBrush(_c("#FFFFFF", 235))
        p.drawPath(_PLANE)
        p.restore()
