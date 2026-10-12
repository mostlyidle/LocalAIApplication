export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  agentType?: string;
  toolCalls?: ToolCall[];
  attachments?: string[];
  timestamp: string;
  execution?: AgentExecutionResult;
}

export interface AgentExecutionResult {
  agent?: string;
  answer?: string;
  artifacts?: Record<string, unknown>;
  limitations?: string[];
  metadata?: Record<string, unknown>;
}

export interface ChatTaskOptions {
  agent_name?: string;
  collection?: string;
  symbol?: string;
  workspace_path?: string;
  context?: string;
  workflow?: Record<string, unknown>;
  inference?: {
    model?: string;
    temperature?: number;
  };
}

export interface AgentCapability {
  name: string;
  target: string;
  description: string;
  default_for_target: boolean;
  inference: {
    allowed_models: string[];
    defaults: { model: string; temperature: number };
    limits: { temperature: { minimum: number; maximum: number } };
  } | null;
}

export interface ToolCall {
  id: string;
  toolName: string;
  toolInput: string;
  toolOutput?: string;
  durationMs?: number;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages?: ChatMessage[];
}

export interface ChatRequest {
  message: string;
  conversation_id?: string;
  attachments?: string[];
}

export interface ChatResponse {
  response: string;
  conversation_id: string;
  agent_type: string;
  tool_calls?: ToolCall[];
}

export interface StreamEvent {
  type: "token" | "tool_call" | "tool_result" | "done" | "error";
  content?: string;
  tool?: string;
  input?: Record<string, unknown>;
  output?: string;
  metadata?: Record<string, unknown>;
  error?: string;
}
