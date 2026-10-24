"""Reusable keyboard and text selectors for terminal lists."""
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .localization import tr
T = TypeVar("T")


def prompt_session() -> Any | None:
    """Create a prompt that turns navigation keys into selector actions."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.key_binding import KeyBindings
    except ImportError:
        return None

    bindings = KeyBindings()

    @bindings.add("pagedown")
    def next_page(event: Any) -> None:
        event.app.exit(result="next")

    @bindings.add("pageup")
    def previous_page(event: Any) -> None:
        event.app.exit(result="prev")

    @bindings.add("down")
    def move_down(event: Any) -> None:
        event.app.exit(result="move-down")

    @bindings.add("up")
    def move_up(event: Any) -> None:
        event.app.exit(result="move-up")

    @bindings.add("escape")
    def return_to_menu(event: Any) -> None:
        event.app.exit(result="back")

    return PromptSession(key_bindings=bindings)


def select_item(items: Sequence[T], *, title: str, columns: Sequence[str],
                render: Callable[[T], Sequence[str]], console: Console,
                prompt: str | None = None, page_size: int = 18) -> T | None:
    """Select an item with arrows, paging, and search, with a numbered fallback."""
    if prompt is None:
        prompt = tr('tui_selection.select')
    if page_size < 1:
        raise ValueError("page_size must be positive")

    entries: list[tuple[T, tuple[str, ...]]] = []
    for item in items:
        values = tuple(str(value) for value in render(item))
        if len(values) != len(columns):
            raise ValueError(tr('tui_selection.each_list_item_must_provide_the_same_number_of_display_values_as_table_columns'))
        entries.append((item, values))

    session = prompt_session()
    search = ""
    page = 0
    selected_index = 0
    notice = ""

    while True:
        if console.is_terminal:
            console.clear()

        visible = [entry for entry in entries
                   if search.casefold() in " ".join(entry[1]).casefold()]
        page_count = max(1, (len(visible) + page_size - 1) // page_size)
        page = min(page, page_count - 1)
        start = page * page_size
        page_entries = visible[start:start + page_size]
        if page_entries:
            selected_index = min(selected_index, len(page_entries) - 1)

        table = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold cyan")
        table.add_column("", no_wrap=True)
        table.add_column(tr('tui_selection.no'), justify="right", style="dim", no_wrap=True)
        for column in columns:
            table.add_column(column)
        for index, (_, values) in enumerate(page_entries, 1):
            marker = (Text("›", style="bold green")
                      if session is not None and index - 1 == selected_index else Text(""))
            table.add_row(marker, Text(str(index)), *(Text(value) for value in values))
        console.print(table)
        console.print(
            tr('tui_selection.page_items', v_a=page + 1, v_b=page_count, v_c=len(visible), v_d=tr('tui_selection.search', v_a=search) if search else ''))
        if notice:
            console.print(f"[yellow]{notice}[/yellow]")
            notice = ""
        if session is not None:
            console.print(tr('tui_selection.select_enter_confirm_pageup_pagedown_change_page_keyword_search_esc_back'))
        else:
            console.print(tr('tui_selection.enter_a_number_and_press_enter_to_confirm_n_p_change_page_keyword_search_enter_back'))

        if session is None:
            choice = input(prompt).strip()
        else:
            choice = session.prompt(prompt).strip()
        lowered = choice.casefold()

        if lowered == "back" or (not choice and session is None):
            return None
        if not choice:
            if page_entries:
                return page_entries[selected_index][0]
            notice = tr('tui_selection.no_matching_items')
            continue
        if lowered == "move-down":
            if selected_index + 1 < len(page_entries):
                selected_index += 1
            elif page + 1 < page_count:
                page += 1
                selected_index = 0
            else:
                notice = tr('tui_selection.this_is_the_last_item')
            continue
        if lowered == "move-up":
            if selected_index > 0:
                selected_index -= 1
            elif page > 0:
                page -= 1
                selected_index = page_size - 1
            else:
                notice = tr('tui_selection.this_is_the_first_item')
            continue
        if lowered in ("n", "next"):
            if page + 1 < page_count:
                page += 1
                selected_index = 0
            else:
                notice = tr('tui_selection.this_is_the_last_page')
            continue
        if lowered in ("p", "prev"):
            if page > 0:
                page -= 1
                selected_index = 0
            else:
                notice = tr('tui_selection.this_is_the_first_page')
            continue
        if lowered.startswith("/"):
            search = choice[1:].strip()
            page = 0
            selected_index = 0
            continue
        if lowered == "all":
            search = ""
            page = 0
            selected_index = 0
            continue
        if choice.isdigit():
            if 1 <= int(choice) <= len(page_entries):
                return page_entries[int(choice) - 1][0]
            notice = tr('tui_selection.invalid_number_enter_a_number_shown_on_this_page')
            continue

        matches = [item for item, values in visible
                   if choice.casefold() in " ".join(values).casefold()]
        if len(matches) == 1:
            return matches[0]
        notice = tr('tui_selection.enter_a_number_or_search_with_keyword')
