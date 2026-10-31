"""Bindings are disabled during numeric entry, except cancel and emergency quit."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent

if TYPE_CHECKING:
    from .viewer import Viewer


def create_bindings(viewer: "Viewer") -> KeyBindings:
    bindings = KeyBindings()
    idle = Condition(lambda: viewer.editing is None)
    browsing = Condition(lambda: viewer.editing is None and not viewer.selecting)
    selecting = Condition(lambda: viewer.editing is None and viewer.selecting)
    rectangle_selecting = Condition(lambda: viewer.editing is None and viewer.selecting
                                    and viewer.clipping.selection is not None
                                    and viewer.clipping.selection.kind == "rectangle")
    polygon_selecting = Condition(lambda: viewer.editing is None and viewer.selecting
                                  and viewer.clipping.selection is not None
                                  and viewer.clipping.selection.kind == "polygon")

    channel_focus = browsing & Condition(lambda: viewer.panel_visible
                    and viewer.application.layout.has_focus(viewer.channel_control))

    @bindings.add("c-q", eager=True)
    def quit_always(event: KeyPressEvent) -> None:
        event.app.exit()

    @bindings.add("c-c", eager=True)
    def interrupt(event: KeyPressEvent) -> None:
        if viewer.editing is not None:
            viewer.cancel_edit()
        elif viewer.selecting:
            viewer.clipping.submit()
        else:
            event.app.exit()

    @bindings.add("q", filter=idle)
    def quit_viewer(event: KeyPressEvent) -> None:
        event.app.exit()

    @bindings.add("escape", eager=True)
    def cancel(event: KeyPressEvent) -> None:
        if viewer.editing is not None:
            viewer.cancel_edit()
        elif viewer.selecting:
            viewer.clipping.end()
        elif viewer.histogram_mode:
            viewer.toggle_histogram()
        elif viewer.image_only:
            viewer.toggle_fullscreen(enable=False)
        else:
            viewer.cancel_edit()

    @bindings.add("c", filter=browsing)
    def panel(event: KeyPressEvent) -> None:
        viewer.panel_requested = not viewer.panel_requested
        event.app.layout.focus(viewer.canvas)
        event.app.invalidate()

    @bindings.add("f", filter=browsing)
    def fullscreen(event: KeyPressEvent) -> None:
        viewer.toggle_fullscreen()

    @bindings.add("tab", filter=browsing)
    def focus(event: KeyPressEvent) -> None:
        if viewer.panel_visible:
            target = (viewer.canvas if event.app.layout.has_focus(viewer.channel_control)
                      else viewer.channel_control)
            event.app.layout.focus(target)

    @bindings.add("+", filter=browsing)
    @bindings.add("=", filter=browsing)
    def zoom_in(event: KeyPressEvent) -> None:
        viewer.zoom(1.25)

    @bindings.add("-", filter=browsing)
    def zoom_out(event: KeyPressEvent) -> None:
        viewer.zoom(1 / 1.25)

    @bindings.add("pageup", filter=browsing & ~channel_focus)
    @bindings.add("[", filter=browsing)
    def previous_item(event: KeyPressEvent) -> None:
        viewer.step_destination(-1)

    @bindings.add("pagedown", filter=browsing & ~channel_focus)
    @bindings.add("]", filter=browsing)
    def next_item(event: KeyPressEvent) -> None:
        viewer.step_destination(1)

    @bindings.add("pageup", filter=channel_focus)
    def channel_page_up(event):
        viewer.focus_channel(-viewer.channel_control.visible_channels)

    @bindings.add("pagedown", filter=channel_focus)
    def channel_page_down(event):
        viewer.focus_channel(viewer.channel_control.visible_channels)

    @bindings.add("home", filter=channel_focus)
    def channel_first(event):
        viewer.focus_channel(-len(viewer.windows))

    @bindings.add("end", filter=channel_focus)
    def channel_last(event):
        viewer.focus_channel(len(viewer.windows))

    @bindings.add("enter", filter=channel_focus)
    def channel_solo(event):
        viewer.select_one(viewer.focused_channel)

    @bindings.add("d", filter=browsing)
    def dimension(event: KeyPressEvent) -> None:
        if viewer.navigation is not None:
            viewer.navigation.cycle_axis()

    @bindings.add("p", filter=browsing)
    def destination(event: KeyPressEvent) -> None:
        viewer.begin_destination()

    @bindings.add("home", filter=browsing & ~channel_focus)
    @bindings.add("r", filter=browsing)
    def fit(event: KeyPressEvent) -> None:
        viewer.fit_full()

    def arrow(dx: int, dy: int) -> Callable[[KeyPressEvent], None]:
        def move(event: KeyPressEvent) -> None:
            if event.app.layout.has_focus(viewer.channel_control) and dy:
                viewer.focus_channel(dy)
            else:
                viewer.pan_cells(dx * max(1, viewer.canvas_size[0] // 8),
                                 dy * max(1, viewer.canvas_size[1] // 8))
        return move

    for key, delta in (("left", (-1, 0)), ("right", (1, 0)),
                       ("up", (0, -1)), ("down", (0, 1))):
        bindings.add(key, filter=browsing)(arrow(*delta))

    @bindings.add(",", filter=browsing)
    def previous_channel(event: KeyPressEvent) -> None:
        viewer.focus_channel(-1)

    @bindings.add(".", filter=browsing)
    def next_channel(event: KeyPressEvent) -> None:
        viewer.focus_channel(1)

    @bindings.add(" ", filter=browsing)
    def toggle_channel(event: KeyPressEvent) -> None:
        viewer.toggle_channel()

    def select(index: int) -> Callable[[KeyPressEvent], None]:
        def select_one(event: KeyPressEvent) -> None:
            viewer.select_one(index)
        return select_one

    for number in range(1, 10):
        bindings.add(str(number), filter=browsing)(select(number - 1))

    def edit(field: str) -> Callable[[KeyPressEvent], None]:
        def begin_edit(event: KeyPressEvent) -> None:
            viewer.begin_edit(field)
        return begin_edit

    for key, field in (("l", "lower"), ("u", "upper"), ("g", "gamma"), ("h", "color")):
        bindings.add(key, filter=browsing)(edit(field))

    @bindings.add("H", filter=browsing)
    def histogram(event):
        viewer.toggle_histogram()

    @bindings.add("A", filter=browsing)
    def stack_auto(event):
        viewer.stack_auto_window()

    @bindings.add("L", filter=browsing)
    def histogram_scale(event):
        if viewer.histogram_mode:
            viewer.contrast.log_counts = not viewer.contrast.log_counts
            event.app.invalidate()

    @bindings.add("a", filter=browsing)
    def auto(event: KeyPressEvent) -> None:
        viewer.auto_window()

    @bindings.add("i", filter=browsing)
    def invert(event: KeyPressEvent) -> None:
        viewer.change_renderer(invert=not viewer.renderer.invert)

    @bindings.add("t", filter=browsing)
    def color(event: KeyPressEvent) -> None:
        viewer.toggle_color()

    @bindings.add("m", filter=idle)
    def mode(event: KeyPressEvent) -> None:
        if viewer.selecting:
            viewer.clipping.cycle_preview("color")
        else:
            viewer.cycle_mode()

    @bindings.add("b", filter=browsing)
    def blocks(event: KeyPressEvent) -> None:
        viewer.toggle_blocks()

    @bindings.add("?", filter=browsing)
    def help_message(event: KeyPressEvent) -> None:
        viewer.show_help = not viewer.show_help
        event.app.invalidate()

    @bindings.add("s", filter=idle)
    def selection_mode(event: KeyPressEvent) -> None:
        viewer.clipping.toggle("rectangle")

    @bindings.add("v", filter=idle)
    def polygon_mode(event: KeyPressEvent) -> None:
        viewer.clipping.start_polygon()

    def selection_move(dx, dy, extend=False):
        def move(event):
            viewer.clipping.move(dx, dy, extend=extend)
        return move

    for key, (dx, dy) in (("left", (-1, 0)), ("right", (1, 0)),
                          ("up", (0, -1)), ("down", (0, 1))):
        bindings.add(key, filter=selecting)(selection_move(dx, dy))
        bindings.add("s-" + key, filter=selecting)(selection_move(dx, dy, True))

    @bindings.add(" ", filter=selecting)
    def mark_corner(event):
        viewer.clipping.mark()

    @bindings.add("tab", filter=selecting)
    def swap_corner(event):
        viewer.clipping.swap_corner()

    def edge(end=False, extend=False):
        def move(event):
            viewer.clipping.edge(end=end, extend=extend)
        return move

    for key, last in (("home", False), ("end", True)):
        bindings.add(key, filter=selecting)(edge(last))
        bindings.add("s-" + key, filter=selecting)(edge(last, True))

    @bindings.add("enter", filter=selecting)
    def selection_enter(event):
        viewer.clipping.enter()

    @bindings.add("a", filter=selecting)
    def add_area(event):
        viewer.clipping.add_area()

    @bindings.add("[", filter=selecting)
    @bindings.add("pageup", filter=selecting)
    def previous_area(event):
        viewer.clipping.cycle_area(-1)

    @bindings.add("]", filter=selecting)
    @bindings.add("pagedown", filter=selecting)
    def following_area(event):
        viewer.clipping.cycle_area(1)

    @bindings.add("delete", filter=selecting)
    def remove_area(event):
        viewer.clipping.remove_area()

    @bindings.add("M", filter=idle)
    def plain_ascii(event):
        if viewer.selecting:
            viewer.clipping.cycle_preview("ascii")
        else:
            viewer.cycle_ascii()

    @bindings.add("n", filter=selecting)
    def name_geojson(event):
        viewer.clipping.begin_name()

    @bindings.add("y", filter=selecting)
    def copy_text(event):
        viewer.clipping.submit()

    @bindings.add("Y", filter=selecting)
    def save_text(event):
        viewer.clipping.save()

    @bindings.add("i", filter=selecting)
    def copy_png(event):
        viewer.clipping.submit_image()

    @bindings.add("I", filter=selecting)
    def save_png(event):
        viewer.clipping.save(image=True)

    @bindings.add("t", filter=selecting)
    def copy_ansi(event):
        viewer.clipping.submit(ansi=True)

    @bindings.add("T", filter=selecting)
    def save_ansi(event):
        viewer.clipping.save(ansi=True)

    @bindings.add("j", filter=selecting)
    def copy_geojson(event):
        viewer.clipping.submit_geojson()

    @bindings.add("J", filter=selecting)
    def save_geojson(event):
        viewer.clipping.save(geojson=True)

    @bindings.add("s", filter=rectangle_selecting)
    @bindings.add("v", filter=polygon_selecting)
    def close_selection(event):
        viewer.clipping.end()

    return bindings
