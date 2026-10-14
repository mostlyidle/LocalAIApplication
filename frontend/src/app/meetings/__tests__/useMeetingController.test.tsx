import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const bridge = vi.hoisted(() => ({
  checkNativeCapabilities: vi.fn(async () => []),
  requestNativePermissions: vi.fn(async () => undefined),
  createConsentedMeeting: vi.fn(),
  createMeetingStreamTicket: vi.fn(async () => ({ ticket: "test-stream-ticket" })),
  ensureMeetingReady: vi.fn(async () => undefined),
  startNativeCapture: vi.fn(async () => undefined),
  startMeetingTransport: vi.fn(async () => undefined),
  stopMeetingTransport: vi.fn(async () => ({})),
  stopNativeCapture: vi.fn(async () => undefined),
  stopMeeting: vi.fn(async () => ({ status: "stopped", failure_reason: null as string | null })),
  stopMeetingResources: vi.fn(async () => undefined),
  deleteMeeting: vi.fn(async () => undefined),
  isNativeMeetingHost: vi.fn(() => true),
  listenToMeetingEvents: vi.fn(() => Object.assign(vi.fn(), { ready: Promise.resolve() })),
  adapters: {},
}));
vi.mock("../meetingBridge", () => bridge);

import { useMeetingController } from "../useMeetingController";

describe("meeting startup cancellation", () => {
  beforeEach(() => { vi.clearAllMocks(); bridge.createConsentedMeeting.mockResolvedValue({ id: "m-race", status: "created" }); });

  it("rolls back a meeting created after unmount without starting capture", async () => {
    let resolveMeeting!: (value: { id: string; status: string }) => void;
    bridge.createConsentedMeeting.mockImplementationOnce(() => new Promise((resolve) => { resolveMeeting = resolve; }));
    const { result, unmount } = renderHook(() => useMeetingController());

    act(() => { result.current.setConsent(true); });
    let start!: Promise<void>;
    act(() => { start = result.current.start(); });
    await vi.waitFor(() => expect(bridge.createConsentedMeeting).toHaveBeenCalled());
    unmount();
    resolveMeeting({ id: "m-race", status: "created" });
    await start;

    expect(bridge.startNativeCapture).not.toHaveBeenCalled();
    expect(bridge.startMeetingTransport).not.toHaveBeenCalled();
    expect(bridge.stopMeetingResources).toHaveBeenCalledWith("m-race");
  });

  it("shows the persisted backend failure when stopping", async () => {
    bridge.stopMeeting.mockResolvedValueOnce({ status: "failed", failure_reason: "final persistence failed" });
    const { result } = renderHook(() => useMeetingController());

    act(() => { result.current.setConsent(true); });
    await act(async () => { await result.current.start(); });
    await act(async () => { await result.current.stop(); });

    expect(result.current.error).toBe("final persistence failed");
    expect(result.current.phase).toBe("review");
  });

  it.each(["readiness", "native start"] as const)("reset during %s does not continue startup", async (blockedAt) => {
    let release!: () => void;
    if (blockedAt === "readiness") bridge.ensureMeetingReady.mockImplementationOnce(() => new Promise<undefined>((resolve) => { release = () => resolve(undefined); }));
    else bridge.startNativeCapture.mockImplementationOnce(() => new Promise<undefined>((resolve) => { release = () => resolve(undefined); }));
    const { result } = renderHook(() => useMeetingController());
    act(() => { result.current.setConsent(true); });
    let start!: Promise<void>;
    act(() => { start = result.current.start(); });
    await vi.waitFor(() => expect(blockedAt === "readiness" ? bridge.ensureMeetingReady : bridge.startNativeCapture).toHaveBeenCalled());
    const reset = result.current.reset();
    release();
    await Promise.all([start, reset]);
    expect(bridge.startMeetingTransport).not.toHaveBeenCalled();
    expect(bridge.stopMeetingResources).toHaveBeenCalledWith("m-race");
  });
});
