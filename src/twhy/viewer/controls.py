"""Terminal controls: cell presentation, selection tools, and mouse navigation."""

from typing import TYPE_CHECKING

from wcwidth import wcwidth

from ..channel_colors import color_hex

from prompt_toolkit.data_structures import Point
from prompt_toolkit.layout.controls import UIContent, UIControl
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType

if TYPE_CHECKING:
    from .viewer import Viewer


def safe_label(text: str) -> str:
    """Keep metadata literal and single-line, excluding terminal control characters."""
    return "".join(character if character.isprintable() else "?" for character in text)


def _padded_label(text: str, width: int) -> str:
    """Fit literal metadata to terminal cells so a right-aligned swatch stays clickable."""
    result, used = [], 0
    for char in safe_label(text):
        size = max(0, wcwidth(char))
        if used + size > width:
            break
        result.append(char)
        used += size
    return "".join(result) + " " * (width - used)


class CanvasControl(UIControl):
    def __init__(self, viewer: "Viewer") -> None:
        self.viewer = viewer
        self._drag: Point | None = None

    def is_focusable(self) -> bool:
        return True

    def create_content(self, width: int, height: int) -> UIContent:
        self.viewer.resize_canvas(width, height)
        selection = self.viewer.clipping.selection
        if selection is not None:
            return UIContent(get_line=selection.row, line_count=max(1, height), show_cursor=False)
        lines = (self.viewer.contrast.content(width, height) if self.viewer.histogram_mode
                 else self.viewer.cell_lines)
        return UIContent(
            get_line=lambda row: lines[row] if row < len(lines) else [],
            line_count=max(1, height), show_cursor=False,
        )

    def mouse_handler(self, event: MouseEvent) -> None:
        viewer = self.viewer
        if viewer.editing is not None:
            return None
        viewer.application.layout.focus(self)
        viewer.clipping.pressed_button = None
        selection = viewer.clipping.selection
        if selection is not None:
            self._drag = None
            x, y = event.position.x, event.position.y
            try:
                if (event.event_type == MouseEventType.MOUSE_DOWN
                        and event.button == MouseButton.LEFT):
                    was_closed = selection.closed
                    selection.start_drag(x, y)
                    if selection.closed and not was_closed:
                        viewer.clipping.notify("Closed | a: add area | y/i/j: copy")
                elif event.event_type == MouseEventType.MOUSE_MOVE:
                    selection.drag(x, y)
                elif event.event_type == MouseEventType.MOUSE_UP:
                    selection.drag(x, y, finish=True)
            except ValueError as error:
                viewer.clipping.notify(str(error))
            viewer.application.invalidate()
            return None
        if viewer.histogram_mode:
            self._drag = None
            viewer.contrast.mouse(event)
            return None
        columns, rows = viewer.canvas_size
        anchor = (min(1.0, max(0.0, (event.position.x + 0.5) / max(1, columns))),
                  min(1.0, max(0.0, (event.position.y + 0.5) / max(1, rows))))
        if event.event_type == MouseEventType.SCROLL_UP:
            viewer.zoom(1.25, anchor=anchor)
        elif event.event_type == MouseEventType.SCROLL_DOWN:
            viewer.zoom(1 / 1.25, anchor=anchor)
        elif event.event_type == MouseEventType.MOUSE_DOWN and event.button == MouseButton.LEFT:
            self._drag = event.position
        elif event.event_type == MouseEventType.MOUSE_UP:
            self._drag = None
        elif (event.event_type == MouseEventType.MOUSE_MOVE
              and event.button == MouseButton.LEFT and self._drag is not None):
            viewer.pan_cells(self._drag.x - event.position.x, self._drag.y - event.position.y)
            self._drag = event.position
        return None


