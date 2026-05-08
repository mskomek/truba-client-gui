from __future__ import annotations

from dataclasses import dataclass


_ACS_MAP = {
    "j": "┘",
    "k": "┐",
    "l": "┌",
    "m": "└",
    "n": "┼",
    "q": "─",
    "t": "├",
    "u": "┤",
    "v": "┴",
    "w": "┬",
    "x": "│",
    "o": "█",
    "s": "·",
    "a": "▒",
    "f": "°",
    "g": "±",
    "h": "␋",
    "i": "␌",
    "`": "◆",
}


@dataclass
class _BufferState:
    rows: int
    cols: int
    screen: list[list[str]]
    cursor_row: int = 0
    cursor_col: int = 0
    scrollback: list[str] | None = None
    saved_cursor: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if self.scrollback is None:
            self.scrollback = []


class TerminalEmulator:
    """Small ANSI/VT helper focused on TRUBA banner/dialog redraw behavior."""

    def __init__(self, columns: int = 120, rows: int = 40, *, scrollback_limit: int = 200):
        self._scrollback_limit = max(0, int(scrollback_limit))
        self._acs_mode = False
        self._pending = ""
        self._saved_main: _BufferState | None = None
        self._main = self._new_state(rows, columns)
        self._alt = self._new_state(rows, columns)
        self._use_alt = False

    def _new_state(self, rows: int, cols: int) -> _BufferState:
        rows = max(1, int(rows))
        cols = max(1, int(cols))
        return _BufferState(
            rows=rows,
            cols=cols,
            screen=[[" "] * cols for _ in range(rows)],
        )

    def _state(self) -> _BufferState:
        return self._alt if self._use_alt else self._main

    def resize(self, columns: int, rows: int) -> None:
        columns = max(1, int(columns))
        rows = max(1, int(rows))
        for state in (self._main, self._alt):
            current = self._state_lines(state)
            new_screen = [[" "] * columns for _ in range(rows)]
            for row_idx, line in enumerate(current[-rows:]):
                if row_idx >= rows:
                    break
                chars = list(line[:columns].ljust(columns))
                new_screen[row_idx] = chars
            state.rows = rows
            state.cols = columns
            state.screen = new_screen
            state.cursor_row = min(state.cursor_row, rows - 1)
            state.cursor_col = min(state.cursor_col, columns - 1)

    def reset(self) -> None:
        self._acs_mode = False
        self._pending = ""
        self._saved_main = None
        self._main = self._new_state(self._main.rows, self._main.cols)
        self._alt = self._new_state(self._alt.rows, self._alt.cols)
        self._use_alt = False

    def feed(self, chunk: str) -> None:
        if not chunk:
            return
        text = self._pending + chunk
        self._pending = ""
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\x1b":
                next_i = self._consume_escape(text, i)
                if next_i is None:
                    self._pending = text[i:]
                    break
                i = next_i
                continue
            self._write_char(ch)
            i += 1

    def render(self) -> str:
        state = self._state()
        lines = []
        if not self._use_alt and state.scrollback:
            lines.extend(state.scrollback)
        lines.extend(self._state_lines(state))
        return "\n".join(lines).rstrip()

    def _state_lines(self, state: _BufferState) -> list[str]:
        return ["".join(row).rstrip() for row in state.screen]

    def _consume_escape(self, text: str, idx: int) -> int | None:
        if idx + 1 >= len(text):
            return None
        nxt = text[idx + 1]
        if nxt == "[":
            return self._consume_csi(text, idx + 2)
        if nxt == "(":
            if idx + 2 < len(text):
                spec = text[idx + 2]
                if spec == "0":
                    self._acs_mode = True
                elif spec == "B":
                    self._acs_mode = False
                return idx + 3
            return None
        if nxt == "]":
            return self._consume_osc(text, idx + 2)
        if nxt == "7":
            state = self._state()
            state.saved_cursor = (state.cursor_row, state.cursor_col)
            return idx + 2
        if nxt == "8":
            state = self._state()
            if state.saved_cursor is not None:
                state.cursor_row, state.cursor_col = state.saved_cursor
            return idx + 2
        return idx + 2

    def _consume_osc(self, text: str, idx: int) -> int | None:
        while idx < len(text):
            if text[idx] == "\x07":
                return idx + 1
            if text[idx] == "\x1b" and idx + 1 < len(text) and text[idx + 1] == "\\":
                return idx + 2
            idx += 1
        return None

    def _consume_csi(self, text: str, idx: int) -> int | None:
        start = idx
        while idx < len(text) and not ("@" <= text[idx] <= "~"):
            idx += 1
        if idx >= len(text):
            return None
        params = text[start:idx]
        final = text[idx]
        self._apply_csi(params, final)
        return idx + 1

    def _apply_csi(self, params: str, final: str) -> None:
        state = self._state()
        raw = params or ""
        if raw.startswith("?") and final in ("h", "l"):
            self._apply_private_mode(raw[1:], final == "h")
            return
        numbers = [int(p) if p.isdigit() else 0 for p in raw.split(";") if p != ""]
        if not numbers:
            numbers = [0]

        if final == "A":
            state.cursor_row = max(0, state.cursor_row - (numbers[0] or 1))
        elif final == "B":
            state.cursor_row = min(state.rows - 1, state.cursor_row + (numbers[0] or 1))
        elif final == "C":
            state.cursor_col = min(state.cols - 1, state.cursor_col + (numbers[0] or 1))
        elif final == "D":
            state.cursor_col = max(0, state.cursor_col - (numbers[0] or 1))
        elif final in ("H", "f"):
            row = (numbers[0] if len(numbers) >= 1 else 1) - 1
            col = (numbers[1] if len(numbers) >= 2 else 1) - 1
            state.cursor_row = min(max(row, 0), state.rows - 1)
            state.cursor_col = min(max(col, 0), state.cols - 1)
        elif final == "J":
            self._clear_screen(numbers[0] if numbers else 0)
        elif final == "K":
            self._clear_line(numbers[0] if numbers else 0)
        elif final == "s":
            state.saved_cursor = (state.cursor_row, state.cursor_col)
        elif final == "u":
            if state.saved_cursor is not None:
                state.cursor_row, state.cursor_col = state.saved_cursor
        elif final == "m":
            # SGR is ignored by the text-only renderer.
            return

    def _apply_private_mode(self, mode: str, enabled: bool) -> None:
        if mode != "1049":
            return
        if enabled:
            self._saved_main = self._copy_state(self._main)
            self._alt = self._new_state(self._main.rows, self._main.cols)
            self._use_alt = True
        else:
            if self._saved_main is not None:
                self._main = self._copy_state(self._saved_main)
            self._use_alt = False

    def _copy_state(self, state: _BufferState) -> _BufferState:
        copy = _BufferState(
            rows=state.rows,
            cols=state.cols,
            screen=[row[:] for row in state.screen],
            cursor_row=state.cursor_row,
            cursor_col=state.cursor_col,
            scrollback=list(state.scrollback or []),
            saved_cursor=state.saved_cursor,
        )
        return copy

    def _clear_screen(self, mode: int) -> None:
        state = self._state()
        if mode == 2:
            state.screen = [[" "] * state.cols for _ in range(state.rows)]
            state.cursor_row = 0
            state.cursor_col = 0
        elif mode == 1:
            for row in range(0, state.cursor_row + 1):
                limit = state.cols if row < state.cursor_row else state.cursor_col + 1
                for col in range(0, limit):
                    state.screen[row][col] = " "
        else:
            for row in range(state.cursor_row, state.rows):
                start = state.cursor_col if row == state.cursor_row else 0
                for col in range(start, state.cols):
                    state.screen[row][col] = " "

    def _clear_line(self, mode: int) -> None:
        state = self._state()
        if mode == 2:
            for col in range(state.cols):
                state.screen[state.cursor_row][col] = " "
        elif mode == 1:
            for col in range(0, state.cursor_col + 1):
                state.screen[state.cursor_row][col] = " "
        else:
            for col in range(state.cursor_col, state.cols):
                state.screen[state.cursor_row][col] = " "

    def _write_char(self, ch: str) -> None:
        state = self._state()
        if ch == "\r":
            state.cursor_col = 0
            return
        if ch == "\n":
            state.cursor_row += 1
            state.cursor_col = 0
            self._scroll_if_needed()
            return
        if ch == "\b":
            state.cursor_col = max(0, state.cursor_col - 1)
            return
        if ch == "\t":
            next_tab = min(state.cols - 1, ((state.cursor_col // 8) + 1) * 8)
            while state.cursor_col < next_tab:
                self._write_char(" ")
            return
        if self._acs_mode and ch in _ACS_MAP:
            ch = _ACS_MAP[ch]
        if state.cursor_row >= state.rows:
            self._scroll_if_needed()
        if state.cursor_row < 0:
            state.cursor_row = 0
        if state.cursor_row >= state.rows:
            state.cursor_row = state.rows - 1
        if state.cursor_col >= state.cols:
            state.cursor_row += 1
            state.cursor_col = 0
            self._scroll_if_needed()
        row = state.screen[state.cursor_row]
        row[state.cursor_col] = ch
        state.cursor_col += 1
        if state.cursor_col >= state.cols:
            state.cursor_col = 0
            state.cursor_row += 1
            self._scroll_if_needed()

    def _scroll_if_needed(self) -> None:
        state = self._state()
        while state.cursor_row >= state.rows:
            top = "".join(state.screen.pop(0)).rstrip()
            if not self._use_alt:
                state.scrollback.append(top)
                if self._scrollback_limit and len(state.scrollback) > self._scrollback_limit:
                    del state.scrollback[0 : len(state.scrollback) - self._scrollback_limit]
            state.screen.append([" "] * state.cols)
            state.cursor_row -= 1
