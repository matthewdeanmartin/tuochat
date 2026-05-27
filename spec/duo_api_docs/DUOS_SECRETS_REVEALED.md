# GitLab Duo Secrets Revealed: The `gitlab-lsp` API Map

This document breaks down how the `duo-cli` (from the `gitlab-lsp` project) actually communicates with GitLab's AI services. If you're building a custom Duo chat client, these are the endpoints and protocols you need.

______________________________________________________________________

## 1. Authentication

GitLab Duo uses standard Personal Access Tokens (PAT) or OAuth tokens. However, for "Agentic" features (Duo Workflow), it often upgrades these to a transient **Workflow Token**.

- **Workflow Token Request**:
  - **Endpoint**: `POST /api/v4/ai/duo_workflows/direct_access`
  - **Body**: `{"workflow_definition": "software_development", "root_namespace_id": "<gid>"}`
  - **Purpose**: Returns a short-lived token and `server_capabilities`.

______________________________________________________________________

## 2. Duo Chat: The "Classic" Interface

The classic Duo Chat is almost entirely **GraphQL** based.

### A. Sending a Message (`aiAction`)

The core mutation is `aiAction`. It has evolved across GitLab versions.

**Modern Template (17.5+):**

```graphql
mutation chat(
  $question: String!
  $resourceId: AiModelID
  $currentFileContext: AiCurrentFileInput
  $clientSubscriptionId: String
  $platformOrigin: String!
  $additionalContext: [AiAdditionalContextInput!]
) {
  aiAction(
    input: {
      chat: {
        resourceId: $resourceId
        content: $question
        currentFile: $currentFileContext
        additionalContext: $additionalContext
      }
      clientSubscriptionId: $clientSubscriptionId
      platformOrigin: $platformOrigin
    }
  ) {
    requestId
    errors
  }
}
```

- **`platformOrigin`**: Usually `jetbrains`, `vscode`, or `duo-cli`.
- **`resourceId`**: The Global ID (GID) of the project or group context (e.g., `gid://gitlab/Project/123`).
- **`additionalContext`**: Used for RAG (Retrieval-Augmented Generation). Categories include `FILE`, `SNIPPET`, `ISSUE`, `MERGE_REQUEST`.

### B. Streaming Responses (Action Cable)

GitLab Duo Chat streams responses back via **WebSockets** using Rails Action Cable.

- **Channel**: `AiCompletionResponseChannel`
- **Identifier**:
  ```json
  {
    "channel": "AiCompletionResponseChannel",
    "userId": "<user_gid>",
    "aiAction": "CHAT",
    "clientSubscriptionId": "<uuid>"
  }
  ```
- **Events**: You'll receive chunks of text which you must concatenate.

### C. Polling Fallback

If WebSockets fail, the client polls the `aiMessages` query using the `requestId` returned by the mutation.

```graphql
query getAiMessages($requestIds: [ID!], $roles: [AiMessageRole!]) {
  aiMessages(requestIds: $requestIds, roles: $roles) {
    nodes {
      content
      role
      timestamp
      extras {
        sources
      }
    }
  }
}
```

______________________________________________________________________

## 3. Agentic Chat: Duo Workflow

"Agentic" mode (the `build` and `plan` agents in `duo-cli`) uses a more complex **REST-heavy** flow.

### A. Starting a Workflow

- **Endpoint**: `POST /api/v4/ai/duo_workflows/workflows`
- **Payload**:
  ```json
  {
    "goal": "Explain this code",
    "workflow_definition": "chat",
    "environment": "ide",
    "project_id": "<id>",
    "agent_privileges": [1, 2]
  }
  ```
- **Returns**: A `workflow_id`.

### B. Communication via Events

Instead of a single request/response, the agent and user exchange **Events**.

- **Send Event**: `POST /api/v4/ai/duo_workflows/workflows/{workflow_id}/events`
- **Event Types**: `user_message`, `tool_response`, `stop`.

### C. The Workflow Executor

The `duo-cli` actually runs a local "Executor" (Node.js based) that:

1. Connects to the GitLab Rails API.
1. Manages local tool execution (like reading files, running tests).
1. Streams progress back to the UI.

______________________________________________________________________

## 4. Key Discovery Endpoints

- **Available Models**: `query { aiChatAvailableModels(rootNamespaceId: "...") { nodes { name modelId } } }`
- **Feature Flags**: `HEAD /api/v4/ai/duo_workflows/workflows/{id}` (Returns `x-gitlab-enabled-feature-flags` header).

______________________________________________________________________

## Summary for Chat Client Developers

| Feature | Protocol | Primary Endpoint |
| :--- | :--- | :--- |
| **Send Chat** | GraphQL | `mutation aiAction` |
| **Stream Chat** | WebSocket | `AiCompletionResponseChannel` |
| **List Models** | GraphQL | `query aiChatAvailableModels` |
| **Agents/Workflow** | REST | `/api/v4/ai/duo_workflows/workflows` |
| **Direct Access** | REST | `/api/v4/ai/duo_workflows/direct_access` |

**Pro Tip:** Always check the `instanceVersion` from `/api/v4/version` before choosing your GraphQL template!
