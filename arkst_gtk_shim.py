"""Headless GTK4 / Libadwaita / GdkPixbuf fallback shim for environments without GTK4 typelibs."""
import sys
import types


def install_gtk4_shim_if_needed():
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        return
    except Exception:
        pass

    import gi
    from gi.repository import GLib, GObject, Gio

    orig_require = gi.require_version

    def _safe_require_version(ns, ver):
        if ns in ("Gtk", "Adw", "Gdk", "GdkPixbuf", "Pango"):
            return
        try:
            orig_require(ns, ver)
        except Exception:
            pass

    gi.require_version = _safe_require_version

    class _MockWidget:
        @classmethod
        def new(cls, *a, **kw):
            return cls()

        def __init__(self, **kwargs):
            self._props = dict(kwargs)
            self._children = []
            self._controllers = []
            self._css_classes = set(kwargs.get("css_classes", []) or [])
            self._signals = {}
            self._next_handler_id = 1
            self._visible = kwargs.get("visible", True)
            self._sensitive = kwargs.get("sensitive", True)
            self._label = kwargs.get("label", "")
            self._text = kwargs.get("text", "")
            self._tooltip = kwargs.get("tooltip_text", "")
            self._name = kwargs.get("name", "")
            self._active = kwargs.get("active", False)
            self._fraction = 0.0
            self._parent = None
            self._child = None
            self._visible_child_name = None
            self._icon_name = kwargs.get("icon_name", "")
            self._hexpand = kwargs.get("hexpand", False)
            self._vexpand = kwargs.get("vexpand", False)
            self._halign = kwargs.get("halign", None)
            self._valign = kwargs.get("valign", None)

        def add_css_class(self, cls):
            self._css_classes.add(cls)

        def remove_css_class(self, cls):
            self._css_classes.discard(cls)

        def has_css_class(self, cls):
            return cls in self._css_classes

        def get_css_classes(self):
            return list(self._css_classes)

        def set_css_classes(self, classes):
            self._css_classes = set(classes or [])

        def append(self, child):
            if child is not None:
                if getattr(gtk_mod, "FlowBox", None) and isinstance(self, gtk_mod.FlowBox) and not isinstance(child, gtk_mod.FlowBoxChild):
                    wrapper = gtk_mod.FlowBoxChild()
                    wrapper.set_child(child)
                    wrapper._parent = self
                    self._children.append(wrapper)
                    return
                if getattr(gtk_mod, "ListBox", None) and isinstance(self, gtk_mod.ListBox) and not isinstance(child, gtk_mod.ListBoxRow):
                    wrapper = gtk_mod.ListBoxRow()
                    wrapper.set_child(child)
                    wrapper._parent = self
                    self._children.append(wrapper)
                    return
                child._parent = self
                self._children.append(child)

        def prepend(self, child):
            if child is not None:
                child._parent = self
                self._children.insert(0, child)

        def insert(self, child, pos):
            if child is not None:
                if getattr(gtk_mod, "FlowBox", None) and isinstance(self, gtk_mod.FlowBox) and not isinstance(child, gtk_mod.FlowBoxChild):
                    wrapper = gtk_mod.FlowBoxChild()
                    wrapper.set_child(child)
                    wrapper._parent = self
                    self._children.insert(pos if pos >= 0 else len(self._children), wrapper)
                    return
                child._parent = self
                self._children.insert(pos if pos >= 0 else len(self._children), child)

        def remove(self, child):
            if child in self._children:
                child._parent = None
                self._children.remove(child)
            else:
                for c in list(self._children):
                    if getattr(c, "_child", None) is child:
                        c._parent = None
                        self._children.remove(c)
                        break

        def remove_all(self):
            for c in self._children:
                c._parent = None
            self._children.clear()

        def get_first_child(self):
            return self._children[0] if self._children else None

        def get_last_child(self):
            return self._children[-1] if self._children else None

        def get_next_sibling(self):
            if self._parent and self in self._parent._children:
                idx = self._parent._children.index(self)
                if idx + 1 < len(self._parent._children):
                    return self._parent._children[idx + 1]
            return None

        def get_parent(self):
            return self._parent

        def set_child(self, child):
            self._child = child
            if child is not None:
                child._parent = self
                self._children = [child]
            else:
                self._children = []

        def get_child(self):
            return self._child if self._child is not None else (self._children[0] if self._children else None)

        def connect(self, sig, cb, *args):
            hid = self._next_handler_id
            self._next_handler_id += 1
            self._signals.setdefault(sig, []).append((hid, cb, args))
            return hid

        def disconnect(self, handler_id):
            for sig, handlers in self._signals.items():
                self._signals[sig] = [h for h in handlers if h[0] != handler_id]

        def emit(self, sig, *emit_args):
            res = None
            for hid, cb, extra_args in list(self._signals.get(sig, [])):
                res = cb(self, *emit_args, *extra_args)
            return res

        def clicked(self):
            return self.emit("clicked")

        def activate(self):
            return self.emit("activate")

        def set_visible(self, v):
            self._visible = bool(v)

        def get_visible(self):
            return self._visible

        def is_visible(self):
            return self._visible

        def set_sensitive(self, s):
            self._sensitive = bool(s)

        def get_sensitive(self):
            return self._sensitive

        def is_sensitive(self):
            return self._sensitive

        def set_label(self, lbl):
            self._label = str(lbl) if lbl is not None else ""

        def get_label(self):
            return self._label

        def set_markup(self, m):
            self._label = str(m) if m is not None else ""

        def get_text(self):
            if self._text:
                return self._text
            return self._label

        def set_text(self, t):
            old = self._text
            self._text = str(t) if t is not None else ""
            self._label = self._text
            if old != self._text:
                self.emit("changed")
                self.emit("search-changed")

        def set_tooltip_text(self, t):
            self._tooltip = str(t) if t is not None else ""

        def get_tooltip_text(self):
            return self._tooltip

        def set_active(self, a):
            old = self._active
            self._active = bool(a)
            if old != self._active:
                self.emit("toggled")
                self.emit("notify::active", None)

        def get_active(self):
            return self._active

        def set_fraction(self, f):
            self._fraction = float(f)

        def get_fraction(self):
            return self._fraction

        def set_icon_name(self, name):
            self._icon_name = str(name) if name is not None else ""

        def get_icon_name(self):
            return self._icon_name

        def set_from_icon_name(self, name):
            self._icon_name = str(name) if name is not None else ""

        def set_from_file(self, path):
            self._props["file"] = path

        def set_from_paintable(self, p):
            self._props["paintable"] = p

        def has_icon(self, name):
            return True

        def add_named(self, child, name):
            if child is not None:
                child._parent = self
                child._stack_name = name
                self._children.append(child)
                if self._visible_child_name is None:
                    self._visible_child_name = name

        def set_visible_child_name(self, name):
            self._visible_child_name = name

        def get_visible_child_name(self):
            return self._visible_child_name

        def get_child_by_name(self, name):
            for c in self._children:
                if getattr(c, "_stack_name", None) == name:
                    return c
            return None

        def add_controller(self, ctrl):
            self._controllers.append(ctrl)

        def observe_controllers(self):
            return self._controllers

        def add_overlay(self, w):
            self.append(w)

        def add_toast(self, toast):
            self._last_toast = toast

        def present(self, *args):
            pass

        def close(self):
            pass

        def grab_focus(self):
            return True

        def set_position(self, pos):
            self._cursor_pos = pos

        def get_width(self):
            return getattr(self, "_width", 1120)

        def get_height(self):
            return getattr(self, "_height", 720)

        def get_allocated_width(self):
            return getattr(self, "_width", 1120)

        def get_allocated_height(self):
            return getattr(self, "_height", 720)

        def get_value(self):
            return getattr(self, "_value", 0.0)

        def set_value(self, v):
            self._value = float(v)

        def get_vadjustment(self):
            return _MockWidget()

        def get_hadjustment(self):
            return _MockWidget()

        def get_style_context(self):
            return _MockWidget()

        def get_buffer(self):
            return _MockWidget()

        def get_root(self):
            return _MockWidget()

        def set_halign(self, a):
            self._halign = a

        def get_halign(self):
            return self._halign

        def set_valign(self, a):
            self._valign = a

        def get_valign(self):
            return self._valign

        def set_size_request(self, w, h):
            self._size_req = (w, h)

        def get_size_request(self):
            return getattr(self, "_size_req", (-1, -1))

        def compute_bounds(self, target):
            return (False, None)

        def pick(self, x, y, flags=0):
            return None

        def is_ancestor(self, other):
            return False

        def set_filter_func(self, fn):
            self._filter_func = fn

        def invalidate_filter(self):
            fn = getattr(self, "_filter_func", None)
            if fn:
                for c in self._children:
                    c._child_visible = bool(fn(c))

        def get_child_visible(self):
            return getattr(self, "_child_visible", True)

        def is_fullscreen(self):
            return False

        def is_maximized(self):
            return False

        def get_position(self):
            return getattr(self, "_cursor_pos", len(self._text))

        def get_width(self):
            return getattr(self, "_width", 1120)

        def get_height(self):
            return getattr(self, "_height", 720)

        def get_allocated_width(self):
            return getattr(self, "_width", 1120)

        def get_allocated_height(self):
            return getattr(self, "_height", 720)

        def get_value(self):
            return getattr(self, "_value", 0.0)

        def set_value(self, v):
            self._value = float(v)

        def get_vadjustment(self):
            return _MockWidget()

        def get_hadjustment(self):
            return _MockWidget()

        def get_style_context(self):
            return _MockWidget()

        def get_buffer(self):
            return _MockWidget()

        def get_root(self):
            return _MockWidget()

        def set_halign(self, a):
            self._halign = a

        def get_halign(self):
            return self._halign

        def set_valign(self, a):
            self._valign = a

        def get_valign(self):
            return self._valign

        def set_size_request(self, w, h):
            self._size_req = (w, h)

        def get_size_request(self):
            return getattr(self, "_size_req", (-1, -1))

        def compute_bounds(self, target):
            return (False, None)

        def pick(self, x, y, flags=0):
            return None

        def is_ancestor(self, other):
            return False

        def set_filter_func(self, fn):
            self._filter_func = fn

        def invalidate_filter(self):
            fn = getattr(self, "_filter_func", None)
            if fn:
                for c in self._children:
                    c._child_visible = bool(fn(c))

        def get_child_visible(self):
            return getattr(self, "_child_visible", True)

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return lambda *a, **kw: None

    class _EnumNamespace:
        def __init__(self, **vals):
            for k, v in vals.items():
                setattr(self, k, v)

        def __call__(self, val=0):
            return val

        def __getattr__(self, k):
            return k

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    for cls_name in [
        "Widget", "Box", "Button", "ToggleButton", "CheckButton", "Switch",
        "Label", "Image", "Picture", "Entry", "SearchEntry", "PasswordEntry",
        "ScrolledWindow", "FlowBox", "FlowBoxChild", "ListBox", "ListBoxRow",
        "Stack", "Overlay", "ProgressBar", "Spinner", "Separator", "Frame",
        "Grid", "HeaderBar", "Window", "ApplicationWindow", "Application",
        "Popover", "MenuButton", "DropDown", "StringList", "TextView",
        "TextBuffer", "DrawingArea", "Revealer", "Paned", "Expander",
        "Notebook", "EventControllerMotion", "EventControllerKey",
        "EventControllerScroll", "GestureClick", "CssProvider", "StyleContext",
        "IconTheme", "FileDialog", "FileFilter", "Adjustment", "Scale",
    ]:
        setattr(gtk_mod, cls_name, type(cls_name, (_MockWidget,), {}))

    gtk_mod.Window.set_default_icon_name = staticmethod(lambda *a, **kw: None)
    gtk_mod.Image.new_from_icon_name = classmethod(lambda cls, name=None: cls(icon_name=name))
    gtk_mod.Image.new_from_file = classmethod(lambda cls, path=None: cls(file=path))
    gtk_mod.Image.new_from_paintable = classmethod(lambda cls, p=None: cls(paintable=p))
    gtk_mod.Picture.new_for_filename = classmethod(lambda cls, p=None: cls(file=p))
    gtk_mod.Picture.new_for_paintable = classmethod(lambda cls, p=None: cls(paintable=p))
    gtk_mod.ToggleButton.new_with_label = classmethod(lambda cls, lbl="": cls(label=lbl))
    gtk_mod.Button.new_with_label = classmethod(lambda cls, lbl="": cls(label=lbl))
    gtk_mod.Button.new_from_icon_name = classmethod(lambda cls, name="": cls(icon_name=name))
    gtk_mod.StyleContext.add_provider_for_display = staticmethod(lambda *a, **kw: None)
    gtk_mod.IconTheme.get_for_display = staticmethod(lambda *a, **kw: _MockWidget())

    gtk_mod.Orientation = _EnumNamespace(HORIZONTAL="horizontal", VERTICAL="vertical")
    gtk_mod.Align = _EnumNamespace(FILL="fill", START="start", END="end", CENTER="center", BASELINE="baseline")
    gtk_mod.PolicyType = _EnumNamespace(AUTOMATIC="auto", NEVER="never", ALWAYS="always", EXTERNAL="external")
    gtk_mod.SelectionMode = _EnumNamespace(NONE="none", SINGLE="single", BROWSE="browse", MULTIPLE="multiple")
    gtk_mod.StackTransitionType = _EnumNamespace(CROSSFADE="crossfade", SLIDE_LEFT_RIGHT="slide_lr", NONE="none")
    gtk_mod.Justification = _EnumNamespace(LEFT="left", RIGHT="right", CENTER="center", FILL="fill")
    gtk_mod.WrapMode = _EnumNamespace(NONE="none", CHAR="char", WORD="word", WORD_CHAR="word_char")
    gtk_mod.ContentFit = _EnumNamespace(FILL="fill", CONTAIN="contain", COVER="cover", SCALE_DOWN="scale_down")
    gtk_mod.RevealerTransitionType = _EnumNamespace(SLIDE_DOWN="slide_down", CROSSFADE="crossfade", NONE="none")
    gtk_mod.EventControllerScrollFlags = _EnumNamespace(VERTICAL=1, HORIZONTAL=2, BOTH_AXES=3)
    gtk_mod.Overflow = _EnumNamespace(HIDDEN="hidden", VISIBLE="visible")
    gtk_mod.PropagationPhase = _EnumNamespace(NONE=0, CAPTURE=1, BUBBLE=2, TARGET=3)
    gtk_mod.PickFlags = _EnumNamespace(DEFAULT=0, INSENSITIVE=1, NON_TARGETABLE=2)
    gtk_mod.DropTarget = type("DropTarget", (_MockWidget,), {})
    gtk_mod.Editable = type("Editable", (_MockWidget,), {})
    gtk_mod.ButtonsType = _EnumNamespace(NONE=0, OK=1, CLOSE=2, CANCEL=3, YES_NO=4, OK_CANCEL=5)
    gtk_mod.MessageType = _EnumNamespace(INFO=0, WARNING=1, QUESTION=2, ERROR=3, OTHER=4)
    gtk_mod.STYLE_PROVIDER_PRIORITY_APPLICATION = 600
    gtk_mod.STYLE_PROVIDER_PRIORITY_USER = 800

    adw_mod = types.ModuleType("gi.repository.Adw")
    for cls_name in [
        "Application", "ApplicationWindow", "Window", "HeaderBar", "ToastOverlay",
        "Toast", "StatusPage", "PreferencesPage", "PreferencesGroup", "ActionRow",
        "SwitchRow", "ComboRow", "ExpanderRow", "EntryRow", "PasswordEntryRow",
        "Clamp", "Bin", "Avatar", "Banner", "ViewStack", "ViewSwitcher",
        "NavigationView", "NavigationPage", "OverlaySplitView", "ToolbarView",
        "WindowTitle", "MessageDialog", "AlertDialog", "AboutWindow", "StyleManager",
    ]:
        setattr(adw_mod, cls_name, type(cls_name, (_MockWidget,), {}))
    adw_mod.Breakpoint = type("Breakpoint", (_MockWidget,), {})
    adw_mod.ResponseAppearance = _EnumNamespace(DEFAULT=0, SUGGESTED=1, DESTRUCTIVE=2)
    adw_mod.breakpoint_condition_parse = staticmethod(lambda s: s)
    adw_mod.Toast.new = classmethod(lambda cls, title="": cls(title=title))
    adw_mod.StyleManager.get_default = staticmethod(lambda: _MockWidget())
    adw_mod.ColorScheme = _EnumNamespace(FORCE_DARK="force_dark", DEFAULT="default", PREFER_DARK="prefer_dark")

    gdk_mod = types.ModuleType("gi.repository.Gdk")
    gdk_mod.Display = type("Display", (_MockWidget,), {"get_default": staticmethod(lambda: _MockWidget())})
    gdk_mod.Cursor = type("Cursor", (_MockWidget,), {"new_from_name": staticmethod(lambda *a: _MockWidget())})
    gdk_mod.Texture = type("Texture", (_MockWidget,), {
        "new_from_filename": staticmethod(lambda *a: _MockWidget()),
        "new_for_pixbuf": staticmethod(lambda *a: _MockWidget()),
    })
    gdk_mod.ModifierType = _EnumNamespace(CONTROL_MASK=4, SHIFT_MASK=1, ALT_MASK=8, SUPER_MASK=67108864, META_MASK=268435456)
    gdk_mod.DragAction = _EnumNamespace(COPY=1, MOVE=2, LINK=4, ASK=8)
    gdk_mod.FileList = type("FileList", (_MockWidget,), {})
    gdk_mod.keyval_to_unicode = staticmethod(lambda kv: kv if isinstance(kv, int) and 32 <= kv <= 126 else 0)
    gdk_mod.KEY_Escape = 65307
    gdk_mod.KEY_BackSpace = 65288
    gdk_mod.KEY_f = 102
    gdk_mod.KEY_F = 70
    gdk_mod.KEY_k = 107
    gdk_mod.KEY_K = 75
    gdk_mod.KEY_r = 114
    gdk_mod.KEY_R = 82
    gdk_mod.KEY_q = 113
    gdk_mod.KEY_Q = 81
    gdk_mod.KEY_a = 97
    gdk_mod.KEY_z = 122
    gdk_mod.KEY_Return = 65293
    gdk_mod.KEY_KP_Enter = 65421

    pixbuf_mod = types.ModuleType("gi.repository.GdkPixbuf")
    pixbuf_mod.Pixbuf = type("Pixbuf", (_MockWidget,), {
        "new_from_file": staticmethod(lambda *a: _MockWidget()),
        "new_from_file_at_scale": staticmethod(lambda *a: _MockWidget()),
        "new_from_stream_at_scale": staticmethod(lambda *a: _MockWidget()),
    })
    pixbuf_mod.InterpType = _EnumNamespace(BILINEAR="bilinear", HYPER="hyper")

    pango_mod = types.ModuleType("gi.repository.Pango")
    pango_mod.EllipsizeMode = _EnumNamespace(NONE="none", START="start", MIDDLE="middle", END="end")
    pango_mod.WrapMode = _EnumNamespace(WORD="word", CHAR="char", WORD_CHAR="word_char")

    import gi.repository
    for name, mod in [
        ("Gtk", gtk_mod),
        ("Adw", adw_mod),
        ("Gdk", gdk_mod),
        ("GdkPixbuf", pixbuf_mod),
        ("Pango", pango_mod),
    ]:
        setattr(gi.repository, name, mod)
        sys.modules[f"gi.repository.{name}"] = mod
