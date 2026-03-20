#!/usr/bin/env python3
"""
Dify Plugin Offline Packager

Downloads a Dify plugin (from Marketplace, GitHub, or local file),
bundles its Python dependencies as wheels, and packages it as an
offline-ready .difypkg file.

Runs inside the official langgenius/dify-plugin-daemon container
which ships with uv and Python 3.12. All operations use uv.
"""

import argparse
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Configuration (overridable via environment variables)
# ---------------------------------------------------------------------------

MARKETPLACE_API_URL = os.environ.get(
    "MARKETPLACE_API_URL", "https://marketplace.dify.ai"
)
GITHUB_API_URL = os.environ.get("GITHUB_API_URL", "https://github.com")
PIP_INDEX_URL = os.environ.get(
    "PIP_INDEX_URL", "https://pypi.org/simple"
)
DIFY_PLUGIN_VERSION = os.environ.get("DIFY_PLUGIN_VERSION", "0.5.3")

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/difypkg"))
WORK_DIR = Path(os.environ.get("WORK_DIR", "/tmp/packager-work"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_AGENT = "dify-plugin-offline-packager/1.0"


def download_file(url: str, dest: str) -> None:
    """Download a file from a URL with a proper User-Agent header."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess, printing the command and raising on failure."""
    print(f"  ▸ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, check=True, **kwargs)


def ensure_dify_plugin_cli(work: Path) -> Path:
    """
    Ensure the dify-plugin CLI binary exists and is executable.
    Downloads from GitHub releases if not already cached.
    Returns the path to the binary.
    """
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        sys.exit(f"Unsupported architecture: {machine}")

    binary_name = f"dify-plugin-linux-{arch}"
    cached = Path("/tmp") / f"dify-plugin-cli-{DIFY_PLUGIN_VERSION}-{arch}"

    if cached.exists():
        return cached

    url = (
        f"https://github.com/langgenius/dify-plugin-daemon"
        f"/releases/download/{DIFY_PLUGIN_VERSION}/{binary_name}"
    )
    print(f"⬇  Downloading dify-plugin CLI ({DIFY_PLUGIN_VERSION}) …")
    print(f"   {url}")
    download_file(url, str(cached))
    cached.chmod(cached.stat().st_mode | stat.S_IEXEC)
    print("   Done.")
    return cached


def download_marketplace(author: str, name: str, version: str, dest: Path) -> Path:
    """Download a plugin from the Dify Marketplace."""
    url = f"{MARKETPLACE_API_URL}/api/v1/plugins/{author}/{name}/{version}/download"
    filename = f"{author}-{name}_{version}.difypkg"
    filepath = dest / filename
    print(f"⬇  Downloading from Marketplace …")
    print(f"   {url}")
    download_file(url, str(filepath))
    return filepath


def download_github(repo: str, tag: str, asset: str, dest: Path) -> Path:
    """Download a plugin from a GitHub release."""
    # Allow full URL or short repo form
    if not repo.startswith("http"):
        repo_url = f"{GITHUB_API_URL}/{repo}"
    else:
        repo_url = repo
    url = f"{repo_url}/releases/download/{tag}/{asset}"
    stem = asset.removesuffix(".difypkg")
    filename = f"{stem}-{tag}.difypkg"
    filepath = dest / filename
    print(f"⬇  Downloading from GitHub …")
    print(f"   {url}")
    download_file(url, str(filepath))
    return filepath


def resolve_local(path_str: str) -> Path:
    """Resolve a local .difypkg path (supports host-mounted paths)."""
    p = Path(path_str)
    if not p.exists():
        # Try under the mounted /difypkg directory
        alt = OUTPUT_DIR / p.name
        if alt.exists():
            return alt
        sys.exit(f"File not found: {path_str}")
    return p


# ---------------------------------------------------------------------------
# Dependency download & patching helpers
# ---------------------------------------------------------------------------


def _download_wheels_pip(req_file: Path, wheels_dir: Path) -> None:
    """Download wheels using uv based on requirements.txt."""
    cmd = [
        "uv", "run", "pip", "download",
        "-r", str(req_file),
        "-d", str(wheels_dir),
    ]
    if PIP_INDEX_URL:
        cmd += ["--index-url", PIP_INDEX_URL]

    print("⬇  Downloading Python dependencies …")
    run(cmd)


def _download_wheels_uv(extract_dir: Path, wheels_dir: Path) -> None:
    """Download wheels using uv based on pyproject.toml."""
    # Export pinned dependencies from pyproject.toml
    print("⬇  Exporting dependencies from pyproject.toml …")
    export_result = subprocess.run(
        ["uv", "export", "--frozen", "--no-hashes", "--directory", str(extract_dir)],
        capture_output=True, text=True,
    )
    if export_result.returncode != 0:
        # Fallback: try uv export without --frozen
        export_result = subprocess.run(
            ["uv", "export", "--no-hashes", "--directory", str(extract_dir)],
            capture_output=True, text=True,
        )
    if export_result.returncode != 0:
        print("   ⚠  uv export failed, falling back to requirements.txt")
        req_file = extract_dir / "requirements.txt"
        if req_file.exists():
            _download_wheels_pip(req_file, wheels_dir)
        return

    # Write exported requirements to a temp file and download via uv
    exported_req = extract_dir / "_exported_requirements.txt"
    exported_req.write_text(export_result.stdout)

    cmd = [
        "uv", "run", "pip", "download",
        "-r", str(exported_req),
        "-d", str(wheels_dir),
    ]
    if PIP_INDEX_URL:
        cmd += ["--index-url", PIP_INDEX_URL]

    print("⬇  Downloading Python dependencies (from pyproject.toml) …")
    run(cmd)

    # Clean up temp file
    exported_req.unlink(missing_ok=True)


def _patch_requirements_txt_offline(req_file: Path) -> None:
    """Prepend --no-index --find-links=./wheels/ to requirements.txt."""
    original = req_file.read_text()
    patched = f"--no-index --find-links=./wheels/\n{original}"
    req_file.write_text(patched)


def _detect_python_version() -> str:
    """Return the running Python version as 'MAJOR.MINOR' (e.g. '3.12')."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _patch_pyproject_toml_offline(pyproject_file: Path, wheels_dir: Path) -> None:
    """
    Add (or update) the [tool.uv] section in pyproject.toml to enable
    offline installation from bundled wheels.

    Adds:
        [tool.uv]
        no-index = true
        find-links = ["./wheels/"]
        environments = ["sys_platform == 'linux'"]

    Also pins ``requires-python`` to the current runtime version so that
    uv does not attempt to resolve dependencies for Python versions that
    are not present in the bundled wheels.
    """
    content = pyproject_file.read_text()

    # ------------------------------------------------------------------
    # 1. Pin requires-python to the current runtime so uv does not try
    #    to solve for future Python versions whose wheels we don't have.
    # ------------------------------------------------------------------
    py_ver = _detect_python_version()  # e.g. "3.12"
    new_requires = f'requires-python = "=={py_ver}.*"'

    if re.search(r'^requires-python\s*=', content, re.MULTILINE):
        content = re.sub(
            r'^requires-python\s*=\s*.*$',
            new_requires,
            content,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        # Insert under [project] if it exists
        if re.search(r'^\[project\]', content, re.MULTILINE):
            content = re.sub(
                r'^(\[project\])',
                rf'\1\n{new_requires}',
                content,
                count=1,
                flags=re.MULTILINE,
            )
    print(f'   ✏  Pinned requires-python to "=={py_ver}.*".')

    # ------------------------------------------------------------------
    # 2. Add [tool.uv] offline settings and restrict resolution to
    #    the current platform only. Without `environments`, uv tries
    #    to resolve for ALL platforms (including Windows) and fails
    #    when platform-specific wheels like colorama are missing.
    # ------------------------------------------------------------------
    uv_settings = (
        'no-index = true\n'
        'find-links = ["./wheels/"]\n'
        'environments = ["sys_platform == \'linux\'"]'
    )
    uv_block = f'\n[tool.uv]\n{uv_settings}\n'

    # Check if [tool.uv] already exists
    if re.search(r"^\[tool\.uv\]", content, re.MULTILINE):
        # Patch existing section: inject keys right after the header
        def _inject(m: re.Match) -> str:
            return m.group(0) + '\n' + uv_settings

        content = re.sub(
            r"^\[tool\.uv\]",
            _inject,
            content,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        # Append a new section
        content = content.rstrip() + "\n" + uv_block

    pyproject_file.write_text(content)
    print("   ✏  Patched pyproject.toml with [tool.uv] offline settings.")

    # ------------------------------------------------------------------
    # 2. Remove uv.lock so that uv does not attempt to reconcile the
    #    lockfile (which contains remote-index references) with
    #    no-index = true.
    # ------------------------------------------------------------------
    lock_file = pyproject_file.parent / "uv.lock"
    if lock_file.exists():
        lock_file.unlink()
        print("   ✏  Removed uv.lock to avoid remote-index reconciliation.")


# ---------------------------------------------------------------------------
# Core packaging logic
# ---------------------------------------------------------------------------


def package_offline(pkg_path: Path, cli: Path, work: Path) -> Path:
    """
    Package a .difypkg with bundled wheels for offline use.

    1. Unzip the package
    2. Download all dependencies as wheels (via uv)
    3. Patch pyproject.toml or requirements.txt for offline use
    4. Re-pack using the dify-plugin CLI
    """
    pkg_name = pkg_path.stem
    extract_dir = work / pkg_name

    # -- Unzip --
    print(f"\n📦 Unzipping {pkg_path.name} …")
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    with zipfile.ZipFile(pkg_path, "r") as zf:
        zf.extractall(extract_dir)

    # -- Download wheels --
    pyproject_file = extract_dir / "pyproject.toml"
    req_file = extract_dir / "requirements.txt"
    has_pyproject = pyproject_file.exists()
    has_requirements = req_file.exists()

    if not has_pyproject and not has_requirements:
        print("   ⚠  No pyproject.toml or requirements.txt found – skipping dependency download.")
    else:
        wheels_dir = extract_dir / "wheels"
        wheels_dir.mkdir(exist_ok=True)

        # Determine which file drives dependency resolution
        # dify-plugin-daemon prioritises pyproject.toml over requirements.txt
        if has_pyproject:
            print("   ℹ  pyproject.toml detected – using uv for dependency download.")
            _download_wheels_uv(extract_dir, wheels_dir)
            _patch_pyproject_toml_offline(pyproject_file, wheels_dir)
        else:
            _download_wheels_pip(req_file, wheels_dir)
            _patch_requirements_txt_offline(req_file)

        # -- Patch .difyignore / .gitignore to not ignore wheels/ --
        for ignore_name in (".difyignore", ".gitignore"):
            ignore_file = extract_dir / ignore_name
            if ignore_file.exists():
                lines = ignore_file.read_text().splitlines()
                lines = [l for l in lines if l.strip() != "wheels/"]
                ignore_file.write_text("\n".join(lines) + "\n")

    # -- Re-pack --
    output_name = f"{pkg_name}-offline.difypkg"
    output_path = OUTPUT_DIR / output_name

    print(f"\n📦 Packaging → {output_name} …")
    run([
        str(cli), "plugin", "package",
        str(extract_dir),
        "-o", str(output_path),
        "--max-size", "5120",
    ])

    print(f"\n✅ Success! → {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Marketplace shorthand parser  (e.g. "langgenius/openai:0.0.17")
# ---------------------------------------------------------------------------


def parse_marketplace_shorthand(value: str) -> tuple[str, str, str]:
    """
    Parse 'author/name:version' → (author, name, version)
    """
    if ":" not in value or "/" not in value:
        sys.exit(
            f"Invalid marketplace shorthand: {value}\n"
            f"Expected format: author/name:version  (e.g. langgenius/openai:0.0.17)"
        )
    repo_part, version = value.rsplit(":", 1)
    author, name = repo_part.split("/", 1)
    return author, name, version


def parse_github_shorthand(value: str) -> tuple[str, str, str]:
    """
    Parse 'owner/repo:tag:asset' or 'owner/repo:tag' → (repo, tag, asset)
    If asset is omitted, we guess '<repo-name>.difypkg'.
    """
    parts = value.split(":")
    if len(parts) == 3:
        repo, tag, asset = parts
        if not asset.endswith(".difypkg"):
            asset += ".difypkg"
        return repo, tag, asset
    elif len(parts) == 2:
        repo, tag = parts
        repo_name = repo.split("/")[-1]
        asset = f"{repo_name}.difypkg"
        return repo, tag, asset
    else:
        sys.exit(
            f"Invalid github shorthand: {value}\n"
            f"Expected format: owner/repo:tag[:asset.difypkg]"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Dify Plugin Offline Packager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --marketplace "langgenius/openai:0.0.17"
  %(prog)s --github "junjiem/dify-plugin-tools-dbquery:v0.0.2:db_query.difypkg"
  %(prog)s --local "./my-plugin.difypkg"
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--marketplace", "-m",
        metavar="AUTHOR/NAME:VERSION",
        help="Download from the Dify Marketplace (e.g. langgenius/openai:0.0.17)",
    )
    group.add_argument(
        "--github", "-g",
        metavar="OWNER/REPO:TAG[:ASSET]",
        help="Download from GitHub releases",
    )
    group.add_argument(
        "--local", "-l",
        metavar="PATH",
        help="Use a local .difypkg file",
    )

    args = parser.parse_args()

    # -- Prepare workspace --
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cli = ensure_dify_plugin_cli(WORK_DIR)

    # -- Acquire the .difypkg --
    if args.marketplace:
        author, name, version = parse_marketplace_shorthand(args.marketplace)
        pkg_path = download_marketplace(author, name, version, WORK_DIR)

    elif args.github:
        repo, tag, asset = parse_github_shorthand(args.github)
        pkg_path = download_github(repo, tag, asset, WORK_DIR)

    elif args.local:
        pkg_path = resolve_local(args.local)

    # -- Copy original to output dir --
    original_dest = OUTPUT_DIR / pkg_path.name
    if pkg_path != original_dest and not original_dest.exists():
        shutil.copy2(pkg_path, original_dest)
        print(f"📄 Original saved → {original_dest}")

    # -- Package for offline use --
    package_offline(pkg_path, cli, WORK_DIR)


if __name__ == "__main__":
    main()
