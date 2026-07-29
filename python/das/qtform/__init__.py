"""
das.qtform  -  the Qt form renderer
===================================
Auto-generate a Qt form from a *das* schema type, driven by a framework-neutral
presentation overlay (see :mod:`das.ui`).  This is the form-based counterpart of
:mod:`das.qtui` (the QTreeView debug/TD editor): same schema, friendlier UI.

Registers itself as the ``"qt"`` renderer with :mod:`das.ui`, so::

    from das import ui
    win = ui.render("toolmanifest.Tool", framework="qt")

The Qt binding (Qt.py / PySide6 / PySide2) is resolved lazily by
:mod:`das.qtform._qtcompat`, so ``import das`` never imports a Qt binding.

Widget mapping (type -> default widget; override per field via the overlay)
--------------------------------------------------------------------------
  Boolean                          QCheckBox
  Integer(min,max) / Integer       QSpinBox
  Integer(enum=...)                QComboBox
  Real(min,max) / Real             QDoubleSpinBox
  String(choices=...)              QComboBox (editable if not strict)
  String                           QLineEdit
  Or(T, Empty())                   nullable T  (empty -> None)
  Optional(T)                      T + an "enable" checkbox
  Struct / SchemaType -> Struct    nested QGroupBox (recursion)
  Sequence(scalar) / Set(scalar)   list editor (+/-)
  Sequence(Struct)                 list of sub-forms (+/-)
  Dict(String, V)                  key/value rows (nested editors for struct V)

Opt-in only (never chosen by default), for a Sequence/Dict of *flat* structs::

  set_widget("table")              one row per element, one column per field
                                   (a Dict also gets a leading "key" column)

The overlay carries widget choice, options, order, labels and the UI-only
`required` flag; a mandatory empty field gets a red border (purely visual --
das validation is unchanged).  `__properties__={"widget": ...}` is still honored
as a fallback when no overlay is supplied.
"""

import os
import sys
import io
import json

from das._qtcompat import (  # noqa: E402
    QtWidgets, QApplication, QWidget, QMainWindow,
    QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea,
    QLabel, QLineEdit, QTextEdit, QPushButton, QComboBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QListWidget, QListWidgetItem,
    QGroupBox, QFrame, QMessageBox, QFont,
    Qt, Signal, app_exec, pyside_version, connect_check_state,
)

import das  # noqa: E402
from das import schematypes as st  # noqa: E402


# ---------------------------------------------------------------------------
#  schema introspection
# ---------------------------------------------------------------------------

def resolve(t):
    """Unwrap Optional / Or(.., Empty) / SchemaType down to the renderable type.

    Returns (real_type, optional, nullable).
      optional -> the key may be absent from the dict (Optional / Deprecated)
      nullable -> the value may be None (Or with a single non-Empty branch)
    """
    optional = False
    nullable = False
    while True:
        if isinstance(t, st.Optional):          # Deprecated subclasses Optional
            optional = True
            t = t.type
            continue
        if isinstance(t, st.Or):
            non_empty = [x for x in t.types if not isinstance(x, st.Empty)]
            if len(t.types) >= 2 and len(non_empty) == 1:
                nullable = True
                t = non_empty[0]
                continue
            break
        if isinstance(t, st.SchemaType):
            t = das.get_schema_type(t.name)
            continue
        break
    return t, optional, nullable


def widget_hint(t):
    try:
        return t.get_property("widget")
    except Exception:
        return None


def is_struct(t):
    return isinstance(t, (st.Struct, st.StaticDict))


def is_complete(value):
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def to_plain(v):
    """Recursively convert a das object into plain JSON-serialisable python.

    das.types.Struct is not a dict, and das Sets are real `set`s (which JSON
    cannot encode), so we walk the tree: Struct/dict -> dict, set -> sorted
    list, list/tuple -> list, scalars pass through.
    """
    if isinstance(v, das.types.Struct):
        return {k: to_plain(val) for k, val in v.items()}
    if isinstance(v, dict):
        return {k: to_plain(val) for k, val in v.items()}
    if isinstance(v, (set, frozenset)):
        return [to_plain(x) for x in sorted(v, key=str)]
    if isinstance(v, (list, tuple)):
        return [to_plain(x) for x in v]
    return v


# A missing mandatory field is flagged in red.  There is deliberately no
# "green/filled" style: once a value is there, the field just goes neutral --
# green carries no information the user needs.
_BAD_STYLE = "border: 1px solid #c0392b;"     # red
_NEUTRAL_STYLE = ""


# ---------------------------------------------------------------------------
#  rich string widget(s)  (seed of the widget registry)
# ---------------------------------------------------------------------------

class FilePathWidget(QWidget):
    value_changed = Signal()

    def __init__(self, pick_dir=False, name_filter="", parent=None):
        super().__init__(parent)
        self._pick_dir = pick_dir          # the "is dir" switch
        self._name_filter = name_filter    # e.g. "Images (*.png *.jpg)"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit()
        btn = QPushButton("...")
        btn.setFixedWidth(28)
        lay.addWidget(self._edit, 1)
        lay.addWidget(btn, 0)
        self._edit.textChanged.connect(self.value_changed)
        btn.clicked.connect(self._browse)

    def _browse(self):
        if self._pick_dir:
            p = QtWidgets.QFileDialog.getExistingDirectory(self, "Select directory")
        else:
            p, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select file", "", self._name_filter or "")
        if p:
            self._edit.setText(p)

    def text(self):
        return self._edit.text()

    def setText(self, v):
        self._edit.setText("" if v is None else str(v))


