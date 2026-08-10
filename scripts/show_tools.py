"""
scripts/show_tools.py

Print the exact `tools/list` response the Weather MCP Server advertises — the
same payload MCP Inspector shows when you connect to the running server, and
the same payload Agent Bricks reads to populate the agent's tool list.

This is the reproducibility script behind `submission/evidence/tools_list.json`
(built by `scripts/build_submission.py`).

Modes:
    python scripts/show_tools.py              # pretty JSON to stdout (default)
    python scripts/show_tools.py --compact    # single-line JSON
    python scripts/show_tools.py --markdown   # Markdown table (for tools.md/README)

The introspection is offline: it builds the FastMCP app and lists its tools
directly, so no server process and no network are needed.

What the output proves (grading criteria):
  - at least 3 distinct tools exposed via @mcp.tool  -> 6 tools, listed here
  - tools have clear docstrings with Args/Returns    -> each `description`
    below is the tool's docstring, verbatim
  - exact `inputJsonSchema` for manual/Agent Bricks review
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Make `import weather_mcp_server` resolve from the sibling mcp_server/ folder.
SERVER_DIR = Path(__file__).resolve().parent.parent / "mcp_server"
sys.path.insert(0, str(SERVER_DIR))

import weather_mcp_server as srv  # noqa: E402


async def tools_list() -> dict:
    """Return the tools/list result dict exactly as the MCP server emits it."""
    tools = await srv.mcp.list_tools()
    return {
        "tools": [
            {
                "name": tool.name,
                "description": (tool.description or "").strip(),
                "inputSchema": tool.inputSchema,
            }
            for tool in tools
        ]
    }


def render_markdown(tools: dict) -> str:
    rows = []
    for tool in tools["tools"]:
        props = tool["inputSchema"].get("properties", {})
        required = tool["inputSchema"].get("required", [])
        arg_text = ", ".join(
            f"`{name}`{'' if name in required else ' (optional)'}"
            for name in props
        )
        desc = tool["description"].splitlines()[0] if tool["description"] else ""
        rows.append(f"| `{tool['name']}` | {arg_text} | {desc} |")
    header = "| Tool | Args | Purpose |\n| --- | --- | --- |"
    return header + "\n" + "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump the MCP tools/list payload.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--compact", action="store_true", help="single-line JSON")
    group.add_argument("--markdown", action="store_true", help="Markdown table")
    args = parser.parse_args()

    tools = asyncio.run(tools_list())

    if args.markdown:
        print(render_markdown(tools))
    elif args.compact:
        print(json.dumps(tools, ensure_ascii=False))
    else:
        print(json.dumps(tools, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
