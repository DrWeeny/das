"""
das.ui  -  framework-neutral UI layer for a das schema
======================================================
Separates *what the data is* (the das schema) from *how it's presented*.

There is **no Qt here** -- only an abstract description (`ui_for` -> `UiSchema`)
plus a renderer dispatch (`render`).  A renderer turns the overlay into a real
UI for some framework (`das.qtform` registers the "qt" one; a "web" stub here
emits a JSON uiSchema).  The overlay serialises to/from a dict (a `.ui.json`),
so the same description can drive Qt today and a web frontend later -- as long
as widgets are referenced by name (the canonical vocabulary below).

    schema = das.get_schema_type("toolmanifest.Tool")   # data contract (shared)
    ui = das.ui.ui_for(schema)                           # per-form overlay (a copy)
    ui.entry_point.set_widget("filepath")
    ui.description.set_widget("multiline", rows=5)
    win  = das.ui.render(schema, ui, framework="qt")     # PySide form
    spec = das.ui.render(schema, ui, framework="web")    # JSON for a frontend
"""

import das
from das import schematypes as st


# Canonical, framework-neutral widget vocabulary -- the contract every renderer
# agrees on.  "auto" means "let the renderer pick from the das type".
WIDGETS = (
    "auto", "lineedit", "multiline", "password",
    "filepath", "dirpath", "image", "url",
    "combo", "spinbox", "checkbox", "list", "dict", "struct",
)


# ---------------------------------------------------------------------------
#  neutral type resolution + convention defaults
# ---------------------------------------------------------------------------

def _resolve(t):
    while True:
        if isinstance(t, st.Optional):
            t = t.type
            continue
        if isinstance(t, st.Or):
            non_empty = [x for x in t.types if not isinstance(x, st.Empty)]
            if len(t.types) >= 2 and len(non_empty) == 1:
                t = non_empty[0]
                continue
            break
        if isinstance(t, st.SchemaType):
            t = das.get_schema_type(t.name)
            continue
        break
    return t


def default_widget(t):
    """The widget a renderer would pick from the das type alone (convention)."""
    t = _resolve(t)
    if isinstance(t, st.Boolean):
        return "checkbox"
    if isinstance(t, st.Integer) and t.enum is not None:
        return "combo"
    if isinstance(t, (st.Integer, st.Real)):
        return "spinbox"
    if isinstance(t, st.String) and t.choices is not None:
        return "combo"
    if isinstance(t, st.String):
        return "lineedit"
    if isinstance(t, (st.Sequence, st.Set)):
        return "list"
    if isinstance(t, st.Dict):
        return "dict"
    if isinstance(t, (st.Struct, st.StaticDict)):
        return "struct"
    return "lineedit"


# ---------------------------------------------------------------------------
#  overlay objects
# ---------------------------------------------------------------------------

class UiField(object):
    """How one struct field is presented.  Pure data; chainable setters."""

    def __init__(self, name):
        self.name = name
        self.widget = "auto"      # "auto" -> renderer infers from the type
        self.options = {}         # widget options, e.g. {"rows": 5}
        self.label = None         # override the field label
        self.help = None          # override tooltip / help text
        self.required = None      # UI-only completeness flag (None -> infer)
        self.hidden = False
        self._factory = None      # raw (framework-specific) widget factory, if any

    def set_widget(self, widget, **options):
        """`widget` is a vocabulary name, or a raw callable (framework-only)."""
        if callable(widget):
            self._factory = widget
            self.widget = "custom"
        else:
            self.widget = widget
        if options:
            self.options.update(options)
        return self

    def set_label(self, text):
        self.label = text
        return self

    def set_help(self, text):
        self.help = text
        return self

    def set_required(self, flag=True):
        self.required = flag
        return self

    def hide(self, flag=True):
        self.hidden = flag
        return self

    def to_dict(self):
        d = {}
        if self.widget not in ("auto",):
            d["widget"] = self.widget
        if self.options:
            d["options"] = dict(self.options)
        if self.label is not None:
            d["label"] = self.label
        if self.help is not None:
            d["help"] = self.help
        if self.required is not None:
            d["required"] = self.required
        if self.hidden:
            d["hidden"] = True
        # note: a raw `_factory` cannot be serialised; only its "custom" marker
        return d

    @classmethod
    def from_dict(cls, name, d):
        f = cls(name)
        f.widget = d.get("widget", "auto")
        f.options = dict(d.get("options", {}))
        f.label = d.get("label")
        f.help = d.get("help")
        f.required = d.get("required")
        f.hidden = d.get("hidden", False)
        return f


class UiType(object):
    """Overlay for one das Struct type: its fields' presentation + order.

    Field access is by attribute (`ui_type.entry_point`) or item
    (`ui_type["entry_point"]`).  Reserved method names (`order`, `field`, ...)
    win over a same-named field via attribute access; use `.field("order")` then.
    """

    def __init__(self, type_name, field_names):
        object.__setattr__(self, "type_name", type_name)
        object.__setattr__(self, "_fields", {n: UiField(n) for n in field_names})
        object.__setattr__(self, "_order", list(field_names))

    def field(self, name):
        return self._fields[name]

    def fields(self):
        return dict(self._fields)

    def order(self, names=None):
        if names is None:
            return list(self._order)
        known = [n for n in names if n in self._fields]
        rest = [n for n in self._order if n not in known]
        object.__setattr__(self, "_order", known + rest)
        return self

    def __getattr__(self, name):
        flds = object.__getattribute__(self, "_fields")
        if name in flds:
            return flds[name]
        raise AttributeError(name)

    def __getitem__(self, name):
        return self._fields[name]

    def to_dict(self):
        out = {"order": list(self._order)}
        fields = {}
        for n, f in self._fields.items():
            fd = f.to_dict()
            if fd:
                fields[n] = fd
        if fields:
            out["fields"] = fields
        return out


