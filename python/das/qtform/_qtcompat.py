"""
das.qtform._qtcompat  -  Qt binding shim
========================================
Import everything Qt-related from here.  Binding preference order:

    Qt.py  ->  PySide6  ->  PySide2

Qt.py is tried first (it already normalises PySide2/PySide6/PyQt for us, so we
don't want to duplicate that work); when it isn't installed we fall back to
PySide6, then PySide2.  This module is imported lazily by das.qtform, so
`import das` never pulls in a Qt binding.
"""

_BINDING = None

try:
    # Qt.py (preferred): a single API over PySide2/PySide6/PyQt5
    from Qt import QtWidgets, QtCore, QtGui
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