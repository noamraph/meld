# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import logging

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, GtkSource

from meld import misc
from meld.conf import _
from meld.const import TEXT_FILTER_ACTION_FORMAT
from meld.filediff import FileDiff
from meld.melddoc import MeldDoc
from meld.recent import RecentType
from meld.settings import bind_settings, get_meld_settings

log = logging.getLogger(__name__)

# These lists contain all the actions in FileDiff, except for the actions generated for each filter.
# Those lists are verified by _verify_action_lists()

FWD_TO_ACTIVE_ACTIONS = [
    'add-sync-point',
    'remove-sync-point',
    'clear-sync-point',
    'copy',
    'copy-full-path',
    'cut',
    'file-push-left',
    'file-push-right',
    'file-pull-left',
    'file-pull-right',
    'file-copy-left-up',
    'file-copy-right-up',
    'file-copy-left-down',
    'file-copy-right-down',
    'file-delete',
    'find',
    'find-next',
    'find-previous',
    'find-replace',
    'format-as-patch',
    'go-to-line',
    'merge-all-left',
    'merge-all-right',
    'merge-all',
    'next-change',
    'next-pane',
    'open-external',
    'open-folder',
    'paste',
    'previous-change',
    'previous-pane',
    'redo',
    'undo',
]

FWD_TO_DIFF2_ACTIONS = [
    'file-previous-conflict',
    'file-next-conflict',
    'lock-scrolling',
    'show-overview-map',
    'text-filter',
    'wrap-mode-bool',
]

FWD_TO_ALL_ACTIONS = [
    'refresh',
    'revert',
    'save',
    'save-all',
]

DISABLED_ACTIONS = [
    # save-as is disabled since we don't want filenames to change
    'save-as',
    # swap-2-panes is disabled since reversing all panes would require more work, and I
    # currently don't see why it should be useful.
    'swap-2-panes',
]


def _get_actions(action_group: Gtk.ActionGroup) -> dict[str, bool]:
    """
    Get the names of all actions in an ActionGroup.
    For each, return whether it's stateful.
    Assert that for all stateful actions, their type is bool.
    """
    action_names = action_group.list_actions()
    r: dict[str, bool] = {}
    for action_name in action_names:
        state = action_group.get_action_state(action_name)
        is_stateful = state is not None
        if is_stateful:
            assert state.get_type_string() == 'b'
        r[action_name] = is_stateful
    return r


def _verify_actions(actions: dict[str, bool]):
    """
    Assert that the action lists cover all the expected actions,
    and that only actions that are forwarded to diff2 are stateful.
    """
    assert TEXT_FILTER_ACTION_FORMAT.endswith('{}')
    text_filter_action_prefix = TEXT_FILTER_ACTION_FORMAT[:-2]
    actions = {k: v for k, v in actions.items() if not k.startswith(text_filter_action_prefix)}

    expected_actions = FWD_TO_ACTIVE_ACTIONS + FWD_TO_DIFF2_ACTIONS + FWD_TO_ALL_ACTIONS + DISABLED_ACTIONS
    assert set(expected_actions) == set(actions)
    may_be_stateful_actions = set(FWD_TO_DIFF2_ACTIONS)
    assert all(action in may_be_stateful_actions for action, is_stateful in actions.items() if is_stateful)


class ShrinkingBin(Gtk.Bin):
    """
    A bin which reports its preferred width to be the minimum width of its child
    """
    def do_get_preferred_width(self):
        child = self.get_child()
        if not child or not child.get_visible():
            return
        min_width, _natural_width = child.get_preferred_width()
        return (min_width, min_width)


class ExactSizeBin(Gtk.Bin):
    """
    A bin which allocates its exact size request to its child
    """
    def do_get_preferred_width(self):
        req_width, _req_height = self.get_size_request()
        return req_width if req_width != -1 else Gtk.Bin.do_get_preferred_width(self)

    def do_get_preferred_height(self):
        _req_width, req_height = self.get_size_request()
        return req_height if req_height != -1 else Gtk.Bin.do_get_preferred_height(self)

    def do_size_allocate(self, alloc: Gdk.Rectangle):
        Gtk.Bin.do_size_allocate(self, alloc)

        child = self.get_child()
        if not child or not child.get_visible():
            return

        req_width, req_height = self.get_size_request()
        child_alloc = Gdk.Rectangle()
        child_alloc.x = alloc.x
        child_alloc.y = alloc.y
        child_alloc.width = req_width if req_width != -1 else alloc.width
        child_alloc.height = req_height if req_height != -1 else alloc.height
        child.size_allocate(child_alloc)
        child.set_clip(alloc)


