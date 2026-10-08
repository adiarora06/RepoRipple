from pathlib import Path

import reporipple.scanner as scanner
from reporipple.config import MAX_SOURCE_FILE_BYTES
from reporipple.scanner import discover_source_files, scan_repository


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


def test_discovers_and_resolves_module_specific_typescript_extensions(tmp_path):
    write(tmp_path, "src/app.mts", "import {load} from './loader.cjs';\n")
    write(tmp_path, "src/loader.cts", "export const load = () => 1;\n")

    graph = scan_repository(tmp_path)

    assert graph.files == {"src/app.mts", "src/loader.cts"}
    assert any(
        edge.source == "src/app.mts" and edge.target == "src/loader.cts" for edge in graph.edges
    )


def test_skips_dependency_directories(tmp_path):
    write(tmp_path, "node_modules/package/index.js", "export default 1\n")
    write(tmp_path, ".venv/lib/site.py", "value = 1\n")
    write(tmp_path, "src/index.js", "export default 1\n")

    graph = scan_repository(tmp_path)

    assert graph.files == {"src/index.js"}


def test_prunes_builtin_and_gitignored_directories_before_walking(tmp_path, monkeypatch):
    write(tmp_path, ".gitignore", "scratch/\n")
    write(tmp_path, "node_modules/package/index.js", "export default 1\n")
    write(tmp_path, "scratch/deep/generated.py", "value = 1\n")
    write(tmp_path, "src/index.py", "value = 1\n")
    visited: list[str] = []
    real_walk = scanner.os.walk

    def tracking_walk(*args, **kwargs):
        for current, directories, files in real_walk(*args, **kwargs):
            visited.append(Path(current).relative_to(tmp_path).as_posix())
            yield current, directories, files

    monkeypatch.setattr(scanner.os, "walk", tracking_walk)

    files = discover_source_files(tmp_path)

    assert files == {"src/index.py"}
    assert "node_modules" not in visited
    assert "scratch" not in visited


def test_honors_nested_gitignore_rules_negations_and_anchored_patterns(tmp_path):
    write(tmp_path, ".gitignore", "*.py\n!keep.py\n/root_only.ts\n")
    write(tmp_path, "drop.py", "value = 1\n")
    write(tmp_path, "keep.py", "value = 1\n")
    write(tmp_path, "root_only.ts", "export const value = 1;\n")
    write(tmp_path, "nested/.gitignore", "*.js\n!keep.js\n")
    write(tmp_path, "nested/drop.py", "value = 1\n")
    write(tmp_path, "nested/keep.py", "value = 1\n")
    write(tmp_path, "nested/drop.js", "export const value = 1;\n")
    write(tmp_path, "nested/keep.js", "export const value = 1;\n")
    write(tmp_path, "nested/root_only.ts", "export const value = 1;\n")

    assert discover_source_files(tmp_path) == {
        "keep.py",
        "nested/keep.js",
        "nested/keep.py",
        "nested/root_only.ts",
    }


def test_duplicate_python_modules_resolve_deterministically():
    files = ["src/foo.py", "consumer.py", "foo.py"]
    forward_warnings: list[str] = []
    reverse_warnings: list[str] = []

    forward = scanner._python_module_index(files, forward_warnings)
    reverse = scanner._python_module_index(reversed(files), reverse_warnings)

    assert forward == reverse
    assert forward["foo"] == "foo.py"
    assert (
        forward_warnings
        == reverse_warnings
        == ["Ambiguous Python module 'foo': foo.py, src/foo.py; using foo.py"]
    )


def test_scan_warns_and_does_not_parse_oversized_sources(tmp_path):
    write(tmp_path, "too_large.py", "x" * (MAX_SOURCE_FILE_BYTES + 1))

    graph = scan_repository(tmp_path)

    assert "too_large.py" in graph.files
    assert graph.edges == []
    assert graph.warnings == [
        f"Skipped too_large.py: source is larger than {MAX_SOURCE_FILE_BYTES} bytes"
    ]


def test_virtual_deleted_source_participates_in_dependency_graph(tmp_path):
    write(tmp_path, "consumer.py", "import deleted\n")

    graph = scan_repository(tmp_path, virtual_files={"deleted.py": "value = 1\n"})

    assert "deleted.py" in graph.files
    assert any(edge.source == "consumer.py" and edge.target == "deleted.py" for edge in graph.edges)


def test_unencodable_virtual_source_warns_without_aborting_scan(tmp_path):
    write(tmp_path, "healthy.py", "value = 1\n")

    graph = scan_repository(tmp_path, virtual_files={"broken.py": "\ud800"})

    assert graph.files == {"broken.py", "healthy.py"}
    assert any("Could not read broken.py" in warning for warning in graph.warnings)


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
