<!-- omit in toc -->
# Dify Plugin Offline Packager

A Docker-based tool that rebuilds [Dify](https://dify.ai) plugin packages (`.difypkg`) so they can be **installed on air-gapped / internet-disconnected Dify instances**.  
It bundles all Python dependencies as pre-built wheels into the package.

- [✨ Why This Tool?](#-why-this-tool)
- [✅ Prerequisites](#-prerequisites)
- [📝 Quick Start](#-quick-start)
  - [📦 Making Offline Packages from Dify Marketplace](#-making-offline-packages-from-dify-marketplace)
  - [📦 Making Offline Packages from GitHub Releases](#-making-offline-packages-from-github-releases)
  - [📦 Making Offline Packages from a Local File](#-making-offline-packages-from-a-local-file)
  - [📦 Output](#-output)
- [⚙️ Configuration](#️-configuration)
- [⚙️ How It Works](#️-how-it-works)
- [⚙️ Dify Platform Settings](#️-dify-platform-settings)
- [🖥️ Running Locally (without Docker)](#️-running-locally-without-docker)
- [🙏 Acknowledgements](#-acknowledgements)

## ✨ Why This Tool?

This tool runs directly inside the **official `langgenius/dify-plugin-daemon` container image** — the same image that Dify Community Edition uses to install and manage plugins. This means:

- **Accurate dependency resolution** — Python packages are resolved using the exact same Python version, system libraries, and `uv` toolchain that Dify uses at runtime. No version mismatches or missing native libraries.
- **Zero build step** — No custom `Dockerfile`, no image builds. Just `docker compose run`.

> [!IMPORTANT]
> Wheels are downloaded for the CPU architecture of the machine running this tool.
> Make sure you run it on the same architecture (amd64 / arm64) as your production Dify environment.

## ✅ Prerequisites

- Docker host with the same CPU architecture as your containerized Dify Plugin Daemon (amd64 or arm64)
- Docker & Docker Compose
- Internet access (to download plugins and Python packages)

> [!NOTE]
> If you are running the Dify Plugin Daemon locally instead of as a container, you can run the packager script directly without Docker.
> See [🖥️ Running Locally (without Docker)](#️-running-locally-without-docker) for details.

## 📝 Quick Start

```bash
git clone https://github.com/kurokobo/dify-plugin-offline-packager.git
cd dify-plugin-offline-packager
# (Optional) Customize settings
cp .env.example .env
```

### 📦 Making Offline Packages from Dify Marketplace

```bash
# author/name:version
docker compose run --rm packager --marketplace "langgenius/openai:0.3.2"
```

### 📦 Making Offline Packages from GitHub Releases

```bash
# owner/repo:tag:asset.difypkg
docker compose run --rm packager --github "junjiem/dify-plugin-agent-mcp_sse:0.2.4:agent-mcp_sse.difypkg"
```

### 📦 Making Offline Packages from a Local File

Place the `.difypkg` file in `./difypkg/`, then run:

```bash
docker compose run --rm packager --local "difypkg/my-plugin.difypkg"
```

### 📦 Output

Both the **original** and the **offline-packaged** file are saved to `./difypkg/`:

```text
difypkg/
  langgenius-openai_0.3.2.difypkg            ← original (online)
  langgenius-openai_0.3.2-offline.difypkg     ← offline-ready
```

## ⚙️ Configuration

All settings can be customised via the `.env` file (or environment variables):

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `DIFY_PLUGIN_DAEMON_VERSION` | `0.5.3` | Docker image tag for the official daemon image. Also used to download the `dify-plugin` CLI binary. |
| `MARKETPLACE_API_URL` | `https://marketplace.dify.ai` | Dify Marketplace API URL |
| `GITHUB_API_URL` | `https://github.com` | GitHub URL (set for GitHub Enterprise) |
| `PIP_INDEX_URL` | `https://pypi.org/simple` | PyPI mirror URL (e.g. `https://mirrors.aliyun.com/pypi/simple` for Chinese users) |

## ⚙️ How It Works

1. `docker compose run` starts the official `dify-plugin-daemon` container.
   - The entrypoint is overridden to `uv run scripts/packager.py`.
   - `./scripts/` is bind-mounted read-only; `./bin/` and `./difypkg/` are mounted read-write.
2. Inside the container the script:
   - Downloads the plugin (or reads a local file).
   - Saves the **original** `.difypkg` to `./difypkg/`.
   - Detects whether the plugin uses `pyproject.toml` or `requirements.txt`:
     - **pyproject.toml** — injects `environments` (current OS + Python) and removes `[dependency-groups]` from `pyproject.toml`, runs `uv lock` to pin exact versions, exports the pinned list via `uv export`, downloads wheels via `uv run python -m pip download`, patches the `[tool.uv]` section with `no-index = true` and `find-links = ["./wheels/"]`, then deletes `uv.lock` (required because `--no-index` and `--frozen` are conflicting options in uv).
     - **requirements.txt** — downloads wheels via `uv run python -m pip download`, then prepends `--no-index --find-links=./wheels/`.
   - Downloads the `dify-plugin` CLI binary from GitHub (cached across runs).
   - Repacks the plugin with `dify-plugin plugin package`.

## ⚙️ Dify Platform Settings

To install offline-packaged plugins, you may need to adjust these Dify `.env` settings:

- `FORCE_VERIFYING_SIGNATURE=false` — Allow installing unsigned plugins.
- `ENFORCE_LANGGENIUS_PLUGIN_SIGNATURES=false` — Allow installing unsigned official plugins.
- `PLUGIN_MAX_PACKAGE_SIZE=524288000` — Allow plugins up to 500 MB.
- `NGINX_CLIENT_MAX_BODY_SIZE=500M` — Raise the Nginx upload limit.

## 🖥️ Running Locally (without Docker)

If you are running the **Dify Plugin Daemon locally** (not as a container), you can invoke the packager script directly on your machine instead of using Docker.

See **[docs/local-usage.md](docs/local-usage.md)** for the full instructions.

## 🙏 Acknowledgements

This project was inspired by [junjiem/dify-plugin-repackaging](https://github.com/junjiem/dify-plugin-repackaging). Thanks to [@junjiem](https://github.com/junjiem) for the original idea and implementation.
