import { beforeEach, describe, expect, it, vi } from "vitest";
import { adapters, createMeetingStreamTicket, ensureMeetingReady, listenToMeetingEvents, permissionReady, stopMeeting } from "../meetingBridge";
import { setCsrfToken } from "@/lib/auth-session";

const listen = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/event", () => ({ listen }));

describe("meeting bridge contracts", () => {
  beforeEach(() => { vi.restoreAllMocks(); listen.mockReset(); });

  it.each([false, true])("checks required backend meeting readiness: %s", async (ready) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ meeting_ready: ready }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    if (ready) await expect(ensureMeetingReady("m-1")).resolves.toBeUndefined();
    else await expect(ensureMeetingReady("m-1")).rejects.toThrow("not ready");
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/v1\/health\/ready$/), expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("requests a meeting stream ticket with the session CSRF token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ticket: "native-ticket" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    setCsrfToken("session-csrf");

    await expect(createMeetingStreamTicket("meeting-1")).resolves.toEqual({
      ticket: "native-ticket",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/v1\/meetings\/meeting-1\/stream-ticket$/),
      expect.objectContaining({
        credentials: "include",
        headers: expect.objectContaining({ "X-CSRF-Token": "session-csrf" }),
      }),
    );
    setCsrfToken(null);
  });

  it("allows optional health services to remain degraded when meeting_ready is true", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ meeting_ready: true, status: "degraded" }), { status: 200 })));
    await expect(ensureMeetingReady("m-1")).resolves.toBeUndefined();
  });

  it("rejects listener registration and unlistens successful listeners exactly once", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true });
    const unlisten = vi.fn();
    let rejectSecond!: (reason: Error) => void;
    listen.mockImplementationOnce(() => Promise.resolve(unlisten)).mockImplementationOnce(() => new Promise((_, reject) => { rejectSecond = reject; }));
    const subscription = listenToMeetingEvents({ "capture-status": vi.fn(), "capture-meter": vi.fn() });
    rejectSecond(new Error("listener failed"));
    await expect(subscription.ready).rejects.toThrow("listener failed");
    expect(unlisten).toHaveBeenCalledTimes(1);
  });

  it("cancels delayed registration and cleans up when it eventually resolves", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true });
    const unlisten = vi.fn(); let resolve!: (value: () => void) => void;
    listen.mockImplementation(() => new Promise((res) => { resolve = res; }));
    const subscription = listenToMeetingEvents({ "capture-status": vi.fn() });
    subscription(); resolve(unlisten); await subscription.ready;
    expect(unlisten).toHaveBeenCalledTimes(1);
  });

  it("allows unknown Windows microphone permission when native capability is usable", () => {
    expect(permissionReady("windows", true, true, "unknown")).toBe(true);
    expect(permissionReady("macos", true, true, "unknown")).toBe(false);
    expect(permissionReady("windows", true, true, "not_applicable", true)).toBe(true);
  });

  it("maps camelCase native dropped frame counts as capture drops", () => {
    expect(adapters.sourceStatus({ source: "microphone", running: true, droppedFrames: 7 })).toMatchObject({ droppedFrames: 7, connected: true });
    expect(adapters.sourceStatus({ source: "microphone", running: true, dropped_frames: 7 })).toMatchObject({ droppedFrames: 0 });
  });

  it("distinguishes native capture loss from processor queue saturation", () => {
    expect(adapters.backpressure({ type: "captureDrop", source: "system", droppedFrames: 4 })).toMatchObject({ kind: "capture", droppedFrames: 4, message: expect.stringContaining("discarded and lost") });
    expect(adapters.backpressure({ type: "processor" })).toEqual({ kind: "processor", message: "Processor queue is saturated; retrying while capture continues." });
  });

  it("keeps transport errors and rejects malformed processor payloads", () => {
    expect(adapters.transportStatus({ phase: "failed", error: "final-event drain timed out" })).toEqual({ phase: "failed", message: "final-event drain timed out" });
    expect(adapters.transportStatus({ type: "error", message: "audio frame was rejected" })).toEqual({ phase: "unknown", message: "audio frame was rejected" });
    expect(adapters.transportStatus({ type: "degraded", message: "transcription unavailable" })).toEqual({ phase: "unknown", message: "transcription unavailable" });
    expect(adapters.transcript({ segment_id: "s1", source: "system", text: "hello", start_ms: 10, end_ms: 20 })).not.toBeNull();
    expect(adapters.transcript({ segment_id: "s1", source: "system", text: "hello", start_ms: 10 })).toBeNull();
  });

  it("preserves a backend meeting failure reason", () => {
    expect(adapters.meetingStatus({ status: "failed", meeting_id: "m-1", failure_reason: "final persistence failed" })).toEqual({
      status: "failed",
      meetingId: "m-1",
      failureReason: "final persistence failed",
    });
  });

  it("rejects malformed stop responses at the API boundary", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "failed", failure_reason: 42 }), { status: 200 }),
    ));

    await expect(stopMeeting("meeting-1")).rejects.toThrow();
  });
});
