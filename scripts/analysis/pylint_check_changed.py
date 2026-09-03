"""Run Pylint only for changed Python files in the repository."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

PYTHON_EXTENSIONS = {".py", ".pyi"}
PYLINT_EXCLUDED_PREFIXES = (
    Path("tools") / "pylint_plugins",
)
TRACKED_DIFF_ARGS = ["diff", "--name-only", "-z", "--diff-filter=ACMRTUXB"]
STAGED_DIFF_ARGS = ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRTUXB"]
UNTRACKED_DIFF_ARGS = ["ls-files", "--others", "--exclude-standard", "-z"]
PYLINT_BASE_COMMAND = [
    "-m",
    "pylint",
    "--reports=n",
    "--score=n",
    "--persistent=n",
]


def run_git(args: list[str], cwd: Path) -> list[str]:
    """Run a Git command and return NUL-delimited output as decoded paths."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )

    # -z в git отдаёт пути через NUL-байт, безопаснее для пробелов и спецсимволов.
    return [
        item.decode("utf-8", errors="replace")
        for item in result.stdout.split(b"\0")
        if item
    ]


def get_repo_root() -> Path:
    """Resolve the Git repository root."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def get_changed_python_files(repo_root: Path) -> list[Path]:
    """Collect tracked, staged, and untracked changed Python files."""
    pathspec = ["--", "*.py", "*.pyi"]

    files: set[str] = set()

    # Изменённые tracked-файлы, но не deleted.
    files.update(
        run_git(
            [*TRACKED_DIFF_ARGS, *pathspec],
            cwd=repo_root,
        )
    )

    # Staged-файлы, но не deleted.
    files.update(
        run_git(
            [*STAGED_DIFF_ARGS, *pathspec],
            cwd=repo_root,
        )
    )

    # Untracked-файлы, с учётом .gitignore.
    files.update(
        run_git(
            [*UNTRACKED_DIFF_ARGS, *pathspec],
            cwd=repo_root,
        )
    )

    result: list[Path] = []

    for file in sorted(files):
        path = repo_root / file

        if (
            path.exists()
            and path.suffix in PYTHON_EXTENSIONS
            and not _is_excluded_from_pylint(path.relative_to(repo_root))
        ):
            result.append(path)

    return result


def to_pylint_path(file: Path, repo_root: Path, *, relative: bool) -> str:
    """Convert a file path to the form passed to Pylint."""
    if not relative:
        return str(file)

    relative_path = file.relative_to(repo_root).as_posix()

    # Безопаснее для путей, которые теоретически могут начинаться с "-".
    # Иначе CLI может принять такой путь за опцию.
    if relative_path.startswith("-"):
        return f"./{relative_path}"

    return relative_path


def _is_excluded_from_pylint(relative_path: Path) -> bool:
    return any(relative_path.is_relative_to(prefix) for prefix in PYLINT_EXCLUDED_PREFIXES)


def main() -> int:
    """Run Pylint for changed Python files."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--absolute",
        action="store_true",
        help="Передавать Pylint абсолютные пути вместо относительных.",
    )

    args, extra_pylint_args = parser.parse_known_args()

    repo_root = get_repo_root()
    files = get_changed_python_files(repo_root)

    if not files:
        print("No changed Python files.")
        return 0

    pylint_files = [
        to_pylint_path(file, repo_root, relative=not args.absolute)
        for file in files
    ]
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(repo_root)
        if not existing_pythonpath
        else f"{repo_root}{os.pathsep}{existing_pythonpath}"
    )
    env["PYLINTHOME"] = str(repo_root / ".pylint")

    command = [
        sys.executable,
        *PYLINT_BASE_COMMAND,
        *extra_pylint_args,
        *pylint_files,
    ]

    return subprocess.run(command, cwd=repo_root, check=False, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
