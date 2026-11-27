"""The interface's pages."""


def clear_layout(layout) -> None:
    """Empty a layout and delete the widgets it held (a page rebuilds itself when
    the settings change: the language, and with it every label, is replaced)."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())
            item.layout().deleteLater()
