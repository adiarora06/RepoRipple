from pathlib import Path

from reporipple.scanner import scan_repository


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scans_python_imports_from_src_layout(tmp_path):
    write(tmp_path, "src/app/__init__.py", "")
    write(tmp_path, "src/app/service.py", "from app.store import load\n")
    write(tmp_path, "src/app/store.py", "def load(): return 1\n")

    graph = scan_repository(tmp_path)

    assert any(
        edge.source == "src/app/service.py" and edge.target == "src/app/store.py"
        for edge in graph.edges
    )


def test_scans_relative_javascript_imports(tmp_path):
    write(tmp_path, "src/pages/dashboard.tsx", "import {load} from '../lib/data';\n")
    write(tmp_path, "src/lib/data.ts", "export const load = () => 1;\n")

    graph = scan_repository(tmp_path)

    assert any(
        edge.source == "src/pages/dashboard.tsx" and edge.target == "src/lib/data.ts"
        for edge in graph.edges
    )


def test_skips_dependency_directories(tmp_path):
    write(tmp_path, "node_modules/package/index.js", "export default 1\n")
    write(tmp_path, ".venv/lib/site.py", "value = 1\n")
    write(tmp_path, "src/index.js", "export default 1\n")

    graph = scan_repository(tmp_path)

    assert graph.files == {"src/index.js"}


def test_records_python_parse_warnings(tmp_path):
    write(tmp_path, "broken.py", "def nope(:\n")

    graph = scan_repository(tmp_path)

    assert graph.warnings
    assert "broken.py" in graph.warnings[0]


def test_does_not_read_source_files_through_symlinks(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")
    (repository / "linked.py").symlink_to(outside)

    graph = scan_repository(repository)

    assert "linked.py" not in graph.files
