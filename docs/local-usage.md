<!-- omit in toc -->
# Running Locally (without Docker)

> [!NOTE]
> The primary and recommended way to use this tool is via Docker Compose, as described in the [main README](../README.md).  
> This guide is for cases where you are running the **Dify Plugin Daemon locally** (not as a container) and want to run the packager on the same machine.

- [✅ Prerequisites](#-prerequisites)
- [📝 Quick Start](#-quick-start)
- [⚙️ Configuration](#️-configuration)

## ✅ Prerequisites

- [`uv`](https://docs.astral.sh/uv/) available in your `PATH`
- Internet access (to download plugins and Python packages)

> [!IMPORTANT]
> Wheels are downloaded for the CPU architecture of the machine running this tool.
> Make sure you run it on the same architecture (amd64 / arm64) as your Dify Plugin Daemon.

## 📝 Quick Start

Clone the repository and run the script directly from the repository root with `uv run`:

```bash
git clone https://github.com/kurokobo/dify-plugin-offline-packager.git
cd dify-plugin-offline-packager
```

```bash
# From Dify Marketplace
uv run scripts/packager.py --marketplace "langgenius/openai:0.3.2"

# From GitHub Releases
uv run scripts/packager.py --github "junjiem/dify-plugin-agent-mcp_sse:0.2.4:agent-mcp_sse.difypkg"

# From a local file  (place it in ./difypkg/ first)
uv run scripts/packager.py --local "difypkg/my-plugin.difypkg"
```

The script resolves all paths relative to the **current working directory**, so always run it from the repository root.

Both the **original** and the **offline-packaged** file are saved to `./difypkg/`:

```text
difypkg/
  langgenius-openai_0.3.2.difypkg            ← original (online)
  langgenius-openai_0.3.2-offline.difypkg     ← offline-ready
```

## ⚙️ Configuration

Settings can be provided as environment variables (same as the Docker-based workflow):

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `DIFY_PLUGIN_DAEMON_VERSION` | `0.5.3` | Version of the `dify-plugin` CLI binary to download. Should match your locally running Plugin Daemon. |
| `MARKETPLACE_API_URL` | `https://marketplace.dify.ai` | Dify Marketplace API URL |
| `GITHUB_API_URL` | `https://github.com` | GitHub URL (set for GitHub Enterprise) |
| `PIP_INDEX_URL` | `https://pypi.org/simple` | PyPI mirror URL |
