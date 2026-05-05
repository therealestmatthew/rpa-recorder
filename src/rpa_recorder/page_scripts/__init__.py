"""Loader for page-side JavaScript bundled inside the wheel.

The browser-side recorder and replay helpers live as `.js` files under
`recorder/`, `replay/`, and `shared/` subpackages. Python code reads them
via `load(...)` and concatenates several into a single Playwright init
script via `bundle(...)`.

Both helpers are sync — JS files ship inside the wheel, so there is no
I/O contention; making them async would just bloat the call sites.
"""

from importlib.resources import files


def load(script: str) -> str:
    """Load a JS file by relative path. `'recorder/inject'` → `recorder/inject.js`.

    The path uses forward slashes regardless of platform. Subpackages must
    contain `__init__.py` so `importlib.resources.files` resolves them.

    Raises:
        FileNotFoundError: if no `.js` file exists at the given path.
    """
    parts = script.split("/")
    leaf = parts[-1] + ".js"
    pkg = "rpa_recorder.page_scripts." + ".".join(parts[:-1])
    resource = files(pkg).joinpath(leaf)
    if not resource.is_file():
        raise FileNotFoundError(f"page_scripts: {script} not found ({pkg}/{leaf})")
    return resource.read_text(encoding="utf-8")


def bundle(*scripts: str) -> str:
    """Concatenate scripts in order, separated by `\\n;\\n`.

    The leading semicolon prevents JS ASI bugs when one script ends in an
    expression and the next starts with `(`, `[`, or `/`.
    """
    return "\n;\n".join(load(s) for s in scripts)


__all__ = ["bundle", "load"]