def wrap_widget_with(widget, container):
    """Wrap widget inside container, preserving its position in a Gtk.Box"""
    box = widget.get_parent()
    assert isinstance(box, Gtk.Box)
    # There's no direct way to query the position of widget in box.
    # In our case, it's the last one. So just assert it.
    assert box.get_children()[-1] is widget
    expand, fill, padding, pack_type = box.query_child_packing(widget)
    assert pack_type == Gtk.PackType.START
    box.remove(widget)
    container.add(widget)
    box.pack_start(container, expand=expand, fill=fill, padding=padding)


class FourDiff(Gtk.Overlay, MeldDoc):
    """
    Four way comparison of text files

    There are 4 files: 0: BASE, 1: REMOTE, 2: LOCAL, 3: RESULT
    Only the RESULT buffer is editable.
    LOCAL has the local file, before applying the diff.
    The user aims to apply the diff between BASE and REMOTE onto LOCAL.
    Or: RESULT - LOCAL = REMOTE - BASE
    Or: RESULT = LOCAL + (REMOTE - BASE)

    Sometimes it's easier to apply the diff between BASE and LOCAL onto REMOTE.
    Or: RESULT = REMOTE + (LOCAL - BASE)
    So it's possible to swap REMOTE and LOCAL.

    The FourDiff doc contains 3 FileDiffs:
    0: BASE-REMOTE  1: BASE-LOCAL  2: LOCAL-RESULT
    There are 2 views. At any time, either:
    1: the BASE-REMOTE and LOCAL-RESULT diffs are displayed, showing the
       source diff and the result diff, or:
    2: the BASE-LOCAL diff is displayed, showing the source of conflicts.

    The two BASE panes scrolling are kept in sync, and so are the two LOCAL
    panes. This causes all panes to be kept in sync.
    """

    __gtype_name__ = "FourDiff"

    close_signal = MeldDoc.close_signal
    create_diff_signal = MeldDoc.create_diff_signal
    file_changed_signal = MeldDoc.file_changed_signal
    label_changed = MeldDoc.label_changed
    move_diff = MeldDoc.move_diff
    tab_state_changed = MeldDoc.tab_state_changed

    # This property is used just to sync the highlighting between all filediffs.
    source_language = GObject.Property(
        type=GtkSource.Language,
        nick="The GtkSourceLanguage of the sourceviews",
        default=None,
    )

    def __init__(self):
        super().__init__()
        # FIXME:
        # See FileDiff.__init__, which calls this an "unimaginable hack".
        # I don't really understand the issue. It mentions Gtk.Template, which we
        # don't inherit from, so perhaps this could be fixed here.
        MeldDoc.__init__(self)
        bind_settings(self)

        # Init diff0, diff1, and diff2
        self.diff0 = FileDiff(2)
        self.diff0.scrolledwindow0.connect('size-allocate', self.on_diff0_scrolledwindow0_size_allocate)
        self.scheduler.add_scheduler(self.diff0.scheduler)

        self.diff1 = FileDiff(2)
        self.diff1.connect('size-allocate', self.on_diff1_size_allocate)
        self.exact0 = ExactSizeBin()
        self.exact0.show()
        wrap_widget_with(self.diff1.scrolledwindow0, self.exact0)
        self.exact1 = ExactSizeBin()
        self.exact1.show()
        wrap_widget_with(self.diff1.scrolledwindow1, self.exact1)
        self.scheduler.add_scheduler(self.diff1.scheduler)

        self.diff2 = FileDiff(2, mark_pane1_conflict_markers=True)
        self.diff2.statusbar0.show_shared_widgets = False
        self.diff2.scrolledwindow0.connect('size-allocate', self.on_diff2_scrolledwindow0_size_allocate)
        self.scheduler.add_scheduler(self.diff2.scheduler)
        self.undosequence = self.diff2.undosequence

        self.diffs = [self.diff0, self.diff1, self.diff2]

        # We use an Overlay instead of a Stack, because a Stack only layouts a
        # page when it's shown, which causes the views to scroll unpredictably.
        # Instead, we use an Overlay, and control which widget is on top.
        # The widgets in the overlay are:
        # 1. self.hbox, containing diff0 and diff2
        # 2. self.diff1
        # 3. self.cover, which is always below diff1, just to hide hbox.
        self.hbox = Gtk.Box(Gtk.Orientation.HORIZONTAL)
        self.hbox.show()
        self.hbox.set_homogeneous(True)
        self.hbox.pack_start(self.diff0, expand=True, fill=True, padding=0)
        self.hbox.pack_start(self.diff2, expand=True, fill=True, padding=0)
        self.hbox.connect('size-allocate', self.on_hbox_size_allocate)
        self.add_overlay(self.hbox)

        # self.cover is shown beneath diff1, to hide hbox0.
        # The "background" style causes it to be opaque rather than transparent.
        self.cover = Gtk.Box()
        self.cover.show()
        self.cover.get_style_context().add_class('background')
        self.add_overlay(self.cover)

        # We put diff1 inside ShrinkingBin, so it will only get its minimum width
        self.shrinking_bin = ShrinkingBin()
        self.shrinking_bin.show()
        self.shrinking_bin.add(self.diff1)
        self.shrinking_bin.set_halign(Gtk.Align.START)
        self.add_overlay(self.shrinking_bin)

        # We always have an active FileDiff, which is self.diffs[self.active_diff_i].
        # When Showing 1 FileDiff, it is the active diff. When showing 2 FileDiffs, it's the one which last
        # received focus.
        self.active_diff_i = 2
        self.active_diff = self.diffs[self.active_diff_i]
        # Start with showing 2 diffs
        self.reorder_overlay(self.hbox, -1)
        self.is_showing_2_diffs = True
        self.active_diff_i_when_showing_2_diffs = 2

        for diff_i in [0, 2]:
            for tv in self.diffs[diff_i].textview:
                tv.connect('focus-in-event', self.on_textview_focus_in_event, diff_i)

        for diff in self.diffs:
            diff.connect('label-changed', self.on_diff_label_changed)
            self.bind_property(
                'source-language', diff, 'source-language',
                GObject.BindingFlags.BIDIRECTIONAL)

        meld_settings = get_meld_settings()
        self.settings_handlers = [
            meld_settings.connect(
                "text-filters-changed", self.on_text_filters_changed)
        ]
        self.create_text_filters()
        text_filter_action = Gio.SimpleAction.new_stateful("text-filter", None, GLib.Variant.new_boolean(False))
        self.view_action_group.add_action(text_filter_action)

        self._init_actions()

        self.show()

        self.files = None

        self.connect_scrolledwindows()

    def _init_actions(self):
        """
        Create actions to forward to the FileDiffs.
        Most actions are forwarded to the active FileDiff, some are forwarded to all.
        """
        actions = _get_actions(self.diff0.view_action_group)
        for diff in self.diffs:
            assert _get_actions(diff.view_action_group) == actions
        _verify_actions(actions)

        my_actions = [
            ('fourdiff-toggle-view', self.action_toggle_view),
            ('fourdiff-swap-remote-and-local', self.action_swap_remote_and_local),
        ]
        for name, callback in my_actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.view_action_group.add_action(action)

        for name in FWD_TO_ACTIVE_ACTIONS:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', self.on_fwd_to_active_action_activate)
            self.view_action_group.add_action(action)

        for name in FWD_TO_DIFF2_ACTIONS:
            action = self.diff2.view_action_group.lookup(name)
            self.view_action_group.add_action(action)

        for name in FWD_TO_ALL_ACTIONS:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', self.on_fwd_to_all_action_activate)
            self.view_action_group.add_action(action)

        for diff_i, diff in enumerate(self.diffs):
            diff.view_action_group.connect('action-enabled-changed', self.on_diff_action_enabled_changed, diff_i)

        self.toolbar_actions = self.diff2.toolbar_actions
        builder = self.diff2.toolbar_actions_builder
        builder.get_object('fourdiff_swap_remote_and_local_button').set_visible(True)
        builder.get_object('fourdiff_toggle_view_button').set_visible(True)

    def on_diff0_scrolledwindow0_size_allocate(self, _widget, allocation):
        # Make diff1.scrolledwindow0 get the same size as diff0.scrolledwindow0
        self.exact0.set_size_request(allocation.width, -1)

    def on_diff2_scrolledwindow0_size_allocate(self, _widget, allocation):
        # Make diff1.scrolledwindow1 get the same size as diff2.scrolledwindow0
        self.exact1.set_size_request(allocation.width, -1)

    def set_diff1_linkmap0_width_request(self):
        # Set diff1.linkmap0 width request so that diff1.scrolledwindow1 will be in the same position as
        # diff2.scrolledwindow0.
        # There is one widget between diff1.linkmap0 and diff1.scrolledwindow1, which is diff1.actiongutter1.
        # So we subtract its width from the requested width of diff1.linkmap0.
        xy_or_none = self.diff2.scrolledwindow0.translate_coordinates(self.diff1.linkmap0, 0, 0)
        if xy_or_none is None:
            # If the widgets weren't realized yet, do nothing.
            return
        x_dist, _y_dist = xy_or_none
        ag1_width = self.diff1.actiongutter1.get_size_request().width
        self.diff1.linkmap0.set_size_request(x_dist - ag1_width, -1)

    def on_hbox_size_allocate(self, _widget, _allocation):
        self.set_diff1_linkmap0_width_request()

    def on_diff1_size_allocate(self, _widget, _allocation):
        self.set_diff1_linkmap0_width_request()

    def on_fwd_to_active_action_activate(self, action, user_data):
        self.active_diff.view_action_group.activate_action(action.get_name(), user_data)

    def on_fwd_to_all_action_activate(self, action, user_data):
        for diff in self.diffs:
            diff.view_action_group.activate_action(action.get_name(), user_data)

    def on_diff_action_enabled_changed(self, _action_group, name, enabled, diff_i):
        relevant_diff_i = 2 if name in FWD_TO_DIFF2_ACTIONS else self.active_diff_i
        if diff_i == relevant_diff_i:
            self.view_action_group.lookup(name).set_enabled(enabled)

    def on_property_action_change_state(self, paction, _param_spec):
        for diff in self.diffs:
            diff.view_action_group.change_action_state(paction.props.name, paction.props.state)

    def on_action_change_state(self, action, state):
        for diff in self.diffs:
            diff.view_action_group.change_action_state(action.get_name(), state)

    def _update_active_diff(self):
        """
        Update self.active_diff_i based on self.active_diff_i_when_showing_2_diffs and self.is_showing_2_diffs.
        If changed, send signals and update actions accordingly.
        """
        active_diff_i = self.active_diff_i_when_showing_2_diffs if self.is_showing_2_diffs else 1
        if active_diff_i != self.active_diff_i:
            self.active_diff_i = active_diff_i
            self.active_diff = self.diffs[active_diff_i]

            diff_view_action_group = self.active_diff.view_action_group
            for name in FWD_TO_ACTIVE_ACTIONS:
                self.view_action_group.lookup(name).set_enabled(diff_view_action_group.lookup(name).get_enabled())

    def on_textview_focus_in_event(self, _textbuffer, _event, diff_i):
        self.active_diff_i_when_showing_2_diffs = diff_i
        self._update_active_diff()

    @staticmethod
    def _set_read_only(diff, panes):
        # A helper function for set_files()
        for pane in panes:
            buf = diff.textbuffer[pane]
            buf.data.force_read_only = True
            diff.update_buffer_writable(buf)

    def set_files(self, files):
        """Load the given files"""
        assert len(files) == 4
        self.files = files
        self.diff0.set_files(files[:2])
        self._set_read_only(self.diff0, [0, 1])
        self.diff1.set_files([files[0], files[2]])
        self._set_read_only(self.diff1, [0, 1])
        self.diff2.set_files(files[2:])
        self._set_read_only(self.diff2, [0])

        self.recompute_label()

    def recompute_label(self):
        buffers = self.diff0.textbuffer[:2] + self.diff2.textbuffer[:2]
        filenames = [b.data.label for b in buffers]
        shortnames = misc.shorten_names(*filenames)

        if buffers[3].get_modified():
            shortnames[3] += "*"

        label_text = " — ".join(shortnames)
        tooltip_names = filenames
        tooltip_text = "\n".join((_("File comparison:"), *tooltip_names))
        self.label_changed.emit(label_text, tooltip_text)

    def on_diff_label_changed(self, _diff, _label_text, _tooltip_text):
        self.recompute_label()

    def get_comparison(self):
        buffers = self.diff0.textbuffer[:2] + self.diff2.textbuffer[:2]
        uris = [b.data.gfile for b in buffers]
        return RecentType.FourDiff, uris

    @staticmethod
    def _on_adj_changed(me, other):
        # A helper function for connect_scrolledwindows()
        v = me.get_value()
        if other.get_value() != v:
            other.set_value(v)

    def connect_scrolledwindows(self):
        sws = [self.diff0.scrolledwindow[0], self.diff1.scrolledwindow[0],
               self.diff1.scrolledwindow[1], self.diff2.scrolledwindow[0]]
        vadjs = [sw.get_vadjustment() for sw in sws]
        hadjs = [sw.get_hadjustment() for sw in sws]

        def connect(adj0, adj1):
            adj0.connect("value-changed", self._on_adj_changed, adj1)
            adj1.connect("value-changed", self._on_adj_changed, adj0)
        connect(vadjs[0], vadjs[1])
        connect(hadjs[0], hadjs[1])
        connect(vadjs[2], vadjs[3])
        connect(hadjs[2], hadjs[3])

    def action_toggle_view(self, _action, _value):
        self.is_showing_2_diffs = not self.is_showing_2_diffs
        if self.is_showing_2_diffs:
            self.reorder_overlay(self.hbox, -1)
        else:
            self.reorder_overlay(self.cover, -1)
            self.reorder_overlay(self.shrinking_bin, -1)
        self._update_active_diff()

    def action_swap_remote_and_local(self, _action, _value):
        assert self.files is not None
        _base, remote, local, _result = self.files
        self.files[1] = local
        self.files[2] = remote
        self.diff0.set_file(1, local)
        self.diff1.set_file(1, remote)
        self.diff2.set_file(0, remote)

        self.recompute_label()

    def get_filter_visibility(self) -> tuple[bool, bool, bool]:
        # The same as FileDiff
        return True, False, False

    def get_conflict_visibility(self) -> bool:
        return True

    def on_text_filters_changed(self, app):
        self.create_text_filters()

    def _update_text_filter(self, action, state):
        for diff in self.diffs:
            diff.view_action_group.change_action_state(action.get_name(), state)
        action.set_state(state)

    def create_text_filters(self):
        # Based on FileDiff.create_text_filters()
        meld_settings = get_meld_settings()
        for i, filt in enumerate(meld_settings.text_filters):
            action = Gio.SimpleAction.new_stateful(
                name=TEXT_FILTER_ACTION_FORMAT.format(i),
                parameter_type=None,
                state=GLib.Variant.new_boolean(filt.active),
            )
            action.connect('change-state', self._update_text_filter)
            action.set_enabled(filt.filter is not None)
            self.view_action_group.add_action(action)

    def on_delete_event(self):
        buf = self.diff2.textbuffer[1]
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(),
                            include_hidden_chars=True)
        if '<<<<<<<' in text or '>>>>>>>>' in text:
            response = misc.modal_dialog(
                primary=_("Close with conflict markers?"),
                secondary=_("There are conflict markers remaining. Are you sure you want to close?"),
                buttons=[
                    (_("_Cancel"), Gtk.ResponseType.CANCEL, None),
                    (_("Close with conflict markers"), Gtk.ResponseType.OK, Gtk.STYLE_CLASS_WARNING),
                ],
                messagetype=Gtk.MessageType.WARNING,
            )
            if response != Gtk.ResponseType.OK:
                return Gtk.ResponseType.CANCEL

        # We start with diff 2, since it contains the editable buffer and
        # the user may decide to abort closing
        response = self.diff2.on_delete_event()
        if response == Gtk.ResponseType.CANCEL:
            return response

        for diff in self.diffs[:2]:
            response = diff.on_delete_event()
            assert response == Gtk.ResponseType.OK

        meld_settings = get_meld_settings()
        for h in self.settings_handlers:
            meld_settings.disconnect(h)

        self.emit('close', 0)
        return Gtk.ResponseType.OK