class UrlWidget(QWidget):
    """A line edit + an 'open' button that launches the URL in a browser."""
    value_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("https://...")
        self._btn = QPushButton("open")
        self._btn.setFixedWidth(40)
        self._btn.setToolTip("Open in browser")
        lay.addWidget(self._edit, 1)
        lay.addWidget(self._btn, 0)
        self._edit.textChanged.connect(self.value_changed)
        self._edit.textChanged.connect(self._sync)
        self._btn.clicked.connect(self._open)
        self._sync()

    def _sync(self):
        self._btn.setEnabled(bool(self._edit.text().strip()))

    def _open(self):
        import webbrowser
        url = self._edit.text().strip()
        if url:
            webbrowser.open(url)

    def text(self):
        return self._edit.text()

    def setText(self, v):
        self._edit.setText("" if v is None else str(v))


# Registry: widget-hint name -> factory(returns (widget, getter, setter, signal))
WIDGET_FACTORIES = {}


def register_widget(name, factory):
    """Register a custom rich-widget factory for a String widget-hint."""
    WIDGET_FACTORIES[name] = factory


# Factories take (type, options) where options is the neutral overlay's
# per-widget dict (e.g. {"rows": 5}).  options defaults to {} so the legacy
# __properties__ call site keeps working unchanged.

def _filepath_factory(_t, options=None):
    w = FilePathWidget(pick_dir=False, name_filter=(options or {}).get("filter", ""))
    return w, w.text, w.setText, w.value_changed


def _dirpath_factory(_t, options=None):
    w = FilePathWidget(pick_dir=True)
    return w, w.text, w.setText, w.value_changed


def _image_factory(_t, options=None):
    w = FilePathWidget(
        pick_dir=False,
        name_filter="Images (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.exr);;"
                    "All files (*.*)")
    return w, w.text, w.setText, w.value_changed


def _url_factory(_t, options=None):
    w = UrlWidget()
    return w, w.text, w.setText, w.value_changed


def _multiline_factory(_t, options=None):
    rows = int((options or {}).get("rows", 5))
    w = QTextEdit()
    w.setAcceptRichText(False)                 # the schema stores a plain string
    w.setLineWrapMode(QTextEdit.WidgetWidth)
    w.setTabChangesFocus(True)                 # Tab leaves the field; Enter = newline
    # Fixed height of ~rows lines: QTextEdit otherwise has an Expanding vertical
    # policy and grabs all spare space in the form, centring itself with big gaps.
    w.setFixedHeight(w.fontMetrics().lineSpacing() * rows + 12)
    w.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    return w, w.toPlainText, (lambda v: w.setPlainText("" if v is None else str(v))), w.textChanged


def _password_factory(_t, options=None):
    w = QLineEdit()
    w.setEchoMode(QLineEdit.Password)
    return w, w.text, (lambda v: w.setText("" if v is None else str(v))), w.textChanged


register_widget("filepath", _filepath_factory)
register_widget("dirpath", _dirpath_factory)
register_widget("image", _image_factory)
register_widget("url", _url_factory)
register_widget("multiline", _multiline_factory)
register_widget("password", _password_factory)


# ---------------------------------------------------------------------------
#  scalar field
# ---------------------------------------------------------------------------

