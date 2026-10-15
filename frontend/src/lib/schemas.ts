import { z } from "zod";

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const healthSchema = z.object({
  status: z.string(),
  services: z.array(z.object({
    name: z.string(),
    healthy: z.boolean(),
    message: z.string().optional(),
  })),
  meeting_ready: z.boolean(),
}).transform((data) => {
  const serviceStatus = (name: string) => ({
    status: data.services.find((service) => service.name === name)?.healthy
      ? "healthy" : "unhealthy",
  });
  return {
    ...data,
    ollama: serviceStatus("ollama"),
    qdrant: serviceStatus("qdrant"),
    database: serviceStatus("app_database"),
  };
});

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export const chatResponseSchema = z.object({
  content: z.string(),
  conversation_id: z.string(),
  agent_used: z.string().nullable(),
  tool_calls: z.array(z.unknown()).optional(),
  execution: z.unknown().optional(),
});

export const agentCatalogSchema = z.object({
  agents: z.array(z.object({
    name: z.string(),
    display_name: z.string().optional().default(""),
    target: z.string(),
    description: z.string(),
    default_for_target: z.boolean(),
    system_prompt: z.string().optional().default(""),
    is_custom: z.boolean().optional().default(false),
    archived: z.boolean().optional().default(false),
    model_availability: z.record(z.string(), z.boolean().nullable()).optional(),
    inference: z.object({
      allowed_models: z.array(z.string()),
      defaults: z.object({ model: z.string(), temperature: z.number() }).passthrough(),
    }).passthrough().nullable(),
  }).passthrough()),
});
export type AgentProfile = z.infer<typeof agentCatalogSchema>["agents"][number];

export const conversationSummarySchema = z.object({
  id: z.string(),
  title: z.string(),
  created_at: z.string(),
  last_message_at: z.string(),
  message_count: z.number(),
  exclude_from_memory: z.boolean().optional().default(false),
});

export const conversationsListSchema = z.array(conversationSummarySchema)
  .transform((conversations) => ({ conversations }));

export const conversationDetailSchema = z.object({
  id: z.string(),
  title: z.string(),
  exclude_from_memory: z.boolean().optional().default(false),
  messages: z.array(z.object({
    id: z.string(),
    client_turn_id: z.string().nullable().optional(),
    role: z.enum(["user", "assistant", "system", "tool"]),
    content: z.string(),
    agent_type: z.string().nullable().optional(),
    execution: z.unknown().nullable().optional(),
    created_at: z.string(),
    tool_calls: z.array(z.object({
      id: z.string(),
      tool_name: z.string(),
      tool_input: z.unknown().optional(),
      tool_output: z.string().nullable().optional(),
      duration_ms: z.number().nullable().optional(),
    }).passthrough()).default([]),
  }).passthrough()),
});

// ---------------------------------------------------------------------------
// Account memory
// ---------------------------------------------------------------------------

export const memorySchema = z.object({
  id: z.string(),
  kind: z.enum(["preference", "fact", "project_decision"]),
  content: z.string(),
  project_scope: z.string().nullable(),
  source_conversation_id: z.string().nullable(),
  source_message_id: z.string().nullable(),
  origin_agent: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  expires_at: z.string().nullable(),
  revision: z.number(),
});

export const memoryListSchema = z.object({
  memories: z.array(memorySchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});

export const memorySettingsSchema = z.object({
  memory_enabled: z.boolean(),
  past_chat_recall_enabled: z.boolean(),
});

export const conversationMemorySettingsSchema = z.object({
  exclude_from_memory: z.boolean(),
});

export const memoryDeleteAllSchema = z.object({
  deleted_count: z.number(),
  memory_epoch: z.number(),
  past_chat_recall_enabled: z.boolean(),
});

export const actionItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().nullable(),
  status: z.enum(["next", "in_progress", "done"]),
  priority: z.enum(["low", "normal", "high"]),
  due_date: z.string().nullable(),
  source_type: z.enum(["chat", "meeting", "document", "github"]).nullable(),
  source_id: z.string().nullable(),
  source_repository_id: z.string().nullable(),
  source_quote: z.string().nullable(),
  revision: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
});
export const actionItemListSchema = z.object({ items: z.array(actionItemSchema), total: z.number() });
export type ActionItemRecord = z.infer<typeof actionItemSchema>;

