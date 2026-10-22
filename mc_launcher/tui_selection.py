"""Reusable keyboard and text selectors for terminal lists."""
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

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
                prompt: str = "选择 > ", page_size: int = 18) -> T | None:
    """Select an item with arrows, paging, and search, with a numbered fallback."""
    if page_size < 1:
        raise ValueError("page_size must be positive")

    entries: list[tuple[T, tuple[str, ...]]] = []
    for item in items:
        values = tuple(str(value) for value in render(item))
        if len(values) != len(columns):
            raise ValueError("每个列表项必须提供与表格列数相同的显示值。")
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
        table.add_column("编号", justify="right", style="dim", no_wrap=True)
        for column in columns:
            table.add_column(column)
        for index, (_, values) in enumerate(page_entries, 1):
            marker = (Text("›", style="bold green")
                      if session is not None and index - 1 == selected_index else Text(""))
            table.add_row(marker, Text(str(index)), *(Text(value) for value in values))
        console.print(table)
        console.print(
            f"第 {page + 1}/{page_count} 页 · 共 {len(visible)} 项"
            + (f" · 搜索：{search}" if search else ""))
        if notice:
            console.print(f"[yellow]{notice}[/yellow]")
            notice = ""
        if session is not None:
            console.print("↑/↓ 选择 · Enter 确认 · PageUp/PageDown 翻页 · /关键词 搜索 · Esc 返回")
        else:
            console.print("输入编号并按 Enter 确认 · n/p 翻页 · /关键词 搜索 · Enter 返回")

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
            notice = "当前没有匹配项。"
            continue
        if lowered == "move-down":
            if selected_index + 1 < len(page_entries):
                selected_index += 1
            elif page + 1 < page_count:
                page += 1
                selected_index = 0
            else:
                notice = "已经是最后一项。"
            continue
        if lowered == "move-up":
            if selected_index > 0:
                selected_index -= 1
            elif page > 0:
                page -= 1
                selected_index = page_size - 1
            else:
                notice = "已经是第一项。"
            continue
        if lowered in ("n", "next"):
            if page + 1 < page_count:
                page += 1
                selected_index = 0
            else:
                notice = "已经是最后一页。"
            continue
        if lowered in ("p", "prev"):
            if page > 0:
                page -= 1
                selected_index = 0
            else:
                notice = "已经是第一页。"
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
            notice = "编号无效；请输入当前页显示的编号。"
            continue

        matches = [item for item, values in visible
                   if choice.casefold() in " ".join(values).casefold()]
        if len(matches) == 1:
            return matches[0]
        notice = "输入编号，或使用 /关键词 搜索。"
