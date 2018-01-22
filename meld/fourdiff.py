from gi.repository import GObject
from gi.repository import Gtk

from . import melddoc
from .filediff import FileDiff
from . import recent


class FourDiff(melddoc.MeldDoc):
    """Two or three way comparison of text files"""

    __gtype_name__ = "FourDiff"

    __gsettings_bindings__ = (
        ('ignore-blank-lines', 'ignore-blank-lines'),
    )

    ignore_blank_lines = GObject.property(
        type=bool,
        nick="Ignore blank lines",
        blurb="Whether to ignore blank lines when comparing file contents",
        default=False,
    )

    __gsignals__ = {
        'next-conflict-changed': (GObject.SignalFlags.RUN_FIRST, None,
                                  (bool, bool)),
        'action-mode-changed': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self):
        global fourdiff
        fourdiff = self
        melddoc.MeldDoc.__init__(self)
        self.widget = self.stack = Gtk.Stack()
        self.widget.show()
        self.widget.pyobject = self
        self.ui_file = None

        self.grid0 = Gtk.Grid()
        self.grid0.set_row_homogeneous(True)
        self.grid0.set_column_homogeneous(True)
        self.stack.add_named(self.grid0, "grid0")
        self.grid1 = Gtk.Grid()
        self.grid1.set_row_homogeneous(True)
        self.grid1.set_column_homogeneous(True)
        self.stack.add_named(self.grid1, "grid1")

        self.diff0 = FileDiff(2)
        self.scheduler.add_scheduler(self.diff0.scheduler)
        self.diff0.force_readonly = [True, True]
        self.grid0.attach(self.diff0.widget, left=0, top=0, width=2, height=1)

        self.diff1 = FileDiff(2)
        self.scheduler.add_scheduler(self.diff1.scheduler)
        self.diff1.force_readonly = [True, True]
        self.label0 = Gtk.Label()
        self.label1 = Gtk.Label()
        self.grid1.attach(self.label0, left=0, top=0, width=1, height=1)
        self.grid1.attach(self.diff1.widget, left=1, top=0, width=2, height=1)
        self.grid1.attach(self.label1, left=3, top=0, width=1, height=1)

        self.diff2 = FileDiff(2)
        self.scheduler.add_scheduler(self.diff2.scheduler)
        self.diff2.force_readonly = [True, False]
        self.undosequence = self.diff2.undosequence
        self.actiongroup = self.diff2.actiongroup
        self.grid0.attach(self.diff2.widget, left=2, top=0, width=2, height=1)

        self.diffs = [self.diff0, self.diff1, self.diff2]
        self.have_next_diffs = [(False, False) for _ in self.diffs]
        for diff in self.diffs:
            diff.connect("next-diff-changed", self.on_have_next_diff_changed)

        self.grid0.connect("set-focus-child", self.on_grid0_set_focus_child)

        self.label0.show()
        self.label1.show()
        self.grid0.show()
        self.grid1.show()

        self.files = None

        self._keep = []
        self.connect_scrolledwindows()

    def set_files(self, files):
        """Load the given files

        If an element is None, the text of a pane is left as is.
        """
        assert len(files) == 4
        self.files = files
        self.diff0.set_files(files[:2])
        self.diff1.set_files(files[1:3])
        self.diff2.set_files(files[2:])

    def get_comparison(self):
        return recent.TYPE_FILE, self.files

    def save(self):
        self.diff2.save()

    def save_as(self):
        self.diff2.save_as()

    def on_undo_activate(self):
        self.diff2.on_undo_activate()

    def on_redo_activate(self):
        self.diff2.on_redo_activate()

    def on_refresh_activate(self, *extra):
        for diff in self.diffs:
            diff.on_refresh_activate()

    def on_have_next_diff_changed(self, diff, have_prev, have_next):
        i = self.diffs.index(diff)
        self.have_next_diffs[i] = (have_prev, have_next)
        if diff is self.get_active_diff():
            self.emit("next-diff-changed", have_prev, have_next)

    def get_active_diff(self):
        name = self.stack.get_visible_child_name()
        if name == 'grid0':
            if self.diff0.widget.get_focus_child() is not None:
                return self.diff0
            elif self.diff2.widget.get_focus_child() is not None:
                return self.diff2
            else:
                return None
        elif name == 'grid1':
            return self.diff1
        else:
            return None

    def on_grid0_set_focus_child(self, _container, _widget):
        self.on_active_diff_changed()

    def on_active_diff_changed(self):
        diff = self.get_active_diff()
        if diff is None:
            have_prev = have_next = False
        else:
            i = self.diffs.index(diff)
            have_prev, have_next = self.have_next_diffs[i]
        self.emit("next-diff-changed", have_prev, have_next)

    def next_diff(self, direction, centered=False):
        return self.get_active_diff().next_diff(direction, centered)

    def toggle_view(self):
        if self.stack.get_visible_child_name() == 'grid1':
            self.stack.set_visible_child_name('grid0')
        else:
            self.stack.set_visible_child_name('grid1')
        self.on_active_diff_changed()

    def on_find_activate(self, *args):
        diff = self.get_active_diff()
        if diff:
            diff.on_find_activate(*args)

    def on_replace_activate(self, *args):
        diff = self.get_active_diff()
        if diff:
            diff.on_replace_activate(*args)

    def on_find_next_activate(self, *args):
        diff = self.get_active_diff()
        if diff:
            diff.on_find_next_activate(*args)

    def on_find_previous_activate(self, *args):
        diff = self.get_active_diff()
        if diff:
            diff.on_find_previous_activate(*args)

    def on_delete_event(self):
        buf = self.diff2.textbuffer[1]
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(),
                            include_hidden_chars=True)
        if '<<<<<<<' in text or '>>>>>>>>' in text:
            dialog = Gtk.MessageDialog(
                self.widget.get_toplevel(), 0, Gtk.MessageType.WARNING,
                Gtk.ButtonsType.NONE,
                "Conflict markers remaining. Are you sure you want to close?")
            dialog.add_button("Close with conflict markers", Gtk.ResponseType.OK)
            dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.OK:
                return Gtk.ResponseType.CANCEL

        for diff in self.diffs:
            response = diff.on_delete_event()
            if response == Gtk.ResponseType.CANCEL:
                return response
        else:
            self.emit('close', 0)
            return Gtk.ResponseType.OK

    def connect_scrolledwindows(self):
        sws = [self.diff0.scrolledwindow[1], self.diff1.scrolledwindow[0],
               self.diff1.scrolledwindow[1], self.diff2.scrolledwindow[0]]
        vadjs = [sw.get_vadjustment() for sw in sws]
        hadjs = [sw.get_hadjustment() for sw in sws]
        # We keep the references because otherwise we get uninitialized
        # references in the callbacks
        self._keep.extend([vadjs, hadjs])

        def connect(adj0, adj1):
            adj0.connect("value-changed", self.on_adj_changed, adj1)
            adj1.connect("value-changed", self.on_adj_changed, adj0)
        connect(vadjs[0], vadjs[1])
        connect(hadjs[0], hadjs[1])
        connect(vadjs[2], vadjs[3])
        connect(hadjs[2], hadjs[3])

    @staticmethod
    def on_adj_changed(me, other):
        v = me.get_value()
        if other.get_value() != v:
            other.set_value(v)
