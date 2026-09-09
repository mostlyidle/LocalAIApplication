import { z } from "zod";

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const healthSchema = z.object({
  status: z.string(),
  ollama: z.object({ status: z.string() }),
  chromadb: z.object({ status: z.string() }),
  database: z.object({ status: z.string() }),
});

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export const chatResponseSchema = z.object({
  response: z.string(),
  conversation_id: z.string(),
  agent_type: z.string(),
  tool_calls: z.array(z.unknown()).optional(),
});

export const conversationSummarySchema = z.object({
  id: z.string(),
  title: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const conversationsListSchema = z.object({
  conversations: z.array(conversationSummarySchema),
});

export const conversationDetailSchema = z.object({
  id: z.string(),
  title: z.string(),
  messages: z.array(z.unknown()),
});

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export const uploadResultSchema = z.object({
  id: z.string(),
});

export const documentListSchema = z.object({
  documents: z.array(z.unknown()),
});

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
  sql: z.string(),
  explanation: z.string(),
  results: sqlResultSetSchema.optional(),
});

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

export const sqlConnectionsSchema = z.object({
  connections: z.array(z.object({ name: z.string(), url: z.string() })),
});

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
      metadata: z.record(z.string(), z.unknown()),
    })
  ),
  query: z.string(),
  collection: z.string(),
});

export const ragIngestSchema = z.object({
  message: z.string(),
  chunks: z.number(),
});

export const ragCollectionsSchema = z.object({
  collections: z.array(z.object({ name: z.string(), count: z.number() })),
});

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

export const toolsListSchema = z.object({
  tools: z.array(z.object({ name: z.string(), description: z.string() })),
});
