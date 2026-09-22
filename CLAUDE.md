# Working in this repo

## File size: 1,000 lines

**No source file goes over 1,000 lines. When one is about to, split it instead.**

Applies to every `.py` file in the repo — app code, modules and tests alike.

### Why

A file you cannot hold in your head is a file you edit by grep. Past roughly a
thousand lines the failure is not aesthetic:

- **Merge conflicts concentrate.** Two people working on unrelated features
  collide because both live in `app.py`.
- **The seams stop being visible.** When five responsibilities share a file,
  nothing marks where one ends, so the sixth gets added anywhere and the file
  gets worse faster than it got big.
- **Tools degrade.** Search returns the same file for every query; a reviewer
  reading a diff has no context for where in the file they are.

### When a file crosses the line

Split it **at a seam that already exists**, not at line 1,000. Every long file
in this repo is long because it holds several jobs; the section comments
(`# --- name ---`) usually mark them already. Take one whole job out into a
module named after it.

A split is done properly when:

1. The new module has a docstring saying what it is responsible for.
2. The original imports from it and gets shorter — no re-exporting the whole
   surface back out to avoid touching callers.
3. Tests still pass without being rewritten. If a split forces test changes,
   the seam was wrong.

Do **not** split by cutting at a line number, by moving code into a `utils.py`,
or by creating `app_part2.py`. A module is a responsibility, not a bucket.

### Checking

```bash
find . -name "*.py" -not -path "./.venv/*" -not -path "*__pycache__*" \
  | xargs wc -l | sort -rn | awk '$1 > 1000 && $2 != "total"'
```

Run it before opening a PR. Empty output means you are fine.

### Where the repo stands

As of 2026-09-22, every file is under the limit. The layout that got it there,
worth knowing before you add to it:

| module | holds |
|---|---|
| `app.py` (891) | wiring: state, auth gate, the chat operations, and the call into each tab |
| `sidebar.py` (444) | projects, workspace and settings |
| `tabs/*.py` | one module per tab — `chat`, `features`, `board`, `compare`, `copyright` — each a `render(...)` taking what it needs as keyword arguments |
| `tabs/constants.py` | the words a status can take and the glyph or tone it wears |
| `report.py` / `report_blocks.py` / `report_style.py` | the PDF: document, the charts and tables inside an answer, and the ink |
| `theme.py` / `theme_css.py` | the design system, and the stylesheet it injects |

Two things this split made explicit, both worth preserving:

- **A tab takes what it needs; it does not reach back into `app.py`.** The
  transcript, the workspace and the app's callbacks arrive as arguments. Before
  the split, `messages` was a module-level binding the Chat tab happened to
  create and four other tabs happened to read — invisible until it broke.
- **`render()` returns anything later code needs.** The Chat tab hands back the
  pending exchange, because answering it is deliberately the last thing the app
  does.

## Other conventions

- **Style follows the file you are in** — comment density, naming and idiom.
  The codebase explains *why*, not *what*; match that.
- **Run the tests** with `cd proxima && python -m pytest tests -q`, or
  `python -m unittest discover -s tests -p "test_*.py"` if pytest is absent.
- **Every source file carries the SPDX header** already used across the repo:
  ```python
  # SPDX-License-Identifier: AGPL-3.0-only
  # Copyright (C) 2026 Jason Yan
  ```
