"""Import parsing and resolution for the 'extended' AI review scope."""
from backend.services.related_files import (
    config_files,
    importer_candidates,
    imports_of,
    js_imports,
    python_imports,
)

TREE = {
    "backend/api/users.py", "backend/models/user.py", "backend/models/__init__.py",
    "backend/core/security.py", "backend/api/__init__.py", "backend/api/helpers.py",
    "src/pkg/mod.py", "src/pkg/other.py",
    "web/src/App.jsx", "web/src/api/client.js", "web/src/components/Button.tsx",
    "web/src/components/index.ts", "web/src/utils.ts",
}


def test_python_absolute_relative_and_submodule_imports():
    source = (
        "import os\n"
        "from backend.models.user import User\n"
        "from backend.core import security\n"
        "from . import helpers\n"
        "from ..models import user\n"
        "import fastapi\n"
    )
    assert imports_of("backend/api/users.py", source, TREE) == {
        "backend/models/user.py", "backend/core/security.py", "backend/api/helpers.py",
    }


def test_python_package_import_resolves_to_init():
    assert imports_of("backend/api/users.py", "import backend.models\n", TREE) == {"backend/models/__init__.py"}


def test_python_src_layout():
    assert imports_of("src/pkg/other.py", "from pkg.mod import thing\n", TREE) == {"src/pkg/mod.py"}


def test_python_with_syntax_errors_falls_back_to_regex():
    source = "print 'py2'\nfrom backend.models.user import User\n"
    assert python_imports(source)
    assert imports_of("backend/api/users.py", source, TREE) == {"backend/models/user.py"}


def test_js_ts_relative_imports_with_extensions_and_index():
    source = (
        "import React from 'react';\n"
        "import client from './api/client';\n"
        "import { Button } from './components';\n"
        "export { x } from './utils';\n"
        "const lazy = import('./missing');\n"
        "const c = require('./api/client.js');\n"
    )
    assert js_imports(source) == ["./api/client", "./components", "./utils", "./missing", "./api/client.js"]
    assert imports_of("web/src/App.jsx", source, TREE) == {
        "web/src/api/client.js", "web/src/components/index.ts", "web/src/utils.ts",
    }


def test_imports_outside_the_repository_are_ignored():
    assert imports_of("web/src/App.jsx", "import x from '../../../../etc/passwd';", TREE) == set()


def test_importer_candidates_are_nearby_code_files_only():
    sizes = {path: 100 for path in TREE} | {"backend/api/big.py": 10_000_000, "backend/api/notes.md": 10}
    candidates = importer_candidates(["backend/api/users.py"], sizes, max_bytes=200_000)
    assert "backend/api/helpers.py" in candidates           # same directory
    assert "backend/api/users.py" not in candidates          # the changed file itself
    assert "backend/api/big.py" not in candidates            # too large
    assert "backend/api/notes.md" not in candidates          # not code
    assert "backend/models/user.py" not in candidates        # sibling directory, not checked


def test_config_files_are_top_level_only():
    sizes = {"package.json": 1, "web/package.json": 1, "Dockerfile": 1, "README.md": 1, "requirements.txt": 1}
    assert config_files(sizes, exclude={"requirements.txt"}) == ["package.json", "Dockerfile"]
