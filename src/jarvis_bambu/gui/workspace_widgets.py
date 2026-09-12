"""Lightweight Nebu desktop primitives; no mesh processing or render loop."""
from PySide6.QtCore import Qt, QRectF, QSize, Signal, QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon, QFont, QImage
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget, QSizePolicy, QGraphicsOpacityEffect

_PATHS = {
 'home':'<path d="m3 10 9-7 9 7v10H3z M9 20v-7h6v7"/>',
 'optimizer':'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="11" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 18h7 M18 16v5"/>',
 'stl_color_map':'<path d="m3 7 9-4 9 4-9 4z M3 12l9 4 9-4 M3 17l9 4 9-4"/>',
 'prices':'<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M8 7h8 M8 12h2 M14 12h2 M8 17h2 M14 17h2"/>',
 'guide':'<path d="M3 4h6l3 2 3-2h6v15h-6l-3 2-3-2H3z M12 6v15"/>',
 'queries':'<path d="M3 4h18v13H9l-6 4z M7 8h10 M7 12h6"/>',
 'settings':'<path d="M4 6h16 M4 12h16 M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
 'upload':'<path d="M12 16V3 M7 8l5-5 5 5 M3 15v6h18v-6"/>',
 'arrow':'<path d="M4 12h16 M14 6l6 6-6 6"/>',
 'menu':'<path d="M4 6h16 M4 12h16 M4 18h16"/>',
}


def line_icon(name, color='#A9BABF'):
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{_PATHS.get(name,_PATHS["home"])}</svg>'
    pix=QPixmap(48,48);pix.fill(Qt.transparent)
    painter=QPainter(pix);QSvgRenderer(svg.encode()).render(painter);painter.end()
    return QIcon(pix)


class ModelCanvas(QWidget):
    """Fit an image to available space without contributing its size to layout."""
    heightPicked=Signal(float)

    def __init__(self, title='Tu modelo, a la vista', subtitle='Carga un STL o 3MF para empezar.', parent=None):
        super().__init__(parent)
        self.title=title;self.subtitle=subtitle;self.raster=None;self._pix=QPixmap()
        self._smooth=False;self.badge='';self._rect=QRectF();self._crop_key=None;self._crop_image=None
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.setMinimumSize(80,100)
        self.setAccessibleName('Vista del modelo');self.setCursor(Qt.CrossCursor)

    def sizeHint(self):return QSize(400,320)
    def minimumSizeHint(self):return QSize(80,100)

    def set_image(self, image, raster=None, *, smooth=False, crop=False):
        # Crop embedded thumbnail padding only. Diagnostic masks keep the
        # shared export frame untouched. This never modifies source geometry.
        if crop and image.cacheKey()==self._crop_key:
            image=self._crop_image
        elif crop and image.hasAlphaChannel():
            self._crop_key=image.cacheKey()
            from PIL import Image
            rgba=image.convertToFormat(QImage.Format_RGBA8888)
            pil=Image.frombuffer('RGBA',(rgba.width(),rgba.height()),bytes(rgba.constBits()),'raw','RGBA',rgba.bytesPerLine(),1)
            box=pil.getchannel('A').getbbox()
            if box:image=image.copy(box[0],box[1],box[2]-box[0],box[3]-box[1])
            self._crop_image=image
        self._pix=QPixmap.fromImage(image);self.raster=raster;self._smooth=smooth;self.update()

    def clear_image(self):
        self._pix=QPixmap();self.raster=None;self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(),QColor('#142126'))
        p.setPen(QPen(QColor('#26383F'),1))
        for x in range(20,self.width(),24):
            for y in range(20,self.height(),24):p.drawPoint(x,y)
        if not self._pix.isNull():
            area=QRectF(self.rect()).adjusted(28,30,-28,-30)
            size=self._pix.size().scaled(max(1,int(area.width())),max(1,int(area.height())),Qt.KeepAspectRatio)
            self._rect=QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())
            p.setRenderHint(QPainter.SmoothPixmapTransform,self._smooth)
            p.drawPixmap(self._rect,self._pix,QRectF(self._pix.rect()))
        else:
            # Small line drawing is a UI affordance, not a fake product render.
            center=self.rect().center();p.setPen(QPen(QColor('#72E2C0'),2))
            r=QRectF(center.x()-27,center.y()-76,54,54);p.drawRoundedRect(r,12,12)
            p.drawLine(center.x()-12,center.y()-49,center.x()+12,center.y()-49)
            p.drawLine(center.x(),center.y()-61,center.x(),center.y()-37)
            f=QFont(self.font());f.setPixelSize(20);f.setBold(True);p.setFont(f);p.setPen(QColor('#F2F6F4'))
            p.drawText(QRectF(16,center.y()-4,self.width()-32,36),Qt.AlignCenter,self.title)
            f.setPixelSize(13);f.setBold(False);p.setFont(f);p.setPen(QColor('#A9BABF'))
            p.drawText(QRectF(20,center.y()+36,self.width()-40,60),Qt.AlignHCenter|Qt.TextWordWrap,self.subtitle)
        if self.badge:
            f=QFont(self.font());f.setPixelSize(11);p.setFont(f);p.setPen(QColor('#A9BABF'))
            p.drawText(QRectF(16,8,self.width()-32,20),Qt.AlignLeft,self.badge)
        p.end()

    def mousePressEvent(self,event):
        if self.raster is None or not self._rect.contains(event.position()):return
        x=(event.position().x()-self._rect.x())/self._rect.width()
        y=(event.position().y()-self._rect.y())/self._rect.height()
        n=self.raster.depth.shape[0];z=self.raster.depth[min(n-1,int(y*n)),min(n-1,int(x*n))]
        import math
        if math.isfinite(float(z)):self.heightPicked.emit(float(z))


class PageFade:
    """160 ms on explicit tab changes, with no timer running afterwards."""
    def __init__(self,host):
        import os
        self.enabled=os.environ.get('NEBU_REDUCED_MOTION')!='1'
        self.effect=QGraphicsOpacityEffect(host);host.setGraphicsEffect(self.effect)
        self.effect.setOpacity(1)
        self.animation=QPropertyAnimation(self.effect,b'opacity',host)
        self.animation.setDuration(160);self.animation.setEasingCurve(QEasingCurve.OutCubic)

    def start(self):
        if not self.enabled:return
        self.animation.stop();self.animation.setStartValue(.82);self.animation.setEndValue(1);self.animation.start()