class ScalarField(QWidget):
    """One editable widget for a scalar das type, with required coloring."""
    value_changed = Signal()

    def __init__(self, vtype, nullable=False, required=False, parent=None,
                 field_ui=None):
        super().__init__(parent)
        self.vtype = vtype
        self.nullable = nullable
        self.required = required
        self._field_ui = field_ui   # neutral overlay node (or None) -> widget choice
        # Only widgets that can actually be left empty are worth flagging.
        # Set True for text/list-like widgets in _build; stays False for
        # checkbox / spinbox / enum / choice combos (they always hold a value).
        self._highlightable = False
        # das forces a default on every scalar (String -> "", Int -> 0, ...),
        # so we treat an *empty* default ("" / 0 falsy) as "no real default":
        # a field with a meaningful default (e.g. version="0.1.0") never nags.
        self._empty_default = not getattr(vtype, "default", None)
        self._inner = None
        self._get = None
        self._set = None
        self._build()

    def _build(self):
        t = self.vtype
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        badge = t.__class__.__name__.lower()
        fui = self._field_ui

        if fui is not None and getattr(fui, "widget", "auto") == "custom" \
                and getattr(fui, "_factory", None) is not None:
            # overlay: a raw (Qt-only) widget factory  -> highest precedence
            w, getter, setter, sig = fui._factory(t)
            self._get = getter
            self._set = setter
            sig.connect(self.value_changed)
            self._highlightable = True
            badge = "custom"

        elif fui is not None and getattr(fui, "widget", "auto") in WIDGET_FACTORIES:
            # overlay: a named widget from the registry (the portable path)
            w, getter, setter, sig = WIDGET_FACTORIES[fui.widget](t, fui.options)
            self._get = getter
            self._set = setter
            sig.connect(self.value_changed)
            self._highlightable = True
            badge = fui.widget

        elif isinstance(t, st.Boolean):
            w = QCheckBox()
            # isChecked() -> a real bool: the one check-state read that means
            # the same thing on PySide2 and PySide6 (see das._qtcompat).
            self._get = w.isChecked
            self._set = lambda v: w.setChecked(bool(v))
            connect_check_state(w, self.value_changed)

        elif isinstance(t, st.Integer) and t.enum is not None:
            w = QComboBox()
            for k in sorted(t.enum.keys(), key=lambda x: t.enum[x]):
                w.addItem(k, userData=t.enum[k])
            self._get = w.currentData
            self._set = lambda v: w.setCurrentIndex(max(0, w.findData(v)))
            w.currentIndexChanged.connect(self.value_changed)
            badge = "enum"

        elif isinstance(t, st.Integer):
            w = QSpinBox()
            w.setRange(t.min if t.min is not None else -10 ** 9,
                       t.max if t.max is not None else 10 ** 9)
            self._get = w.value
            self._set = lambda v: w.setValue(int(v) if v is not None else 0)
            w.valueChanged.connect(self.value_changed)
            badge = "int"

        elif isinstance(t, st.Real):
            w = QDoubleSpinBox()
            w.setDecimals(4)
            w.setRange(t.min if t.min is not None else -1e12,
                       t.max if t.max is not None else 1e12)
            self._get = w.value
            self._set = lambda v: w.setValue(float(v) if v is not None else 0.0)
            w.valueChanged.connect(self.value_changed)
            badge = "float"

        elif isinstance(t, st.String) and t.choices is not None:
            w = QComboBox()
            choices = t._expand_choices() or []
            w.addItems([str(c) for c in choices])
            w.setEditable(not t.strict)
            self._get = w.currentText
            self._set = self._make_combo_setter(w)
            w.currentIndexChanged.connect(self.value_changed)
            if w.isEditable():
                w.editTextChanged.connect(self.value_changed)
            badge = "choice"

        elif isinstance(t, st.String) and widget_hint(t) in WIDGET_FACTORIES:
            hint = widget_hint(t)
            w, getter, setter, sig = WIDGET_FACTORIES[hint](t, {})
            self._get = getter
            self._set = setter
            sig.connect(self.value_changed)
            self._highlightable = True   # filepath / multiline / password text
            badge = hint

        elif isinstance(t, st.String):
            w = QLineEdit()
            if self.nullable:
                w.setPlaceholderText("(none)")
            self._get = w.text
            self._set = lambda v: w.setText("" if v is None else str(v))
            w.textChanged.connect(self.value_changed)
            self._highlightable = True   # free text can be left empty
            badge = "str" + (" | null" if self.nullable else "")

        else:
            # Empty, Class, multi-Or, Tuple, ... : read-only fallback
            w = QLineEdit()
            w.setReadOnly(True)
            w.setPlaceholderText("<%s: edit in text/tree editor>" % badge)
            self._get = lambda: None
            self._set = lambda v: w.setText("" if v is None else str(v))

        self._inner = w
        lay.addWidget(w, 1)
        lbl = QLabel(badge)
        lbl.setStyleSheet("color:#888; font-size:10px; font-style:italic; padding-left:4px;")
        lay.addWidget(lbl, 0)
        self.value_changed.connect(self._update_state)

    @staticmethod
    def _make_combo_setter(w):
        def _set(v):
            idx = w.findText("" if v is None else str(v))
            if idx >= 0:
                w.setCurrentIndex(idx)
            elif w.isEditable():
                w.setEditText("" if v is None else str(v))
        return _set

    def get_value(self):
        v = self._get()
        if isinstance(self.vtype, st.String) and self.nullable:
            if isinstance(v, str) and v.strip() == "":
                return None
        return v

    def set_value(self, v):
        self._set(v)
        self._update_state()

    def setEnabled(self, on):  # noqa: N802 (Qt naming)
        super().setEnabled(on)
        self._update_state()

    def _update_state(self):
        # red only for a mandatory, empty-defaulted, can-be-empty field that is
        # currently empty; otherwise neutral (no green).
        flag = (self.required and self._highlightable
                and self._empty_default and self.isEnabled())
        if flag and not is_complete(self.get_value()):
            self._inner.setStyleSheet(_BAD_STYLE)
        else:
            self._inner.setStyleSheet(_NEUTRAL_STYLE)


# ---------------------------------------------------------------------------
#  list / dict fields
# ---------------------------------------------------------------------------

