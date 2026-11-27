# REAL PROJECT MATERIAL — MCP Adapter and Bridge

Source: `src/job_agent/agent_runtime/mcp_adapter.py` and `src/job_agent/agent_runtime/mcp_bridge.py`.

`MCPToolAdapter` converts an MCP tool JSON schema into a Pydantic input model, builds a synchronous handler around `MCPClientBridge.call_tool_sync`, and registers the tool in the existing `ToolRegistry`. Registered MCP tools use typed output, a configurable timeout, and `ToolEffect.READ_ONLY`.

`StdioMCPClientBridge` launches the MCP server with the current Python interpreter, maintains a persistent asynchronous `ClientSession` on a background event loop, and exposes synchronous list and call methods through `asyncio.run_coroutine_threadsafe`. Structured MCP content is returned directly; MCP errors raise explicitly.