class UiSchema(object):
    """The whole overlay: one UiType per das type, with a root.

    Attribute / item access on the root type's fields is proxied for
    convenience (`ui.entry_point`); reach a reused type with `ui["ns.Type"]`.
    """

    def __init__(self, root_type_name):
        object.__setattr__(self, "root", root_type_name)
        object.__setattr__(self, "_types", {})

    def add_type(self, ui_type):
        self._types[ui_type.type_name] = ui_type
        return ui_type

    def for_type(self, type_name):
        return self._types.get(type_name)

    def types(self):
        return dict(self._types)

    def order(self, names=None):
        return self._types[self.root].order(names)

    def __getitem__(self, type_name):
        return self._types[type_name]

    def __getattr__(self, name):
        types = object.__getattribute__(self, "_types")
        root = object.__getattribute__(self, "root")
        rt = types.get(root)
        if rt is not None and name in rt.fields():
            return rt.field(name)
        raise AttributeError(name)

    def to_dict(self):
        return {"root": self.root,
                "types": {n: t.to_dict() for n, t in self._types.items()}}

    @classmethod
    def from_dict(cls, d):
        ui = cls(d["root"])
        for name, td in d.get("types", {}).items():
            order = td.get("order") or list(td.get("fields", {}).keys())
            ut = UiType(name, order)
            object.__setattr__(ut, "_order", list(order))
            for fn, fd in td.get("fields", {}).items():
                ut._fields[fn] = UiField.from_dict(fn, fd)
            ui.add_type(ut)
        return ui


# ---------------------------------------------------------------------------
#  build a default overlay from a das schema
# ---------------------------------------------------------------------------

def _struct_fields(t):
    return [k for k in t.ordered_keys() if not st.Alias.Check(t[k])]


def ui_for(schema):
    """Build a fresh, framework-neutral overlay for a das schema type.

    `schema` is a schema-type name ("toolmanifest.Tool") or the type object.
    Every named Struct reachable from the root gets a UiType keyed by its das
    type name; all fields start at widget "auto".  The result is a *copy* you
    own -- it never mutates the shared/cached schema types.
    """
    if isinstance(schema, str):
        name = schema
        stype = das.get_schema_type(name)
    else:
        stype = schema
        name = das.get_schema_type_name(stype)

    ui = UiSchema(name)
    seen = set()

    def walk(t):
        t = _resolve(t)
        if isinstance(t, (st.Struct, st.StaticDict)):
            tname = das.get_schema_type_name(t)
            if tname and tname not in seen:
                seen.add(tname)
                ui.add_type(UiType(tname, _struct_fields(t)))
                for k in _struct_fields(t):
                    walk(t[k])
        elif isinstance(t, (st.Sequence, st.Set)):
            walk(t.type)
        elif isinstance(t, st.Dict):
            walk(t.vtype)

    walk(stype)
    return ui


# ---------------------------------------------------------------------------
#  renderer dispatch
# ---------------------------------------------------------------------------

_RENDERERS = {}

# built-in frameworks whose module registers a renderer when imported
_BUILTIN_MODULES = {"qt": "das.qtform"}


def register_renderer(name, fn):
    """Register a renderer:  fn(schema_name, ui, **kw) -> framework artifact."""
    _RENDERERS[name] = fn


def frameworks():
    return sorted(set(_RENDERERS) | set(_BUILTIN_MODULES))


def render(schema, ui=None, framework="qt", **kw):
    """Render `schema` (name or type) with `ui` (overlay) using `framework`.

    If `ui` is None a default overlay is built from the schema.  Built-in
    framework modules (e.g. das.qtform) are imported lazily on first use, so
    `import das.ui` never pulls in a Qt binding.
    """
    name = schema if isinstance(schema, str) else das.get_schema_type_name(schema)
    if ui is None:
        ui = ui_for(name)
    if framework not in _RENDERERS and framework in _BUILTIN_MODULES:
        __import__(_BUILTIN_MODULES[framework])     # registers the renderer
    if framework not in _RENDERERS:
        raise ValueError("no renderer for framework %r (have: %s)"
                         % (framework, ", ".join(frameworks()) or "<none>"))
    return _RENDERERS[framework](name, ui, **kw)


# ---------------------------------------------------------------------------
#  built-in "web" renderer (Qt-free): emit a JSON uiSchema from the overlay
# ---------------------------------------------------------------------------

def _web_renderer(schema_name, ui, **_kw):
    """Emit a JSON-Schema-style uiSchema from the same overlay (no Qt).

    Each "auto" (or non-portable "custom") field resolves to the neutral
    type-based default, so the output is concrete and frontend-consumable.
    """
    def resolve_type(ui_type, type_obj):
        out = {"order": ui_type.order(), "fields": {}}
        for k in ui_type.order():
            f = ui_type.field(k)
            widget = f.widget
            if widget in ("auto", "custom"):
                ft = type_obj[k] if (type_obj is not None and k in type_obj) else None
                widget = default_widget(ft) if ft is not None else "lineedit"
            entry = {"widget": widget}
            if f.options:
                entry["options"] = dict(f.options)
            if f.label:
                entry["label"] = f.label
            if f.required is not None:
                entry["required"] = f.required
            if f.hidden:
                entry["hidden"] = True
            out["fields"][k] = entry
        return out

    types_out = {}
    for tname, ut in ui.types().items():
        try:
            tobj = das.get_schema_type(tname)
        except Exception:
            tobj = None
        types_out[tname] = resolve_type(ut, tobj)

    return {"schema_type": schema_name, "root": ui.root, "uiSchema": types_out}


register_renderer("web", _web_renderer)