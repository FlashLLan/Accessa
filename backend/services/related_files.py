"""Related files for the 'extended' AI review scope.

Simple, static import parsing for Python and JavaScript/TypeScript:
- files a changed file imports (resolved against the repository tree);
- files that import a changed file. Searching the whole repository would cost one
  GitHub request per file, so only code files in the same directory as a changed
  file or its parent directory are checked (at most MAX_IMPORTER_CANDIDATES);
- top-level config files (package.json, pyproject.toml, Dockerfile, ...).

Only Python and relative JS/TS imports ('./x', '../x') are resolved; package
imports (react, fastapi, ...) are external and ignored. Dynamic imports built at
run time are not seen.
"""
import ast
import posixpath
import re

PYTHON_SUFFIXES = (".py",)
JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
CODE_SUFFIXES = PYTHON_SUFFIXES + JS_SUFFIXES

MAX_IMPORTER_CANDIDATES = 20
MAX_RELATED_FILES = 15
MAX_CONFIG_FILES = 8

# Top-level files that describe how the project is built, configured and deployed.
# Lock files are left out (large and rarely useful for a review).
CONFIG_FILE_NAMES = (
    "package.json", "tsconfig.json", "vite.config.js", "vite.config.ts", "webpack.config.js",
    "eslint.config.js", ".eslintrc.json", ".eslintrc.js",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "alembic.ini",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "Makefile", ".env.example", "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "Gemfile",
)

_PY_FROM = re.compile(r"^\s*from\s+(\.*[\w.]*)\s+import\s+\(?\s*([\w\s,*]+)", re.M)
_PY_IMPORT = re.compile(r"^\s*import\s+([\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*)", re.M)
_JS_SPECIFIER = re.compile(
    r"""(?:\bimport\s+(?:[^'"`;]*?\s+from\s+)?|\bexport\s+[^'"`;]*?\s+from\s+|\brequire\s*\(\s*|\bimport\s*\(\s*)"""
    r"""['"](\.{1,2}/[^'"]+)['"]"""
)


def is_code_file(path: str) -> bool:
    return path.endswith(CODE_SUFFIXES)


# --- parsing --------------------------------------------------------------------------------

def python_imports(source: str) -> list[tuple[int, str, list[str]]]:
    """(level, module, imported names). level > 0 for relative imports."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return _python_imports_regex(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(0, alias.name, []) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.level or 0, node.module or "", [a.name for a in node.names]))
    return found


def _python_imports_regex(source: str) -> list[tuple[int, str, list[str]]]:
    found = []
    for match in _PY_FROM.finditer(source):
        spec = match[1]
        level = len(spec) - len(spec.lstrip("."))
        names = [n.strip().split(" ")[0] for n in match[2].split(",") if n.strip()]
        found.append((level, spec.lstrip("."), names))
    for match in _PY_IMPORT.finditer(source):
        for part in match[1].split(","):
            found.append((0, part.strip().split(" ")[0], []))
    return found


def js_imports(source: str) -> list[str]:
    return [match[1] for match in _JS_SPECIFIER.finditer(source)]


# --- resolution -------------------------------------------------------------------------------

def _python_module_files(base: str, module: str) -> list[str]:
    path = posixpath.join(base, *module.split(".")) if module else base
    return [path + ".py", posixpath.join(path, "__init__.py")]


def _ancestors(path: str) -> list[str]:
    """'' (repository root) first, then each parent directory of `path`."""
    parts = path.split("/")[:-1]
    return [""] + ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def resolve_python(importer: str, level: int, module: str, names: list[str], tree: set[str]) -> set[str]:
    if level:
        base = posixpath.dirname(importer)
        for _ in range(level - 1):
            base = posixpath.dirname(base)
        roots = [base]
    else:
        # Absolute imports: try the repository root, then the importer's parent
        # directories (covers src/ layouts).
        roots = _ancestors(importer)

    def find(mod: str) -> str | None:
        for root in roots:
            hits = [p for p in _python_module_files(root, mod) if p in tree]
            if hits:
                return hits[0]
        return None

    resolved = set()
    # `from pkg import name` may import the submodule pkg/name.py ...
    names = [n for n in names if n != "*"]
    submodules = {n: find(f"{module}.{n}" if module else n) for n in names}
    resolved |= {path for path in submodules.values() if path}
    # ... otherwise `name` is defined in pkg itself (or it is `import pkg`).
    if module and (not names or not all(submodules.values())):
        if path := find(module):
            resolved.add(path)
    return resolved


def resolve_js(importer: str, specifier: str, tree: set[str]) -> set[str]:
    target = posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))
    if target.startswith(".."):
        return set()
    candidates = [target] + [target + ext for ext in JS_SUFFIXES] + [f"{target}/index{ext}" for ext in JS_SUFFIXES]
    for candidate in candidates:
        if candidate in tree:
            return {candidate}
    return set()


def imports_of(path: str, source: str, tree: set[str]) -> set[str]:
    """Repository files that `path` imports, resolved against `tree`."""
    resolved: set[str] = set()
    if path.endswith(PYTHON_SUFFIXES):
        for level, module, names in python_imports(source):
            resolved |= resolve_python(path, level, module, names, tree)
    elif path.endswith(JS_SUFFIXES):
        for specifier in js_imports(source):
            resolved |= resolve_js(path, specifier, tree)
    resolved.discard(path)
    return resolved


# --- selection ----------------------------------------------------------------------------------

def importer_candidates(changed: list[str], tree: dict[str, int], max_bytes: int) -> list[str]:
    """Code files near the changed files that may import them: same directory and
    parent directory, not themselves changed, not larger than max_bytes."""
    changed_set = set(changed)
    directories = set()
    for path in changed:
        if is_code_file(path):
            directory = posixpath.dirname(path)
            directories |= {directory, posixpath.dirname(directory)}
    candidates = sorted(
        path for path, size in tree.items()
        if posixpath.dirname(path) in directories
        and is_code_file(path)
        and path not in changed_set
        and size <= max_bytes
    )
    return candidates[:MAX_IMPORTER_CANDIDATES]


def config_files(tree: dict[str, int], exclude: set[str]) -> list[str]:
    present = [name for name in CONFIG_FILE_NAMES if name in tree and name not in exclude]
    return present[:MAX_CONFIG_FILES]
