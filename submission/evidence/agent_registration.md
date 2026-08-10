# Agent Bricks registration — Weather MCP Server (external tool)

**Status: not deployed yet.** This is the one workspace-dependent item in the
submission. The app has not been deployed to a Databricks workspace, so no
screenshot of the external-MCP configuration or an agent-playground trace exists
yet — and none is fabricated here.

What `evidence/local_run_log.txt` *does* prove is that the exact endpoint the
agent would call is live and serving `tools/list` over streamable HTTP with all
six tools (plus a real `tools/call`), so the deployable artifact is verified;
only the workspace step is pending.

Per the reviewer's ask: *"Add proof that the Agent Bricks agent was registered to
your MCP server (screenshot of the external MCP tool configuration or an agent
playground trace hitting your deployed app URL)."*

## Exact steps to complete registration (from the repo README)

1. **Deploy the MCP server app** (source folder `mcp_server/`, app.yaml +
   requirements.txt in `code/`):
   - CLI: `databricks apps create mcp-weather-server`, sync `mcp_server/` to the
     workspace, then `databricks apps deploy mcp-weather-server`.
   - UI: *Apps → Create app → Connect to Git provider → repo → source folder
     `mcp_server/` → Create → Deploy.*
   - Name it `mcp-weather-server` — names starting with `mcp-` are recognized by
     the workspace as MCP servers.
2. Note the app URL. The MCP endpoint is
   `https://<mcp-weather-server-app-url>/mcp` (streamable HTTP).
3. Open **Agent Bricks → Create agent** and add a model of your choice.
4. Add the MCP server as an **external tool**: paste the `/mcp` URL above and
   complete the OAuth client pairing Agent Bricks guides you through (same as the
   Day-3 Alpaca MCP registration).
5. Paste **`agent_config/system_prompt.md`** into the **System prompt** field.
6. The six tools appear in the agent's tool list automatically (their exact
   `inputJsonSchema` is in `agent_config/tools.md`).

## Once deployed, capture these and drop them into this folder

- A screenshot of the external MCP tool configuration showing the app URL + the
  six tools; or
- An agent-playground trace calling one of the tools against the live app URL.
