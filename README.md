# MCP-Learning

A personal learning log for the [Model Context Protocol (MCP)](https://modelcontextprotocol.io), an open standard for connecting AI applications to tools, data and services.

This repo collects my experiments building MCP servers, clients and integrations in Python and TypeScript.

## Projects

| Project | Type | Language | Description | Status |
| ------- | ---- | -------- | ----------- | ------ |
| [project_1](./project_1) | Script (warm-up) | Python | Calls the [OpenSky Network](https://openskynetwork.github.io/opensky-api/rest.html) REST API and prints live flights over Switzerland as a readable table. A Python and REST API refresher before wrapping an API as an MCP server. Run with `pip install requests` then `python project_1/main.py` | ✅ Done |

<!--
Example row:
| [weather-server](./weather-server) | Server | Python | Exposes a tool that fetches weather forecasts | ✅ Done |
Status options: 🚧 In progress · ✅ Done · 💤 Paused
-->

## Prerequisites

- **Python 3.10+** with [uv](https://docs.astral.sh/uv/) (recommended) or pip
- **Node.js 18+** and npm
- **Git**
- An MCP client for testing, such as [Claude Desktop](https://claude.ai/download), Claude Code or the MCP Inspector

## Setup

Each project lives in its own folder with its own dependencies. See that project's README for specifics.

**Python projects**

```bash
cd <project-folder>
uv sync            # or: pip install -r requirements.txt
uv run <script>.py
```

**TypeScript projects**

```bash
cd <project-folder>
npm install
npm run build
```

**Testing a server with the MCP Inspector**

```bash
npx @modelcontextprotocol/inspector <command-to-start-server>
```

## Learning goals

### Fundamentals
- [ ] Understand MCP architecture (hosts, clients, servers)
- [ ] Understand transports (stdio and Streamable HTTP)
- [ ] Learn the core primitives: tools, resources and prompts

### Servers
- [ ] Build a basic server in Python
- [ ] Build a basic server in TypeScript
- [ ] Expose tools with typed inputs and outputs
- [ ] Expose resources and resource templates
- [ ] Define reusable prompts
- [ ] Debug servers with the MCP Inspector
- [ ] Connect a server to Claude Desktop or Claude Code

### Clients
- [ ] Build a client that connects to a server and lists its capabilities
- [ ] Call tools from a client
- [ ] Integrate an LLM into a client to choose and call tools

### Integrations
- [ ] Wrap a public REST API as an MCP server
- [ ] Connect to a database
- [ ] Work with the local file system
- [ ] Handle authentication and secrets safely

### Advanced
- [ ] Run a remote server over HTTP
- [ ] Explore sampling, elicitation and roots
- [ ] Add error handling, logging and tests