class _ComboItemDelegate(QtWidgets.QStyledItemDelegate):
    """In-place editor for list rows: an editable combobox with completer.

    The dropdown offers the element type's `choices` (suggestions); the line
    edit + completer give type-ahead; free text is allowed unless the element
    type is `strict` (and actually has choices to be strict about).
    """

    def __init__(self, choices, strict, parent=None):
        super().__init__(parent)
        self._choices = [str(c) for c in (choices or [])]
        self._strict = bool(strict)

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        editable = (not self._strict) or (not self._choices)
        combo.setEditable(editable)
        combo.addItems(self._choices)
        if editable:
            combo.setInsertPolicy(QComboBox.NoInsert)
            comp = combo.completer()
            if comp is not None:
                comp.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
                comp.setCaseSensitivity(Qt.CaseInsensitive)
        return combo

    def setEditorData(self, editor, index):
        text = index.data(Qt.EditRole) or ""
        i = editor.findText(text)
        if i >= 0:
            editor.setCurrentIndex(i)
        elif editor.isEditable():
            editor.setEditText(text)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText().strip(), Qt.EditRole)

    def sizeHint(self, option, index):
        # give rows enough height that the in-place combobox isn't cropped
        s = super().sizeHint(option, index)
        s.setHeight(max(s.height(), 24))
        return s


class _OverlayListWidget(QListWidget):
    """A QListWidget with a small corner widget floating over its viewport."""

    def __init__(self, corner, parent=None):
        super().__init__(parent)
        self._corner = corner
        corner.setParent(self.viewport())
        corner.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition()

    def _reposition(self):
        c = self._corner
        c.adjustSize()
        c.move(max(0, self.viewport().width() - c.width() - 2),
               max(0, self.viewport().height() - c.height() - 2))
        c.raise_()


class ScalarListField(QWidget):
    """Sequence(scalar) or Set(scalar) editor with in-place editable rows.

    Layout is the "outliner" pattern asked for: a header carrying [+]/[-]
    pinned to the right, over a framed list whose rows are edited in place.

      * [+]  appends a blank row and opens its editor immediately.
      * [-]  removes the selected row(s); disabled while nothing is selected.
      * double-click (or F2) edits an existing row.
      * suggestions for each row come from the element type's choices.
      * when `required`, the frame is red while empty, green once it has >=1.
    """
    value_changed = Signal()

    def __init__(self, container_type, required=False, parent=None):
        super().__init__(parent)
        self.elem_type, _, _ = resolve(container_type.type)
        self.is_set = isinstance(container_type, st.Set)
        self.required = required
        choices = self.elem_type._expand_choices() \
            if getattr(self.elem_type, "choices", None) else []
        strict = getattr(self.elem_type, "strict", False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        # [+]/[−] floating vertically in the list's top-right corner
        corner = QWidget()
        cl = QVBoxLayout(corner)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(1)
        self._add_btn = QPushButton("+")
        self._rm_btn = QPushButton("−")  # minus sign
        for btn in (self._add_btn, self._rm_btn):
            btn.setFixedSize(20, 18)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setStyleSheet(
            "QPushButton{color:#27ae60; font-weight:bold; border:1px solid #27ae60;"
            " border-radius:3px; background:rgba(39,174,96,30);}")
        self._rm_btn.setStyleSheet(
            "QPushButton{color:#c0392b; font-weight:bold; border:1px solid #c0392b;"
            " border-radius:3px; background:rgba(192,57,43,30);}"
            "QPushButton:disabled{color:#888; border-color:#555; background:transparent;}")
        self._rm_btn.setEnabled(False)
        cl.addWidget(self._add_btn)
        cl.addWidget(self._rm_btn)

        # framed list (the frame border carries the required red/green hint)
        self._frame = QFrame()
        self._frame.setObjectName("listFrame")
        fl = QVBoxLayout(self._frame)
        fl.setContentsMargins(1, 1, 1, 1)
        self._list = _OverlayListWidget(corner)
        self._list.setMaximumHeight(110)
        self._list.setItemDelegate(_ComboItemDelegate(choices, strict, self._list))
        self._list.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.SelectedClicked)
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        fl.addWidget(self._list)
        lay.addWidget(self._frame)

        self._add_btn.clicked.connect(self._add)
        self._rm_btn.clicked.connect(self._remove)
        self._list.itemSelectionChanged.connect(self._on_selection)
        self._list.itemChanged.connect(self._on_changed)
        self._list.itemDelegate().closeEditor.connect(self._drop_blanks)
        self._update_state()

    def _coerce(self, text):
        if isinstance(self.elem_type, st.Integer):
            return int(text)
        if isinstance(self.elem_type, st.Real):
            return float(text)
        return text

    def _new_item(self, text=""):
        it = QListWidgetItem(str(text))
        it.setFlags(it.flags() | Qt.ItemIsEditable)
        return it

    def _add(self):
        item = self._new_item("")
        self._list.addItem(item)
        self._list.setCurrentItem(item)
        self._list.editItem(item)

    def _remove(self):
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))
        self.value_changed.emit()
        self._update_state()

    def _drop_blanks(self, *args):
        """Remove rows left empty (a cancelled new row, or a cleared one)."""
        removed = False
        for i in reversed(range(self._list.count())):
            if self._list.item(i).text().strip() == "":
                self._list.takeItem(i)
                removed = True
        if removed:
            self.value_changed.emit()
        self._update_state()

    def _on_changed(self, _item):
        self.value_changed.emit()
        self._update_state()

    def _on_selection(self):
        self._rm_btn.setEnabled(bool(self._list.selectedItems()))

    def _update_state(self):
        # red while a mandatory list is empty; neutral once it has items (no green)
        if self.required and self._list.count() == 0:
            self._frame.setStyleSheet("#listFrame { border: 1px solid #c0392b; }")
        else:
            self._frame.setStyleSheet("")

    def get_value(self):
        vals = []
        for i in range(self._list.count()):
            t = self._list.item(i).text().strip()
            if not t:
                continue
            try:
                vals.append(self._coerce(t))
            except ValueError:
                continue
        return set(vals) if self.is_set else vals

    def set_value(self, values):
        self._list.blockSignals(True)
        self._list.clear()
        for v in (values or []):
            self._list.addItem(self._new_item(v))
        self._list.blockSignals(False)
        self._update_state()


