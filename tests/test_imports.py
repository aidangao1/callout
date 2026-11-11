"""Every internal import resolves, including the ones done lazily inside functions.

Lazy imports only run when their command is used (e.g. the mic tools), so a broken one
would otherwise only show up on the user's machine.
"""

import ast
import importlib
from pathlib import Path

import callout

PACKAGE = Path(callout.__file__).parent


def _module_name(path: Path) -> str:
    rel = path.relative_to(PACKAGE.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def test_every_internal_import_resolves():
    problems = []
    for path in sorted(PACKAGE.rglob("*.py")):
        here = _module_name(path)
        is_pkg = path.name == "__init__.py"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue
            base = here if is_pkg else here.rsplit(".", 1)[0]
            for _ in range(node.level - 1):
                base = base.rsplit(".", 1)[0]
            target = f"{base}.{node.module}" if node.module else base
            try:
                mod = importlib.import_module(target)
            except ModuleNotFoundError as e:
                if not e.name or e.name.startswith("callout"):
                    problems.append(f"{path.relative_to(PACKAGE)}:{node.lineno} -> {target}")
                continue  # an optional third-party library missing here (e.g. PortAudio) is fine
            except Exception:
                continue
            for alias in node.names:
                if alias.name != "*" and not hasattr(mod, alias.name):
                    try:
                        importlib.import_module(f"{target}.{alias.name}")
                    except ModuleNotFoundError:
                        problems.append(f"{path.relative_to(PACKAGE)}:{node.lineno} -> {target}.{alias.name}")
    assert not problems, "Broken imports:\n" + "\n".join(problems)


def test_web_files_are_packaged_next_to_the_window():
    from callout.app.window import WEB

    for name in ("index.html", "app.css", "app.js", "theme.css", "fonts/GeistMono-Regular.woff2"):
        assert (WEB / name).exists(), name


def test_config_template_is_found():
    from callout.config import TEMPLATE, load_config

    assert TEMPLATE.exists()
    load_config(TEMPLATE)