export const actionItemProposalSchema = z.object({
  source_type: z.enum(["chat", "meeting", "document"]),
  source_id: z.string(),
  source_title: z.string(),
  suggestions: z.array(z.object({
    title: z.string(),
    description: z.string().nullable(),
    priority: z.enum(["low", "normal", "high"]),
    due_date: z.string().nullable(),
    source_quote: z.string(),
  })),
});
export type ActionItemSuggestion = z.infer<typeof actionItemProposalSchema>["suggestions"][number];
export const meetingSourceListSchema = z.array(z.object({
  id: z.string(), status: z.string(), created_at: z.string(),
}));

export const githubConnectionSchema = z.object({
  configured: z.boolean(),
  connected: z.boolean(),
  login: z.string().nullable(),
  expires_at: z.string().nullable(),
  install_url: z.string().nullable(),
});
export const githubAuthorizationSchema = z.object({ authorization_url: z.string().url() });
export type GitHubConnection = z.infer<typeof githubConnectionSchema>;
export const githubRepositorySchema = z.object({
  repository_id: z.string(),
  full_name: z.string(),
  html_url: z.string().url(),
  default_branch: z.string(),
  is_private: z.boolean(),
  selected: z.boolean(),
});
export const githubRepositoryListSchema = z.object({ repositories: z.array(githubRepositorySchema) });
export type GitHubRepository = z.infer<typeof githubRepositorySchema>;
const githubProjectItemSchema = z.object({
  number: z.number(), title: z.string(), body: z.string(), state: z.string(), html_url: z.string().url(),
  author: z.string().nullable(), updated_at: z.string().nullable(), labels: z.array(z.string()),
});
export const githubProjectOverviewSchema = z.object({
  repository_id: z.string(), repository: z.string(),
  issues: z.array(githubProjectItemSchema),
  pull_requests: z.array(githubProjectItemSchema.extend({ draft: z.boolean(), head_sha: z.string().nullable() })),
});
export const githubPullDetailSchema = z.object({
  repository_id: z.string(), number: z.number(), title: z.string(), body: z.string(), state: z.string(),
  html_url: z.string().url(), head_sha: z.string().nullable(),
  files: z.array(z.object({ filename: z.string(), status: z.string(), additions: z.number(), deletions: z.number(), patch: z.string().nullable(), html_url: z.string().url().nullable() })),
  checks: z.array(z.object({ name: z.string(), status: z.string(), conclusion: z.string().nullable(), html_url: z.string().url().nullable() })),
  files_truncated: z.boolean(), checks_truncated: z.boolean(),
});
export const githubIssueProposalSchema = z.object({
  repository_id: z.string(), source_id: z.string(), source_title: z.string(),
  suggestions: actionItemProposalSchema.shape.suggestions,
});
export const githubIssueWriteSchema = z.object({ number: z.number(), title: z.string(), html_url: z.string().url() });
export const githubCommentWriteSchema = z.object({ id: z.string(), html_url: z.string().url().nullable() });
export type GitHubProjectOverview = z.infer<typeof githubProjectOverviewSchema>;
export type GitHubPullDetail = z.infer<typeof githubPullDetailSchema>;
export type GitHubIssueProposal = z.infer<typeof githubIssueProposalSchema>;

export type MemoryRecord = z.infer<typeof memorySchema>;
export type MemorySettings = z.infer<typeof memorySettingsSchema>;

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export const uploadResultSchema = z.object({
  id: z.string(),
});

export const documentListSchema = z.array(z.object({
  id: z.string(),
  filename: z.string(),
  format: z.string(),
  size_bytes: z.number(),
  content_sha256: z.string().nullable().optional(),
  status: z.enum(["pending", "processing", "completed", "failed"]),
  created_at: z.string(),
})).transform((documents) => ({ documents }));

