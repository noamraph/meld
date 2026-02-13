
from typing import Optional

from gi.repository import Gio, GObject, Gtk, GtkSource

from meld.ui.encoding_extra_widget import EncodingExtraWidget


class MeldFileButton(Gtk.Button):
    __gtype_name__ = "MeldFileButton"

    file: Optional[Gio.File] = GObject.Property(
        type=Gio.File,
        nick="Most recently selected file",
    )

    encoding: Optional[GtkSource.Encoding] = GObject.Property(
        type=GtkSource.Encoding,
        nick="The encoding of the most recently selected file. None means autodetect.",
    )

    pane: int = GObject.Property(
        type=int,
        nick="Index of pane associated with this file selector",
        flags=(
            GObject.ParamFlags.READWRITE |
            GObject.ParamFlags.CONSTRUCT_ONLY
        ),
    )

    action: Gtk.FileChooserAction = GObject.Property(
        type=Gtk.FileChooserAction,
        nick="File selector action",
        flags=(
            GObject.ParamFlags.READWRITE |
            GObject.ParamFlags.CONSTRUCT_ONLY
        ),
        default=Gtk.FileChooserAction.OPEN,
    )

    local_only: bool = GObject.Property(
        type=bool,
        nick="Whether selected files should be limited to local file:// URIs",
        flags=(
            GObject.ParamFlags.READWRITE |
            GObject.ParamFlags.CONSTRUCT_ONLY
        ),
        default=True,
    )

    dialog_label: str = GObject.Property(
        type=str,
        nick="Label for the file selector dialog",
        flags=(
            GObject.ParamFlags.READWRITE |
            GObject.ParamFlags.CONSTRUCT_ONLY
        ),
    )

    @GObject.Signal('file-selected')
    def file_selected_signal(self, pane: int, file: Gio.File, encoding: GtkSource.Encoding) -> None:
        ...

    icon_action_map = {
        Gtk.FileChooserAction.OPEN: "document-open-symbolic",
        Gtk.FileChooserAction.SELECT_FOLDER: "folder-open-symbolic",
    }

    def do_realize(self) -> None:
        Gtk.Button.do_realize(self)

        image = Gtk.Image.new_from_icon_name(
            self.icon_action_map[self.action], Gtk.IconSize.BUTTON)
        self.set_image(image)

    def do_clicked(self) -> None:
        dialog = Gtk.FileChooserNative(
            title=self.dialog_label,
            transient_for=self.get_toplevel(),
            action=self.action,
            local_only=self.local_only
        )

        if self.file and self.file.get_path():
            dialog.set_file(self.file)

        if self.action == Gtk.FileChooserAction.OPEN:
            encoding_widget = EncodingExtraWidget(with_autodetect=True)
            encoding_widget.encoding = self.encoding
            dialog.set_extra_widget(encoding_widget)

        response = dialog.run()
        gfile = dialog.get_file()
        dialog.destroy()

        if response != Gtk.ResponseType.ACCEPT or not gfile:
            return

        self.file = gfile

        if self.action == Gtk.FileChooserAction.OPEN:
            self.encoding = encoding_widget.encoding

        self.file_selected_signal.emit(self.pane, self.file, self.encoding)