class DictField(QWidget):
    """Dict(String, V) editor: key/value rows.

    V may be a scalar (one widget per row) or a Struct/container, in which
    case the value renders as a nested editor (recursion via make_editor) on
    its own line under the key.
    """
    value_changed = Signal()

    def __init__(self, dict_type, ui_schema=None, parent=None):
        super().__init__(parent)
        self.ui_schema = ui_schema
        self.vtype, _, self._nullable = resolve(dict_type.vtype)
        self._complex = is_struct(self.vtype) or isinstance(
            self.vtype, (st.Sequence, st.Set, st.Dict))
        self._rows = []   # list of (key_edit, val_field, row_widget)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._rows_box = QVBoxLayout()
        self._lay.addLayout(self._rows_box)
        add = QPushButton("+ add entry")
        add.clicked.connect(lambda: self._add_row())
        self._lay.addWidget(add)

    def _add_row(self, key="", value=None):
        ke = QLineEdit(key)
        ke.setPlaceholderText("key")
        vf = make_editor(self.vtype, self._nullable, False, ui_schema=self.ui_schema)
        if value is not None:
            vf.set_value(value)
        rm = QPushButton("−"); rm.setFixedWidth(24)

        if self._complex:
            # key on a header line, nested editor framed below it
            row = QGroupBox()
            gl = QVBoxLayout(row)
            gl.setContentsMargins(6, 4, 6, 6)
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.addWidget(QLabel("key:"), 0)
            head.addWidget(ke, 1)
            head.addWidget(rm, 0)
            gl.addLayout(head)
            gl.addWidget(vf)
        else:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(ke, 1); rl.addWidget(vf, 2); rl.addWidget(rm, 0)

        self._rows_box.addWidget(row)
        entry = (ke, vf, row)
        self._rows.append(entry)
        ke.textChanged.connect(self.value_changed)
        vf.value_changed.connect(self.value_changed)
        rm.clicked.connect(lambda: self._remove(entry))
        self.value_changed.emit()

    def _remove(self, entry):
        ke, vf, row = entry
        self._rows.remove(entry)
        row.setParent(None)
        self.value_changed.emit()

    def get_value(self):
        out = {}
        for ke, vf, _ in self._rows:
            k = ke.text().strip()
            if k:
                out[k] = vf.get_value()
        return out

    def set_value(self, data):
        for _, _, row in self._rows:
            row.setParent(None)
        self._rows = []
        for k, v in (data or {}).items():
            self._add_row(str(k), v)


class StructListField(QWidget):
    """Sequence(Struct) editor: a list of sub-forms."""
    value_changed = Signal()

    def __init__(self, seq_type, ui_schema=None, parent=None):
        super().__init__(parent)
        self.ui_schema = ui_schema
        self.elem_type, _, _ = resolve(seq_type.type)
        self._forms = []
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._forms_box = QVBoxLayout()
        self._lay.addLayout(self._forms_box)
        add = QPushButton("+ add")
        add.clicked.connect(lambda: self._add_form())
        self._lay.addWidget(add)

    def _add_form(self, data=None):
        box = QGroupBox("#%d" % (len(self._forms) + 1))
        bl = QVBoxLayout(box)
        form = StructForm(self.elem_type, ui_schema=self.ui_schema)
        if data is not None:
            form.set_data(data)
        form.value_changed.connect(self.value_changed)
        rm = QPushButton("remove")
        bl.addWidget(form)
        bl.addWidget(rm)
        self._forms_box.addWidget(box)
        entry = (form, box)
        self._forms.append(entry)
        rm.clicked.connect(lambda: self._remove(entry))
        self.value_changed.emit()

    def _remove(self, entry):
        form, box = entry
        self._forms.remove(entry)
        box.setParent(None)
        self.value_changed.emit()

    def get_value(self):
        return [f.get_data() for f, _ in self._forms]

    def set_value(self, items):
        for _, box in self._forms:
            box.setParent(None)
        self._forms = []
        for it in (items or []):
            self._add_form(it)


