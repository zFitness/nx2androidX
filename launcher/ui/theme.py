"""The look of the launcher: NX2Apple's Dark Glass, applied in Qt.

The tokens are the desktop launcher's own (frontend-qt nspb_qt/style.py, aligned
with its design tokens): a five-step ladder of surfaces from the near-black
ground to the raised glass, cream as the one accent with its own hover/pressed
states and black ink on it, white text in three strengths, hairlines at six
percent — and four corner radii (chip 6, card 12, sheet 16, control 18) that
shape every card, pill and field.

Feedback is immediate: a hover changes the fill a step, never a motion; the
keyboard focus draws a 2px cream line; the window's close control takes the
danger red on hover.  The library's action panel is the heroSecondary glass: a
translucent card over the page, static layering, never a live blur.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QPainter, QPainterPath, QPalette,
                           QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QWidget

# Surface & border tokens.
BG = '#0e0e0f'                 # the window's ground
SURFACE = '#141416'            # dialogs and sunken fields' neighbours
CARD = '#1a1a1c'               # cards and grouped panels
RAISED = '#202023'             # menus, tooltips, the lifted glass
CARD_HOVER = '#222225'
HAIRLINE = 'rgba(255, 255, 255, 0.06)'      # a card's edge, barely there
SEPARATOR = 'rgba(255, 255, 255, 0.10)'     # a row's line

# Text hierarchy.
TEXT = '#f5f5f7'
MUTED = '#a1a1a8'
FAINT = '#787880'

# The accent: cream, with its own three states and its ink.
ACCENT = '#fff0d6'
ACCENT_HOVER = '#fff6e6'
ACCENT_PRESSED = '#e8d7ba'
ACCENT_DISABLED = '#3a3834'
ACCENT_INK = '#000000'

# The semantic states.
READY = '#40d678'
BUILDING = '#ffc73d'           # amber; orange only through it
DANGER = '#ff6b66'
DANGER_FILL = '#d23b36'        # the error fill (4.75:1 with a white label)
DANGER_ON = '#ffffff'
NEUTRAL_DOT = '#787880'

# The four radii (chip / card / sheet / control), the whole shape language.
R_CHIP = 6
R_CARD = 12
R_SHEET = 16
R_CONTROL = 18

# The rich-text tags the build page's card writes with.
TAGS = {'name': TEXT, 'dim': MUTED, 'ok': READY, 'warn': BUILDING, 'bad': DANGER}

# What a porting status is worth on the screen.
STATUS_COLOUR = {'playable': READY, 'wip': BUILDING, 'boots': BUILDING,
                 'experimental': BUILDING, 'not ported': NEUTRAL_DOT}

# The palette's older names, kept for the pages that still speak them.
GROUND = BG
PANEL = CARD
CREAM = ACCENT
INK = TEXT
DIM = MUTED
LINE = SEPARATOR
UNBUILT = NEUTRAL_DOT
SELECTED_FILL = 'rgba(255, 240, 214, 0.10)'   # the chosen card: cream at ten
FOCUS_LINE = ACCENT                            # the keyboard focus: 2px of cream


def build_qss() -> str:
    """The whole stylesheet in one string, from the tokens above."""
    return f'''
    /* The surfaces: the ground everywhere, panels a step above it. */
    QMainWindow {{ background: {BG}; }}
    QDialog {{ background: {SURFACE}; }}
    QFrame#titlebar {{ background-color: {BG}; border-bottom: 1px solid {HAIRLINE}; }}
    /* Opaque ground on the stack and every page: a transparent page on a
       compositor without a window background flashes one frame of desktop
       while a flip is in flight — exactly the KWin flicker on this tablet. */
    QStackedWidget {{ background-color: {BG}; }}
    QWidget#page {{ background-color: {BG}; }}

    /* Words. */
    QLabel {{ color: {TEXT}; background: transparent; }}
    QLabel[dim="true"] {{ color: {MUTED}; }}
    QLabel[status="busy"] {{ color: {BUILDING}; }}
    QLabel[status="done"], QLabel[status="ready"] {{ color: {READY}; }}
    QLabel[status="bad"] {{ color: {DANGER}; }}
    QLabel#pageTitle {{ font-size: 25px; font-weight: 800; color: {TEXT}; }}
    QLabel#pageNote {{ font-size: 13.5px; color: {MUTED}; }}
    QLabel#sectionTitle {{ font-size: 14px; font-weight: 600; color: {MUTED}; }}
    QLabel#sectionFoot {{ font-size: 11.5px; color: {FAINT}; }}
    QLabel#rowTitle {{ font-size: 13px; font-weight: 600; color: {TEXT}; }}

    /* The desktop launcher's card: rounded dark, hairline edge. */
    QFrame#nxcard {{
        background: {CARD}; border: 1px solid {HAIRLINE}; border-radius: {R_CARD}px;
    }}

    /* The library's grid items: air until the hand comes near; the chosen one
       carries a cream line (the selection never changes the card's size). */
    QFrame#gamecard {{
        background: transparent; border: 1px solid transparent; border-radius: {R_CARD}px;
    }}
    QFrame#gamecard:hover {{ background: rgba(255, 255, 255, 0.05); }}
    QFrame#gamecard[selected="true"] {{
        background: {SELECTED_FILL}; border-color: {ACCENT};
    }}
    QFrame#gamecard:focus {{ border-color: {ACCENT}; }}
    QFrame#infocard {{ background: {SURFACE}; border: 1px solid {HAIRLINE};
                       border-radius: {R_CARD}px; }}

    /* Boxed panels: the card surface with a hairline. */
    QGroupBox {{
        background: {CARD}; border: 1px solid {HAIRLINE}; border-radius: {R_CARD}px;
        margin-top: 14px; padding: 10px; font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; left: 14px; padding: 0 4px; color: {MUTED};
    }}

    /* Fields: glass fills, a 2px cream focus. */
    QLineEdit, QPlainTextEdit, QTreeWidget {{
        background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.11);
        border-radius: {R_CARD}px; color: {TEXT}; padding: 5px 10px;
        selection-background-color: {ACCENT}; selection-color: {ACCENT_INK};
    }}
    QLineEdit:hover {{
        background: rgba(255, 255, 255, 0.09); border-color: rgba(255, 255, 255, 0.18);
    }}
    QLineEdit:focus {{ border: 2px solid {ACCENT}; background: rgba(255, 255, 255, 0.10); }}
    QPlainTextEdit:focus {{ border: 1px solid rgba(255, 240, 214, 0.45); }}
    QTreeWidget:focus {{ border: 1px solid rgba(255, 240, 214, 0.45); }}
    QLineEdit:disabled {{ color: {FAINT}; }}
    QTreeWidget::item {{ padding: 3px; border-radius: {R_CHIP}px; }}
    QTreeWidget::item:selected {{ background: {ACCENT}; color: {ACCENT_INK}; }}
    QHeaderView::section {{
        background: transparent; color: {MUTED};
        border: none; border-bottom: 1px solid {SEPARATOR}; padding: 4px 8px;
    }}

    /* The dropdown, the same glass as the fields. */
    QComboBox {{
        background: rgba(255, 255, 255, 0.06); color: {TEXT};
        border: 1px solid rgba(255, 255, 255, 0.12); border-radius: {R_CARD}px;
        padding: 5px 28px 5px 12px; min-width: 120px;
    }}
    QComboBox:hover {{ background: rgba(255, 255, 255, 0.10);
                       border-color: rgba(255, 255, 255, 0.20); }}
    QComboBox:focus {{ border: 2px solid {ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent;
                             border-right: 4px solid transparent;
                             border-top: 5px solid {MUTED}; width: 0; height: 0; }}
    QComboBox QAbstractItemView {{
        background: {RAISED}; color: {TEXT};
        border: 1px solid rgba(255, 255, 255, 0.14); border-radius: {R_CARD}px;
        selection-background-color: {ACCENT}; selection-color: {ACCENT_INK}; padding: 4px;
    }}

    /* Checks: 16px rounded squares, cream when they say yes. */
    QCheckBox {{ color: {TEXT}; spacing: 8px; }}
    QCheckBox:disabled {{ color: {FAINT}; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 4px;
        background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.24);
    }}
    QCheckBox::indicator:hover {{
        border-color: rgba(255, 240, 214, 0.65); background: rgba(255, 255, 255, 0.10);
    }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
    QCheckBox::focus {{ color: {ACCENT}; }}

    /* Spin boxes and the scrollbar's twin, the same glass. */
    QDoubleSpinBox {{
        background: rgba(255, 255, 255, 0.06); color: {TEXT};
        border: 1px solid rgba(255, 255, 255, 0.11); border-radius: {R_CARD}px;
        padding: 4px 8px;
    }}
    QDoubleSpinBox:focus {{ border: 2px solid {ACCENT}; }}

    /* Progress: 6px of track, a cream fill. */
    QProgressBar {{
        background: rgba(255, 255, 255, 0.10); border: none; border-radius: 3px;
        max-height: 6px; min-height: 6px; text-align: center;
    }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

    /* Scrolling: thin handles on transparent rails. */
    QScrollArea {{ background-color: {BG}; border: none; }}
    QScrollArea > QWidget > QWidget {{ background-color: {BG}; }}
    QAbstractScrollArea {{ background-color: {BG}; }}
    QAbstractScrollArea > QWidget > QWidget {{ background-color: {BG}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px 4px 0; }}
    QScrollBar::handle:vertical {{ background: rgba(255, 255, 255, 0.18);
                                   border-radius: 3px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: rgba(255, 255, 255, 0.30); }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0 4px 2px 4px; }}
    QScrollBar::handle:horizontal {{ background: rgba(255, 255, 255, 0.18);
                                     border-radius: 3px; min-width: 28px; }}
    QScrollBar::handle:horizontal:hover {{ background: rgba(255, 255, 255, 0.30); }}
    QScrollBar::sub-line, QScrollBar::add-line {{ width: 0; height: 0; }}
    QScrollBar::sub-page, QScrollBar::add-page {{ background: none; }}

    QSplitter::handle:vertical {{ background: transparent; height: 6px; }}

    QToolTip {{
        background: {RAISED}; color: {TEXT};
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: {R_CHIP}px; padding: 5px 9px;
    }}
    QMenu {{ background: {RAISED}; color: {TEXT};
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: {R_CARD}px; padding: 6px; }}
    QMenu::item {{ padding: 7px 16px; border-radius: {R_CHIP}px; }}
    QMenu::item:selected {{ background: rgba(255, 255, 255, 0.11); color: #ffffff; }}
    QMenu::separator {{ height: 1px; background: {SEPARATOR}; margin: 5px 10px; }}
    '''


def apply(app: QApplication) -> None:
    """Fusion under everything, the Dark Glass palette for the widgets without a
    rule (native dialogs never flash light chrome), and the stylesheet."""
    app.setStyle('Fusion')
    palette = QPalette()
    roles = (
        (QPalette.Window, BG), (QPalette.WindowText, TEXT),
        (QPalette.Base, SURFACE), (QPalette.AlternateBase, CARD),
        (QPalette.Text, TEXT), (QPalette.Button, CARD),
        (QPalette.ButtonText, TEXT), (QPalette.ToolTipBase, RAISED),
        (QPalette.ToolTipText, TEXT), (QPalette.Highlight, QColor(ACCENT)),
        (QPalette.HighlightedText, QColor(ACCENT_INK)),
        (QPalette.PlaceholderText, QColor(MUTED)),
        (QPalette.Link, ACCENT), (QPalette.LinkVisited, ACCENT),
        (QPalette.BrightText, QColor(DANGER)),
    )
    for role, colour in roles:
        palette.setColor(role, QColor(colour) if isinstance(colour, str) else colour)
    disabled = ((QPalette.Text, QColor(FAINT)), (QPalette.ButtonText, QColor(FAINT)),
                (QPalette.WindowText, QColor(FAINT)))
    for role, colour in disabled:
        palette.setColor(QPalette.Disabled, role, colour)
    app.setPalette(palette)
    app.setStyleSheet(build_qss())


def styled_background(widget: QWidget) -> QWidget:
    """Let a plain QWidget or QFrame paint the stylesheet's background for it."""
    widget.setAttribute(Qt.WA_StyledBackground, True)
    return widget


