# GitLab Duo Research in `glab` CLI

The `glab` CLI project currently has three primary integration points for GitLab Duo, none of which utilize the GitLab GraphQL API for AI functionality directly within the codebase. Instead, it relies on REST and a separate binary.

## 1. `glab duo ask` (Classic)

- **Purpose**: Generates Git commands from natural language.
- **Implementation**: `internal/commands/duo/ask/ask.go`
- **API Protocol**: **REST API**
- **Endpoint**: `/api/v4/ai/llm/git_command`
- **Request Format**:
  ```json
  {
    "prompt": "<user prompt>",
    "model": "vertexai"
  }
  ```
- **Response Format**:
  ````json
  {
    "predictions": [
      {
        "candidates": [
          {
            "content": "Explanation and ```git command``` blocks"
          }
        ]
      }
    ]
  }
  ````
- **Note**: The code uses a Vertex AI-style JSON structure for both the request and response.

## 2. `glab duo cli` (Experimental)

- **Purpose**: Runs a dedicated GitLab Duo CLI for code assistance and autonomous actions.
- **Implementation**: `internal/commands/duo/cli/cli.go`
- **Protocol**: **Wrapper around a separate binary.**
- **Details**:
  - Downloads a binary named `duo-cli` from the GitLab Package Registry.
  - The `duo-cli` project is hosted at `https://gitlab.com/gitlab-org/editor-extensions/gitlab-lsp` (Project ID: `46519181`).
  - `glab` handles the download, update, and execution of this binary, passing through any arguments.
  - It sets an environment variable `GITLAB_DUO_DISTRIBUTION=glab`.

## 3. `glab mcp serve` (Experimental)

- **Purpose**: Exposes `glab` CLI commands as Model Context Protocol (MCP) tools for AI assistants (like Claude or the GitLab Duo Chat).
- **Implementation**: `internal/commands/mcp/serve/server.go`
- **Protocol**: **MCP (STDIO)**
- **Details**:
  - Dynamically registers `glab` commands marked with specific annotations as MCP tools.
  - When a tool is called, the MCP server executes the `glab` CLI itself as a subprocess.
  - This allows Duo (via the Duo Agent Platform) to "call" `glab` commands to interact with GitLab resources (issues, MRs, pipelines, etc.).

## GraphQL Findings

While the `glab` CLI uses GraphQL for other features (e.g., `workitems`), it **does not** appear to call any Duo-specific GraphQL mutations (like `aiAction`) or queries (like `aiChat`) directly.

Any Duo GraphQL functionality likely resides in the `duo-cli` binary or the GitLab server-side components.

### Relevant Files:

- `internal/commands/duo/ask/ask.go`: Implementation of `glab duo ask`.
- `internal/commands/duo/cli/cliutils/binary_manager.go`: Downloads the external Duo CLI.
- `internal/commands/mcp/serve/server.go`: The MCP server that enables Duo integration via tools.
