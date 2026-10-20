from __future__ import annotations

import html
import unittest

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from project_map.mixins.formatting import FormattingMixin
from qt_test_support import APP


def reference_icon(symbol):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
    <rect x="1" y="1" width="22" height="22" rx="6" fill="none" stroke="#64748b" stroke-width="1.2"/>
    <text x="12" y="16.5" text-anchor="middle" font-family="Segoe UI, Microsoft YaHei UI" font-size="12" font-weight="700" fill="#64748b">{html.escape(symbol)}</text>
    </svg>'''
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(48, 48)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, 24, 24))
    painter.end()
    return QIcon(pixmap)


class IconRenderingTests(unittest.TestCase):
    def test_text_symbols_are_distinct_not_missing_glyph_boxes(self):
        images = [FormattingMixin.vector_icon(None, symbol).pixmap(QSize(24, 24), 2).toImage() for symbol in ("B", "I", "H1", "H6", "V+", "V−")]
        for index, image in enumerate(images):
            for other in images[index + 1:]:
                self.assertNotEqual(image, other)

    def test_glyph_and_frame_not_cropped_at_display_scales(self):
        for symbol in ("↶", "↷", "B", "I", "S", "U", "H1", "H6", "☷", "☑", ">", "</>", "↗", "—", "V+", "v.x", "V−", "○"):
            icon = FormattingMixin.vector_icon(None, symbol)
            expected = reference_icon(symbol)
            for size in (16, 22, 24, 32):
                for ratio in (1.0, 1.25, 1.5, 2.0):
                    with self.subTest(symbol=symbol, size=size, scale=ratio):
                        actual_image = icon.pixmap(QSize(size, size), ratio).toImage()
                        expected_image = expected.pixmap(QSize(size, size), ratio).toImage()
                        self.assertEqual(actual_image, expected_image)


if __name__ == "__main__":
    unittest.main()