class StructTableField(QWidget):
    """`Dict(String, Struct)` / `Sequence(Struct)` as a table: rows x columns.

    Same data as `DictField` / `StructListField`, but every element is one ROW
    and every field of the element struct is one COLUMN -- the shape you want
    for a list of render layers, where stacked sub-forms scroll off the screen
    and nothing lines up.  A Dict gets a leading "key" column (the row's name);
    a Sequence has no such column, its rows are positional.

    Opt-in via the overlay (`t.layers.set_widget("table")`) because it is only
    readable when every element field is a scalar -- `make_editor` checks that
    with `is_flat_struct` and falls back when it does not hold.

    Cells are ordinary `ScalarField`s, so a column inherits the widget its das
    type implies: a `choices` column is a combo box, a bounded Integer column
    a spin box, a Boolean column a checkbox -- and a required-but-empty cell
    still gets the red border.
    """
    value_changed = Signal()

    def __init__(self, container_type, ui_schema=None, parent=None):
        super().__init__(parent)
        self.ui_schema = ui_schema
        self.keyed = isinstance(container_type, st.Dict)
        elem = container_type.vtype if self.keyed else container_type.type
        self.elem_type, _, _ = resolve(elem)
        self._columns = self._build_columns()
        self._rows = []          # [(key_edit_or_None, {field_name: ScalarField})]
        self._build()

    # -- columns come from the element struct, filtered/ordered by the overlay
    def _build_columns(self):
        tname = das.get_schema_type_name(self.elem_type) if self.ui_schema else None
        uitype = self.ui_schema.for_type(tname) if (self.ui_schema and tname) else None

        keys = [k for k in self.elem_type.ordered_keys()
                if not st.Alias.Check(self.elem_type[k])]
        if uitype is not None:
            order = uitype.order()
            keys = [k for k in order if k in keys] + [k for k in keys if k not in order]

        columns = []
        for k in keys:
            fui = uitype.field(k) if uitype is not None else None
            if fui is not None and fui.hidden:
                continue
            real, optional, nullable = resolve(self.elem_type[k])
            required = not optional and not nullable
            if fui is not None and fui.required is not None:
                required = fui.required
            label = fui.label if (fui is not None and fui.label) else k
            columns.append((k, real, nullable, required, label, fui))
        return columns

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        headers = ([] if not self.keyed else ["key"]) \
            + [c[4] for c in self._columns] + [""]
        self._table = QtWidgets.QTableWidget(0, len(headers), self)
        self._table.setHorizontalHeaderLabels(headers)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        lay.addWidget(self._table)

        add = QPushButton("+ add row")
        add.clicked.connect(lambda: self._add_row())
        lay.addWidget(add)

    def _add_row(self, key="", value=None):
        row = self._table.rowCount()
        self._table.insertRow(row)
        col = 0

        ke = None
        if self.keyed:
            ke = QLineEdit(str(key))
            ke.setPlaceholderText("key")
            ke.textChanged.connect(self.value_changed)
            self._table.setCellWidget(row, col, ke)
            col += 1

        fields = {}
        for name, real, nullable, required, _label, fui in self._columns:
            f = ScalarField(real, nullable=nullable, required=required, field_ui=fui)
            if value is not None and name in value:
                f.set_value(value[name])
            f.value_changed.connect(self.value_changed)
            self._table.setCellWidget(row, col, f)
            fields[name] = f
            col += 1

        rm = QPushButton("−")
        rm.setFixedWidth(24)
        rm.clicked.connect(lambda: self._remove(rm))
        self._table.setCellWidget(row, col, rm)

        self._rows.append((ke, fields))
        self._table.resizeRowsToContents()
        self.value_changed.emit()

    def _remove(self, button):
        # the row index is looked up now, not captured: removing a row shifts
        # every index below it, so a captured one would delete the wrong row.
        for row in range(self._table.rowCount()):
            if self._table.cellWidget(row, self._table.columnCount() - 1) is button:
                self._table.removeRow(row)
                del self._rows[row]
                self.value_changed.emit()
                return

    def get_value(self):
        if self.keyed:
            out = {}
            for ke, fields in self._rows:
                k = ke.text().strip()
                if k:
                    out[k] = {n: f.get_value() for n, f in fields.items()}
            return out
        return [{n: f.get_value() for n, f in fields.items()}
                for _, fields in self._rows]

    def set_value(self, data):
        while self._table.rowCount():
            self._table.removeRow(0)
        self._rows = []
        if self.keyed:
            for k, v in (data or {}).items():
                self._add_row(k, v)
        else:
            for v in (data or []):
                self._add_row(value=v)


# ---------------------------------------------------------------------------
#  struct form (recursive)
# ---------------------------------------------------------------------------

def is_flat_struct(t):
    """True if every field of struct `t` renders as a single scalar widget.

    A table can only line fields up in columns if none of them is itself a
    struct/sequence/dict -- there is no sane column for a nested document.
    """
    if not is_struct(t):
        return False
    for k in t.ordered_keys():
        if st.Alias.Check(t[k]):
            continue
        real, _, _ = resolve(t[k])
        if is_struct(real) or isinstance(real, (st.Sequence, st.Set, st.Dict)):
            return False
    return True


def wants_table(container_type, field_ui):
    """Table is opt-in: asked for by the overlay, or baked as a schema property.

    Silently falls back when the element type is not flat -- a wrong hint
    should cost a nicer layout, never the ability to edit the document.
    """
    asked = (getattr(field_ui, "widget", None) == "table"
             or widget_hint(container_type) == "table")
    if not asked:
        return False
    elem = container_type.vtype if isinstance(container_type, st.Dict) else container_type.type
    real, _, _ = resolve(elem)
    return is_flat_struct(real)