class ChannelControl(UIControl):
    def __init__(self, viewer: "Viewer") -> None:
        self.viewer = viewer
        self.first_channel = 0
        self.visible_channels = 1
        self.channel_row_start = 1
        self.swatch_columns = (0, 0)
        self.color_row: int | None = None

    def is_focusable(self) -> bool:
        return True

    def create_content(self, width: int, height: int) -> UIContent:
        viewer, info = self.viewer, self.viewer.session.info
        self.color_row = None
        self.swatch_columns = (width - 3, width - 1) if width >= 4 else (0, 0)
        if viewer.selecting:
            selection = viewer.clipping.selection
            tool_help = (" Click first / Enter: close" if selection.kind == "polygon" else
                         " Drag / Space+arrows: box")
            hints = [tool_help, " a: add | s/v: switch/exit", " [/]: area | Del: remove",
                     " Tab: corner / undo vertex", " y/Y: text | i/I: PNG",
                     " t/T: ANSI | j/J: GeoJSON", " m: art | M: ASCII", " n: rename | Esc: done"]
            lines = [[("class:panel.title", " SELECTIONS")]]
            lines.extend([[("class:panel", text)] for text in hints[:max(0, height - 2)]])
            capacity = max(0, height - len(lines))
            start = max(0, selection.active_index - capacity + 1)
            for index in range(start, min(len(selection.areas), start + capacity)):
                active = index == selection.active_index
                text = f"{'>' if active else ' '}{index+1} {selection.areas[index].identity.name}"
                lines.append([
                    ("class:panel.selected" if active else "class:panel", safe_label(text))
                ])
            return UIContent(get_line=lambda row: lines[row] if row < len(lines) else [],
                             line_count=len(lines), show_cursor=False)
        count = len(info.channels)
        details_height = min(7, max(0, height // 3))
        self.channel_row_start = 1 if height > 1 else 0
        self.visible_channels = min(count, max(1, height - self.channel_row_start - details_height))
        self.first_channel = min(max(0, self.first_channel), max(0, count-self.visible_channels))
        self.first_channel = min(self.first_channel, viewer.focused_channel)
        self.first_channel = max(self.first_channel,
                                 viewer.focused_channel - self.visible_channels + 1)
        last = min(count, self.first_channel + self.visible_channels)
        header = f" CHANNELS {self.first_channel}-{last-1}/{count}"
        header += (" ^" if self.first_channel else "") + (" v" if last < count else "")
        lines = [[("class:panel.title", header)]] if self.channel_row_start else []
        for index in range(self.first_channel, last):
            focus = ">" if index == viewer.focused_channel else " "
            selected = "x" if index in viewer.selected_channels else " "
            style = "class:panel.selected" if index == viewer.focused_channel else "class:panel"
            label = f"{focus}[{selected}] {index} {safe_label(info.channels[index])}"
            if info.is_rgb or width < 4:
                lines.append([(style, label)])
            else:
                color = color_hex(viewer.channel_colors[index])
                lines.append([(style, _padded_label(label, width - 3)),
                              (f"bg:{color}", "  "), (style, " ")])
        window = viewer.windows[viewer.focused_channel]
        color = color_hex(viewer.channel_colors[viewer.focused_channel])
        color_line = ([("class:panel", " Color: native RGB")] if info.is_rgb else
                      [("class:panel", " h: Color "), (f"bg:{color}", "  "),
                       ("class:panel", f" {color}")])
        details = [
            [("class:panel", f" L:{window.lower:g} U:{window.upper:g}" if window else
              " Limits: auto pending")],
            [("class:panel", f" Gamma:{window.gamma:g}" if window else " Gamma:1")],
            color_line,
            [("class:panel", " l/u/g: edit | a: auto")],
            [("class:panel", " Space: toggle | Enter: solo")],
            [("class:panel", " Wheel/arrows/PgUp/PgDn: move")],
            [("class:panel", " Home/End: first/last")],
        ]
        if not info.is_rgb and len(lines) + 2 < height:
            self.color_row = len(lines) + 2
        lines.extend(details[:max(0, height - len(lines))])
        return UIContent(get_line=lambda row: lines[row] if row < len(lines) else [],
                         line_count=len(lines), show_cursor=False)

    def mouse_handler(self, event: MouseEvent) -> None:
        viewer = self.viewer
        if viewer.editing is not None or viewer.selecting:
            return None
        viewer.application.layout.focus(self)
        if event.event_type == MouseEventType.SCROLL_UP:
            viewer.focus_channel(-1)
        elif event.event_type == MouseEventType.SCROLL_DOWN:
            viewer.focus_channel(1)
        elif event.event_type == MouseEventType.MOUSE_UP and event.button == MouseButton.LEFT:
            if event.position.y == self.color_row:
                viewer.begin_edit("color")
                return None
            row = event.position.y - self.channel_row_start
            index = self.first_channel + row
            if 0 <= row < self.visible_channels and index < len(viewer.windows):
                viewer.focused_channel = index
                left, right = self.swatch_columns
                if not viewer.session.info.is_rgb and left <= event.position.x < right:
                    viewer.begin_edit("color")
                elif viewer.histogram_mode:
                    viewer.contrast.drag = None
                    viewer.contrast.request(index)
                    viewer.application.invalidate()
                else:
                    viewer.toggle_channel()
        return None


def navigation_fragments(viewer: "Viewer") -> list:
    """Clickable, single-line page/series controls; image wheel remains zoom."""
    nav = viewer.navigation
    if nav is None:
        return []

    def previous(event):
        if (viewer.editing is None and not viewer.selecting
                and event.button == MouseButton.LEFT
                and event.event_type == MouseEventType.MOUSE_UP):
            viewer.step_destination(-1)

    def following(event):
        if (viewer.editing is None and not viewer.selecting
                and event.button == MouseButton.LEFT
                and event.event_type == MouseEventType.MOUSE_UP):
            viewer.step_destination(1)

    def jump(event):
        if (viewer.editing is None and not viewer.selecting
                and event.button == MouseButton.LEFT
                and event.event_type == MouseEventType.MOUSE_UP):
            viewer.begin_destination()

    fragments = [("class:status", " [<] ", previous),
                 ("class:status", "[>] ", following),
                 ("class:status", "[p: go] ", jump)]
    if any(axis in ("Z", "T") for axis in nav.axes):
        def choose(axis):
            def clicked(event):
                if (viewer.editing is None and not viewer.selecting
                        and event.button == MouseButton.LEFT
                        and event.event_type == MouseEventType.MOUSE_UP):
                    nav.select_axis(axis)
            return clicked
        for axis in nav.axes:
            label = "Series" if axis == "series" else axis
            if axis in ("Z", "T"):
                info = next(info for info in nav.active.axis_info if info.name == axis)
                position = nav.display_position
                current = position[1] if axis == "Z" else position[2]
                label += f"{'*' if nav.axis == axis else ''} {current}/{info.size - 1}"
            else:
                label = (f"S{'*' if nav.axis == axis else ''} "
                         f"{nav.active.index}/{nav.document.last_index}")
            fragments.append(("class:panel.selected" if nav.axis == axis else "class:status",
                              f"[{label}] ", choose(axis)))
        fragments.append(("class:status", "d:axis"))
    compact = any(axis in ("Z", "T") for axis in nav.axes)
    fragments.append(("class:status", safe_label(nav.status(compact=compact))))
    return fragments



def clip_fragments(viewer: "Viewer") -> list:
    """Clickable selection controls live in the existing footer, costing no canvas row."""
    def button(label, action):
        def clicked(event):
            if viewer.editing is not None or event.button != MouseButton.LEFT:
                return
            if event.event_type == MouseEventType.MOUSE_DOWN:
                viewer.clipping.pressed_button = label
            elif event.event_type == MouseEventType.MOUSE_UP:
                pressed, viewer.clipping.pressed_button = viewer.clipping.pressed_button, None
                # Ending a canvas drag over Copy is not a button click.
                if viewer.clipping.selection is not None:
                    viewer.clipping.selection.dragging = False
                if pressed == label:
                    action()
        return ("class:clip.button", label, clicked)

    clip = viewer.clipping
    if not viewer.selecting:
        return [button(" [s: Select] ", clip.toggle),
                button("[v: Polygon] ", clip.start_polygon),
                button("[f: Full] ", viewer.toggle_fullscreen)]
    # Copy/save keys are individually clickable; each format occupies one short group.
    width = (viewer.application.output.get_size().columns if viewer.application is not None
             and hasattr(viewer.application.output, "get_size") else 100)
    short = width < 76

    def pair(copy_key, save_key, label, copy_action, save_action):
        return [("", "["), button(copy_key, copy_action), ("", "/"),
                button(save_key, save_action), ("", ("" if short else " " + label) + "] ")]

    result = pair("y", "Y", "txt", clip.submit, clip.save)
    result += pair("i", "I", "png", clip.submit_image, lambda: clip.save(image=True))
    result += pair("t", "T", "ansi", lambda: clip.submit(ansi=True), lambda: clip.save(ansi=True))
    result += pair("j", "J", "json", clip.submit_geojson, lambda: clip.save(geojson=True))
    # Keep the toolbar to one compact line even in a 45-column terminal.
    extras = [("[a] ", clip.add_area), ("[n] ", clip.begin_name),
              ("[m] ", lambda: clip.cycle_preview("color")),
              ("[M] ", lambda: clip.cycle_preview("ascii")), ("[Esc]", clip.end)]
    for label, action in extras:
        if sum(len(fragment[1]) for fragment in result) + len(label) <= width:
            result.append(button(label, action))
    return result
