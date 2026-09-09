import { describe, it, expect } from "vitest";
import {
  API_BASE,
  API_V1,
  WS_BASE,
  WS_CHAT,
  MAX_FILE_SIZE,
  ACCEPTED_FILE_TYPES,
  AGENT_LABELS,
  AGENT_COLORS,
} from "../constants";

describe("constants", () => {
  it("API_BASE defaults to empty string for same-origin proxy", () => {
    expect(API_BASE).toBe("");
  });

  it("API_V1 includes /api/v1 suffix", () => {
    expect(API_V1).toContain("/api/v1");
  });

  it("WS_BASE defaults to backend WebSocket address", () => {
    expect(WS_BASE).toBe("ws://localhost:8000");
  });

  it("WS_CHAT includes chat stream path", () => {
    expect(WS_CHAT).toContain("/api/v1/chat/stream");
  });

  it("MAX_FILE_SIZE is 50MB", () => {
    expect(MAX_FILE_SIZE).toBe(50 * 1024 * 1024);
  });

  it("ACCEPTED_FILE_TYPES includes common formats", () => {
    expect(ACCEPTED_FILE_TYPES).toContain(".pdf");
    expect(ACCEPTED_FILE_TYPES).toContain(".docx");
    expect(ACCEPTED_FILE_TYPES).toContain(".csv");
    expect(ACCEPTED_FILE_TYPES).toContain(".png");
  });

  it("AGENT_LABELS has expected entries", () => {
    expect(AGENT_LABELS.chat).toBe("Chat");
    expect(AGENT_LABELS.sql).toBe("SQL Agent");
    expect(AGENT_LABELS.rag).toBe("RAG Agent");
  });

  it("AGENT_COLORS has expected entries", () => {
    expect(AGENT_COLORS.chat).toContain("blue");
    expect(AGENT_COLORS.sql).toContain("emerald");
  });
});
