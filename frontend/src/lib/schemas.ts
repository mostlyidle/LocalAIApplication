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
    target: z.string(),
    description: z.string(),
    default_for_target: z.boolean(),
    model_availability: z.record(z.string(), z.boolean().nullable()).optional(),
    inference: z.object({
      allowed_models: z.array(z.string()),
      defaults: z.object({ model: z.string(), temperature: z.number() }).passthrough(),
    }).passthrough().nullable(),
  }).passthrough()),
});

export const conversationSummarySchema = z.object({
  id: z.string(),
  title: z.string(),
  created_at: z.string(),
  last_message_at: z.string(),
  message_count: z.number(),
});

export const conversationsListSchema = z.array(conversationSummarySchema)
  .transform((conversations) => ({ conversations }));

export const conversationDetailSchema = z.object({
  id: z.string(),
  title: z.string(),
  messages: z.array(z.object({
    id: z.string(),
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

export const memoryDeleteAllSchema = z.object({
  deleted_count: z.number(),
  memory_epoch: z.number(),
  past_chat_recall_enabled: z.boolean(),
});

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

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

export const toolsListSchema = z.array(z.object({ name: z.string(), description: z.string() }))
  .transform((tools) => ({ tools }));