def make_editor(real_type, nullable, required, field_ui=None, ui_schema=None):
    if is_struct(real_type):
        return StructForm(real_type, ui_schema=ui_schema)
    if isinstance(real_type, st.Sequence):
        elem, _, _ = resolve(real_type.type)
        if wants_table(real_type, field_ui):
            return StructTableField(real_type, ui_schema=ui_schema)
        return StructListField(real_type, ui_schema=ui_schema) if is_struct(elem) \
            else ScalarListField(real_type, required=required)
    if isinstance(real_type, st.Set):
        return ScalarListField(real_type, required=required)
    if isinstance(real_type, st.Dict):
        if wants_table(real_type, field_ui):
            return StructTableField(real_type, ui_schema=ui_schema)
        return DictField(real_type, ui_schema=ui_schema)
    return ScalarField(real_type, nullable=nullable, required=required,
                       field_ui=field_ui)


class StructForm(QWidget):
    """Builds a QFormLayout from a das Struct schema type."""
    value_changed = Signal()

    def __init__(self, struct_type, ui_schema=None, parent=None):
        super().__init__(parent)
        self.struct_type = struct_type
        self.ui_schema = ui_schema
        # the neutral overlay node for *this* type, if the overlay knows it
        tname = das.get_schema_type_name(struct_type) if ui_schema else None
        self.ui_type = ui_schema.for_type(tname) if (ui_schema and tname) else None
        self._fields = {}   # key -> (editor, optional_checkbox_or_None)
        self._build()

    def _build(self):
        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignRight)

        keys = [k for k in self.struct_type.ordered_keys()
                if not st.Alias.Check(self.struct_type[k])]
        if self.ui_type is not None:                 # overlay-driven order
            order = self.ui_type.order()
            keys = [k for k in order if k in keys] + [k for k in keys if k not in order]

        for k in keys:
            ft = self.struct_type[k]
            real, optional, nullable = resolve(ft)
            required = not optional and not nullable
            desc = ft.description or real.description

            fui = self.ui_type.field(k) if self.ui_type is not None else None
            if fui is not None:
                if fui.hidden:
                    continue
                if fui.required is not None:          # UI-only required override
                    required = fui.required
                if fui.help is not None:
                    desc = fui.help

            editor = make_editor(real, nullable, required,
                                 field_ui=fui, ui_schema=self.ui_schema)
            editor.value_changed.connect(self.value_changed)

            base_label = (fui.label if (fui is not None and fui.label) else k)
            label = base_label + (" *" if required else "")
            chk = None
            if optional:
                chk = QCheckBox()
                chk.setChecked(False)
                editor.setEnabled(False)
                chk.toggled.connect(editor.setEnabled)
                chk.toggled.connect(self.value_changed)
                cell = QWidget()
                cl = QHBoxLayout(cell)
                cl.setContentsMargins(0, 0, 0, 0)
                cl.addWidget(chk, 0)
                cl.addWidget(editor, 1)
                row_widget = cell
            else:
                row_widget = editor

            lbl = QLabel(label + ":")
            if desc:
                lbl.setToolTip(desc)
            form.addRow(lbl, row_widget)
            self._fields[k] = (editor, chk)

    def field(self, key):
        """The editor widget for `key`, or None if there is no such row.

        For an embedding tool that only cares about one field: connect to that
        widget's own `value_changed` instead of the form-wide one, which fires
        for any edit and carries no arguments.  Returns None for an unknown key
        *and* for a field the overlay hid -- a hidden field has no widget.
        """
        f = self._fields.get(key)
        return None if f is None else f[0]

    def get_data(self):
        out = {}
        for k, (editor, chk) in self._fields.items():
            if chk is not None and not chk.isChecked():
                continue   # optional field left disabled -> omit key
            out[k] = editor.get_data() if isinstance(editor, StructForm) else editor.get_value()
        return out

    # uniform with the other field widgets
    def get_value(self):
        return self.get_data()

    def set_data(self, data):
        for k, (editor, chk) in self._fields.items():
            present = (data is not None) and (k in data)
            if chk is not None:
                chk.setChecked(present)
                editor.setEnabled(present)
            if present:
                if isinstance(editor, StructForm):
                    editor.set_data(data[k])
                else:
                    editor.set_value(data[k])

    def set_value(self, v):
        self.set_data(v)


# ---------------------------------------------------------------------------
#  editor window
# ---------------------------------------------------------------------------