export const analysisResultSchema = z.object({
  document_id: z.string(),
  filename: z.string(),
  format: z.string(),
  text: z.string(),
  tables: z.array(
    z.object({
      page: z.number().nullable().optional(),
      headers: z.array(z.string()),
      rows: z.array(z.array(z.string())),
    })
  ),
  metadata: z.record(z.string(), z.unknown()),
  page_count: z.number().nullable().optional(),
  word_count: z.number(),
  status: z.string(),
  answer: z.string().nullable().optional(),
});

// ---------------------------------------------------------------------------
// SQL
// ---------------------------------------------------------------------------

export const sqlResultSetSchema = z.object({
  columns: z.array(z.string()),
  rows: z.array(z.array(z.unknown())),
  row_count: z.number(),
});

export const sqlQueryResponseSchema = z.object({
  generated_sql: z.string(),
  explanation: z.string(),
  columns: z.array(z.string()),
  rows: z.array(z.array(z.unknown())),
  row_count: z.number(),
}).transform((data) => ({
  sql: data.generated_sql,
  explanation: data.explanation,
  results: { columns: data.columns, rows: data.rows, row_count: data.row_count },
}));

export const sqlExecuteResponseSchema = z.object({
  sql: z.string(),
  result: sqlResultSetSchema,
}).transform((data) => data.result);

export const sqlSchemaResponseSchema = z.object({
  database: z.string(),
  tables: z.array(
    z.object({
      name: z.string(),
      columns: z.array(
        z.object({
          name: z.string(),
          type: z.string(),
          nullable: z.boolean(),
          primary_key: z.boolean(),
        })
      ),
    })
  ),
});

export const sqlConnectionsSchema = z.array(z.object({ name: z.string(), url: z.string() }))
  .transform((connections) => ({ connections }));

export const sqlAddConnectionSchema = z.object({
  name: z.string(),
  status: z.string(),
});

// ---------------------------------------------------------------------------
// RAG
// ---------------------------------------------------------------------------

export const ragSearchResultSchema = z.object({
  results: z.array(
    z.object({
      content: z.string(),
      score: z.number(),
      score_type: z.string().optional(),
      metadata: z.record(z.string(), z.unknown()),
    })
  ),
  query: z.string(),
  total_results: z.number(),
  retrieval: z.record(z.string(), z.unknown()).optional(),
});

export const ragIngestSchema = z.object({
  document_id: z.string(),
  collection: z.string(),
  chunks_ingested: z.number(),
}).transform((data) => ({ ...data, chunks: data.chunks_ingested }));

export const ragCollectionsSchema = z.array(z.object({
  name: z.string(), document_count: z.number(),
})).transform((collections) => ({
  collections: collections.map((collection) => ({
    name: collection.name, count: collection.document_count,
  })),
}));

export const ragContainerFileSchema = z.object({
  id: z.string(),
  relative_path: z.string(),
  status: z.string(),
  chunk_count: z.number(),
  size_bytes: z.number(),
  last_error: z.string().nullable().optional(),
});

export const ragContainerSchema = z.object({
  name: z.string(),
  display_name: z.string(),
  file_count: z.number(),
  indexed_file_count: z.number(),
  staged_file_count: z.number(),
  queued_file_count: z.number(),
  processing_file_count: z.number(),
  failed_file_count: z.number(),
  chunk_count: z.number(),
});

export const ragContainersSchema = z.array(ragContainerSchema);

export const ragContainerUploadResultSchema = z.object({
  files: z.array(ragContainerFileSchema),
  failures: z.array(z.object({ relative_path: z.string(), message: z.string() })),
});

export const ragContainerLoadSchema = z.object({ queued: z.number().int().nonnegative() });
export const deleteResultSchema = z.object({ deleted: z.boolean() });

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

export const toolsListSchema = z.array(z.object({ name: z.string(), description: z.string() }))
  .transform((tools) => ({ tools }));
