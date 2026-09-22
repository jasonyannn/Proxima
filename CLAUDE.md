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

As of 2026-09-22, three files are over and one is at the line:

| file | lines | the seam to split on |
|---|---|---|
| `proxima/proxima/app.py` | 2,317 | Each tab is already its own block. `ip_tab` (L1939–2254), `compare_tab` (L1628–1937) and `board_tab` (L1412–1626) lift out to `tabs/` almost untouched — that alone takes it under 1,000. |
| `proxima/proxima/report.py` | 1,136 | `# --- blocks` (L430–637) is the chart/table/diagram renderer and depends on little else — it becomes `report_blocks.py`. The markdown converter (L221–429) is a second candidate. |
| `proxima/proxima/theme.py` | 1,008 | The CSS string (L31–786) and the render helpers (L787+) are two different things sharing a file. |
| `proxima/proxima/agent.py` | 997 | At the limit. The next feature added here splits it first — the Ollama client and the intent classification are separate jobs. |

These are pre-existing and are not required to be fixed in an unrelated change.
The rule binds new work: do not make a file over the limit longer, and do not
push a file over the limit.

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
