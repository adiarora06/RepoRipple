"""Shared file-discovery configuration."""

SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
JAVASCRIPT_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
MAX_SOURCE_FILE_BYTES = 1_000_000
IGNORED_DIRECTORIES = {
    ".git",
    ".github",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "vendor",
    "venv",
}
