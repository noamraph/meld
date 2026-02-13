from gi.repository import GObject, Gtk, GtkSource

from meld.conf import _
from meld.ui.bufferselectors import EncodingSelector


class EncodingExtraWidget(Gtk.Box):
    __gtype_name__ = "FileDialogEncoding"

    encoding = GObject.Property(
        type=GtkSource.Encoding,
        default=GtkSource.Encoding.get_utf8(),
    )

    def __init__(self, with_autodetect: bool):
        super().__init__()

        self.set_spacing(6)

        label = Gtk.Label(label=_("Character Encoding:"))
        label.show()
        self.pack_start(label, expand=False, fill=False, padding=0)

        def change_encoding(selector, encoding):
            self.encoding = encoding
            pop.hide()

        def set_initial_encoding(selector):
            selector.select_value(self.encoding)

        selector = EncodingSelector(with_autodetect)
        selector.connect('encoding-selected', change_encoding)
        selector.connect('map', set_initial_encoding)

        pop = Gtk.Popover()
        pop.set_position(Gtk.PositionType.TOP)
        pop.add(selector)

        self.button = button = Gtk.MenuButton()
        button.show()
        arrow = Gtk.Image.new_from_icon_name('pan-down-symbolic', Gtk.IconSize.SMALL_TOOLBAR)
        arrow.props.valign = Gtk.Align.BASELINE
        button.set_image(arrow)
        button.set_always_show_image(True)
        button.set_image_position(Gtk.PositionType.RIGHT)
        self.bind_property(
            'encoding', button, 'label',
            GObject.BindingFlags.DEFAULT | GObject.BindingFlags.SYNC_CREATE,
            lambda binding, enc: selector.get_value_label(enc))
        button.set_popover(pop)
        button.show()

        self.pack_start(button, expand=False, fill=False, padding=0)