class DasFormEditor(QMainWindow):
    """Auto form for a das schema type + live das preview + validated save/load."""

    def __init__(self, schema_type_name, save_dir=None, parent=None,
                 initial_data=None, ui=None):
        super().__init__(parent)
        self.schema_type_name = schema_type_name
        self.schema_type = das.get_schema_type(schema_type_name)
        self.ui = ui                 # framework-neutral overlay (das_ui_model), or None
        self.save_dir = save_dir or os.getcwd()
        self.setWindowTitle("das form  -  %s" % schema_type_name)
        self.resize(960, 680)
        self._build_ui()
        if initial_data is not None:
            self.form.set_data(initial_data)
        self._refresh()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.form = StructForm(self.schema_type, ui_schema=self.ui)
        self.form.value_changed.connect(self._refresh)
        scroll.setWidget(self.form)
        root.addWidget(scroll, 3)

        right = QWidget()
        rl = QVBoxLayout(right)
        hdr = QLabel("Live das preview")
        hdr.setStyleSheet("font-weight:bold; padding-bottom:4px;")
        rl.addWidget(hdr)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Courier New", 9))
        self.preview.setStyleSheet("background:#1e1e1e; color:#d4d4d4;")
        rl.addWidget(self.preview, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        rl.addWidget(self.status)
        btns = QHBoxLayout()
        b_load = QPushButton("Load...")
        b_save = QPushButton("Save as JSON (validate + write)")
        b_load.clicked.connect(self._load)
        b_save.clicked.connect(self._save)
        btns.addWidget(b_load); btns.addStretch(); btns.addWidget(b_save)
        rl.addLayout(btns)
        root.addWidget(right, 2)

        self.statusBar().showMessage(
            "PySide%d  -  schema '%s'" % (pyside_version(), self.schema_type_name))

    def _build_object(self):
        """Validate current widget data through das -> returns a das object."""
        data = self.form.get_data()
        return self.schema_type.validate(das.copy(data))

    def _refresh(self):
        try:
            obj = self._build_object()
        except Exception as e:
            self.preview.setPlainText(repr(self.form.get_data()))
            self.status.setText("invalid: %s" % e)
            self.status.setStyleSheet("color:#e44;")
            return
        buf = io.StringIO()
        das.pprint(obj, stream=buf)
        self.preview.setPlainText(buf.getvalue())
        self.status.setText("valid")
        self.status.setStyleSheet("color:#3c3;")

    def _schema_version(self):
        schema = das.get_schema(self.schema_type_name)
        v = getattr(schema, "version", None) if schema else None
        return str(v) if v is not None else None

    # --- format seams (override these for a different on-disk format) -------

    def _default_save_path(self, obj):
        return os.path.join(
            self.save_dir,
            "%s_v%s.json" % (getattr(obj, "name", "tool") or "tool",
                             getattr(obj, "version", "0") or "0"))

    def _save_filter(self):
        return "JSON (*.json)"

    def _load_filter(self):
        return "Manifest (*.json *.toolmanifest);;JSON (*.json);;All files (*.*)"

    def _serialize(self, obj, path):
        # wrap the data so das can still recover schema + version on load
        payload = {
            "schema_type": self.schema_type_name,
            "schema_version": self._schema_version(),
            "data": to_plain(obj),
        }
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=False)
            f.write("\n")

    def _deserialize(self, path):
        if path.lower().endswith(".json"):
            return self._load_json(path)
        # legacy das-native format
        return das.read(path, schema_type=self.schema_type_name)

    # -----------------------------------------------------------------------

    def _save(self):
        # validate through das first (fills defaults, enforces the schema)
        try:
            obj = self._build_object()
        except Exception as e:
            QMessageBox.warning(self, "Validation failed", str(e))
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save", self._default_save_path(obj), self._save_filter())
        if not path:
            return
        self._serialize(obj, path)
        self.status.setText("saved: %s" % path)
        self.status.setStyleSheet("color:#3c3;")

    def _load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load", self.save_dir, self._load_filter())
        if not path:
            return
        try:
            obj = self._deserialize(path)
        except Exception as e:
            QMessageBox.warning(self, "Load failed", str(e))
            return
        self.form.set_data(obj)
        self._refresh()

    def _load_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # accept both the wrapped form ({schema_type, data}) and bare data
        if isinstance(raw, dict) and "data" in raw and "schema_type" in raw:
            stype = raw.get("schema_type") or self.schema_type_name
            data = raw["data"]
        else:
            stype = self.schema_type_name
            data = raw
        schema_type = das.get_schema_type(stype)
        return schema_type.validate(das.copy(data))


def build_app(schema_type_name, save_dir=None, parent=None, ui=None):
    """Create the editor.

    Returns (app, win, created) where `created` is True only when we had to
    create the QApplication ourselves (standalone). Inside a host such as Maya
    a QApplication already exists, so the caller must NOT start a second event
    loop nor call sys.exit().
    """
    existing = QApplication.instance()
    app = existing or QApplication(sys.argv)
    win = DasFormEditor(schema_type_name, save_dir=save_dir, parent=parent, ui=ui)
    return app, win, (existing is None)


# ---------------------------------------------------------------------------
#  register as the "qt" renderer for das.ui.render(...)
# ---------------------------------------------------------------------------

def render(schema_name, ui=None, data=None, parent=None, save_dir=None, **_kw):
    """das.ui renderer entry point: build the form window (not shown)."""
    return DasFormEditor(schema_name, ui=ui, initial_data=data,
                         save_dir=save_dir, parent=parent)


from das import ui as _ui  # noqa: E402
_ui.register_renderer("qt", render)