def repolish(widget: QWidget) -> None:
    """Re-read the stylesheet after a property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def headline(scale: float, factor: float = 1.0) -> QFont:
    """A page headline: the token stylesheet's pageTitle — 25px, weight 800."""
    font = QFont()
    font.setWeight(QFont.Black)
    font.setPixelSize(max(24, round(25 * factor * max(1.0, scale))))
    return font


def subhead(scale: float) -> QFont:
    """The note under a headline: the token stylesheet's pageNote."""
    font = QFont()
    font.setPixelSize(max(12, round(13.5 * max(1.0, scale))))
    return font


# The brand's mark, the one docs/images/icon.svg carries: the blue tile, the two
# rounded strokes of its "2".  It is drawn, not loaded, so the launcher ships no
# QtSvg dependency and never misses a file.
def brand_pixmap(size: float, dpr: float = 1.0) -> QPixmap:
    """The brand's mark at `size` logical pixels."""
    pixels = max(1, round(size * dpr))
    pixmap = QPixmap(pixels, pixels)
    pixmap.setDevicePixelRatio(dpr if dpr > 0 else 1.0)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    scale = size / 100.0

    def rect(x: float, y: float, w: float, h: float) -> QRectF:
        return QRectF(x * scale, y * scale, w * scale, h * scale)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#2E2BD9'))
    painter.drawRoundedRect(rect(0, 0, 100, 100), 23 * scale, 23 * scale)
    painter.setBrush(QColor('#8A88FF'))
    painter.drawRect(rect(50, 32, 18, 36))
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor('#FFFFFF'), 6 * scale, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
    painter.drawRoundedRect(rect(12, 32, 56, 36), 10 * scale, 10 * scale)
    painter.setPen(QPen(QColor('#FF8A00'), 6 * scale, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
    painter.drawRoundedRect(rect(50, 14, 32, 72), 10 * scale, 10 * scale)
    painter.end()
    return pixmap


def brand_icon(size: int = 64) -> QIcon:
    return QIcon(brand_pixmap(size, 1.0))


def rounded(pixmap: QPixmap, radius: float) -> QPixmap:
    """A copy of the pixmap with its corners rounded off (the covers' shape)."""
    if pixmap.isNull():
        return pixmap
    dpr = pixmap.devicePixelRatio() or 1.0
    out = QPixmap(pixmap.size())
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    size = pixmap.size()
    path.addRoundedRect(QRectF(0, 0, size.width() / dpr, size.height() / dpr),
                        radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return out


def cover_placeholder(size: QSize, dpr: float, letter: str, radius: float) -> QPixmap:
    """A cover for a game whose icon could not be read: the card shade, the
    game's first letter — the same rounded shape as a real cover."""
    pixels = QSize(max(1, round(size.width() * dpr)), max(1, round(size.height() * dpr)))
    pixmap = QPixmap(pixels)
    pixmap.setDevicePixelRatio(dpr if dpr > 0 else 1.0)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius, radius)
    painter.setClipPath(path)
    painter.fillRect(QRectF(0, 0, size.width(), size.height()), QColor(CARD))
    font = painter.font()
    font.setPointSizeF(max(12.0, size.height() / 3.2))
    font.setWeight(QFont.Bold)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 140))   # direct RGBA: QColor() refuses the CSS spelling
    painter.drawText(QRectF(0, 0, size.width(), size.height()), Qt.AlignCenter, letter)
    painter.end()
    return pixmap

