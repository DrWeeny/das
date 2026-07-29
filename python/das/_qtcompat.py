"""
das._qtcompat  -  Qt binding shim
=================================
Import everything Qt-related from here.  Binding preference order:

    Qt.py  ->  PySide6  ->  PySide2

Qt.py is tried first (it already normalises PySide2/PySide6/PyQt for us, so we
don't want to duplicate that work); when it isn't installed we fall back to
PySide6, then PySide2.  This module is imported lazily by the UI modules, so
`import das` never pulls in a Qt binding.

Shared by BOTH renderers -- das.qtform (the form) and das.qtui (the tree) --
so there is exactly one binding ladder in the codebase.  It used to live at
das.qtform._qtcompat, which still re-exports it for existing imports.
"""

_BINDING = None

# The Qt.py module itself when that is what we went through, else None.  Only
# code that must ask Qt.py something *about itself* needs this (see qtui's
# IsPySide2); everything else should use the re-exports below.
qt_py = None
QtCompat = None

try:
    # Qt.py (preferred): a single API over PySide2/PySide6/PyQt5
    import Qt as qt_py
    from Qt import QtWidgets, QtCore, QtGui, QtCompat
    from Qt.QtCore import Signal, Slot
    _BINDING = "Qt.py"
    QAction = QtWidgets.QAction

    def app_exec(app):
        return app.exec_()

    def dialog_exec(dialog):
        return dialog.exec_()

except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        from PySide6.QtCore import Signal, Slot
        _BINDING = "PySide6"
        QAction = QtGui.QAction          # PySide6: QAction moved to QtGui

        def app_exec(app):
            return app.exec()            # PySide6 dropped exec_()

        def dialog_exec(dialog):
            return dialog.exec()

    except ImportError:
        from PySide2 import QtWidgets, QtCore, QtGui
        from PySide2.QtCore import Signal, Slot
        _BINDING = "PySide2"
        QAction = QtWidgets.QAction

        def app_exec(app):
            return app.exec_()

        def dialog_exec(dialog):
            return dialog.exec_()


# ── convenience re-exports ───────────────────────────────────────────────────
QApplication    = QtWidgets.QApplication
QWidget         = QtWidgets.QWidget
QDialog         = QtWidgets.QDialog
QMainWindow     = QtWidgets.QMainWindow
QVBoxLayout     = QtWidgets.QVBoxLayout
QHBoxLayout     = QtWidgets.QHBoxLayout
QFormLayout     = QtWidgets.QFormLayout
QGridLayout     = QtWidgets.QGridLayout
QLabel          = QtWidgets.QLabel
QLineEdit       = QtWidgets.QLineEdit
QTextEdit       = QtWidgets.QTextEdit
QPushButton     = QtWidgets.QPushButton
QComboBox       = QtWidgets.QComboBox
QCheckBox       = QtWidgets.QCheckBox
QSpinBox        = QtWidgets.QSpinBox
QDoubleSpinBox  = QtWidgets.QDoubleSpinBox
QListWidget     = QtWidgets.QListWidget
QListWidgetItem = QtWidgets.QListWidgetItem
QScrollArea     = QtWidgets.QScrollArea
QGroupBox       = QtWidgets.QGroupBox
QSplitter       = QtWidgets.QSplitter
QTabWidget      = QtWidgets.QTabWidget
QMessageBox     = QtWidgets.QMessageBox
QSizePolicy     = QtWidgets.QSizePolicy
QFrame          = QtWidgets.QFrame
QToolBar        = QtWidgets.QToolBar
QStatusBar      = QtWidgets.QStatusBar
QMenuBar        = QtWidgets.QMenuBar

Qt              = QtCore.Qt
QSize           = QtCore.QSize
QTimer          = QtCore.QTimer

QFont           = QtGui.QFont
QColor          = QtGui.QColor
QPalette        = QtGui.QPalette
QIcon           = QtGui.QIcon


def binding_name():
    """Return the active Qt binding: 'Qt.py', 'PySide6' or 'PySide2'."""
    return _BINDING


def pyside_version():
    """Best-effort major version (6 / 2); 0 when going through Qt.py."""
    return {"PySide6": 6, "PySide2": 2}.get(_BINDING, 0)


def set_section_resize_mode(header, mode):
    """QHeaderView.setSectionResizeMode, whichever binding we are on.

    Qt.py routes it through QtCompat (it has to cover PyQt4/PySide1, where the
    method was called setResizeMode); on PySide2/PySide6 the header carries it
    natively.
    """
    if QtCompat is not None and hasattr(QtCompat, "setSectionResizeMode"):
        QtCompat.setSectionResizeMode(header, mode)
    else:
        header.setSectionResizeMode(mode)