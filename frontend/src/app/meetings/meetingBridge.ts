import { API_V1 } from "@/lib/constants";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { AudioSourceState, CapabilityCheck, DetectedQuestion, TranscriptLine } from "@/types/meeting";

type EventName = "capture-status" | "capture-meter" | "transport-status" | "meeting-status" | "backend-event" | "degraded" | "backpressure";
type EventPayload = AudioSourceState | TranscriptLine | DetectedQuestion | { message: string; error?: string; status?: string; phase?: string; meeting_id?: string; type?: string; source?: string; rms?: number; peak?: number; running?: boolean; frames_buffered?: number; dropped_frames?: number; question_id?: string; text?: string; answer?: string; citations?: string[]; segment_id?: string; start_ms?: number; end_ms?: number };

export function isNativeMeetingHost() { return typeof window !== "undefined" && Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__); }
const object = (value: unknown): Record<string, unknown> => typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
const text = (value: unknown): value is string => typeof value === "string";
const number = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const source = (value: unknown): value is "microphone" | "system" => value === "microphone" || value === "system";
export function permissionReady(platform: string | undefined, available: boolean, native: boolean, state: string | undefined, allowsNotApplicable = false) { const windows = platform?.toLowerCase() === "windows"; return available && native && (state === "granted" || allowsNotApplicable && state === "not_applicable" || windows && state === "unknown"); }

export async function checkNativeCapabilities(): Promise<CapabilityCheck[]> {
  if (!isNativeMeetingHost()) return [{ id: "desktop", label: "Native desktop capture", detail: "Open this page in the Tauri desktop app", passed: false, required: true }];
  const capabilities = await invoke<{ platform?: string; systemMix?: boolean; sources?: Array<{ source?: string; available?: boolean; native?: boolean; limitation?: string }> }>("get_capabilities");
  const permissions = await invoke<{ microphone?: { state?: string }; screenRecording?: { state?: string } }>("get_permissions");
  const mic = capabilities.sources?.find((item) => item.source === "microphone"); const sys = capabilities.sources?.find((item) => item.source === "system");
  const micPermission = permissions.microphone?.state === "granted" ? "granted" : permissions.microphone?.state === "notApplicable" ? "not_applicable" : "unknown";
  const screenPermission = permissions.screenRecording?.state === "granted" ? "granted" : permissions.screenRecording?.state === "notApplicable" ? "not_applicable" : "unknown";
  return [
    { id: "microphone", label: "Microphone permission", detail: mic?.limitation ?? `Permission: ${micPermission}`, passed: permissionReady(capabilities.platform, Boolean(mic?.available), Boolean(mic?.native), micPermission), required: true, state: micPermission as CapabilityCheck["state"] },
    { id: "system", label: "System audio permission", detail: sys?.limitation ?? `Permission: ${screenPermission}${capabilities.systemMix ? "; non-meeting sound may be included" : ""}`, passed: permissionReady(capabilities.platform, Boolean(sys?.available), Boolean(sys?.native), screenPermission, true), required: true, state: screenPermission as CapabilityCheck["state"] },
  ];
}

export async function requestNativePermissions() { if (!isNativeMeetingHost()) throw new Error("Native permissions are unavailable in a browser."); await invoke("request_permissions", { kind: "all" }); }
export async function openNativePermissionSettings() { if (!isNativeMeetingHost()) throw new Error("Native permission settings are unavailable in a browser."); await invoke("open_permission_settings", { kind: "all" }); }
export async function ensureMeetingReady(meetingId: string) { const controller = new AbortController(); const timeout = window.setTimeout(() => controller.abort(), 5000); try { const response = await fetch(`${API_V1}/health/ready`, { method: "GET", headers: { "Content-Type": "application/json", "X-Meeting-Id": meetingId }, signal: controller.signal }); if (!response.ok) throw new Error(`Meeting readiness returned ${response.status}.`); const result = await response.json() as { meeting_ready?: boolean; ready?: boolean; reason?: string }; if (result.meeting_ready !== true && result.ready !== true) throw new Error(result.reason || "The meeting is not ready for native capture."); } finally { window.clearTimeout(timeout); } }
async function api<T>(path: string, options: RequestInit): Promise<T> { const response = await fetch(`${API_V1}${path}`, { ...options, headers: { "Content-Type": "application/json", ...options.headers } }); if (!response.ok) throw new Error(`Meeting service returned ${response.status}.`); return response.json() as Promise<T>; }
export async function createConsentedMeeting(): Promise<{ id: string; status: string }> { return api("/meetings", { method: "POST", body: JSON.stringify({ consent_policy_version: "meeting-consent-v1", consent_attested_at: new Date().toISOString() }) }); }
export async function startNativeCapture() { await invoke("start_capture", { request: { source: "microphone", deviceId: null } }); await invoke("start_capture", { request: { source: "system", deviceId: null } }); }
export async function stopNativeCapture() { await invoke("stop_capture", { source: "microphone" }); await invoke("stop_capture", { source: "system" }); }
export async function startMeetingTransport(meetingId: string) { if (!isNativeMeetingHost()) throw new Error("Native meeting transport is unavailable in a browser."); await invoke("start_meeting_transport", { request: { meetingId, backendUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000" } }); }
export async function stopMeetingTransport(): Promise<{ phase?: string; error?: string }> { if (!isNativeMeetingHost()) return {}; return invoke("stop_meeting_transport"); }
export async function stopMeeting(meetingId: string) { return api(`/meetings/${meetingId}/stop`, { method: "POST", body: JSON.stringify({}) }); }
export async function deleteMeeting(meetingId: string) { return api(`/meetings/${meetingId}`, { method: "DELETE" }); }
export async function stopMeetingResources(meetingId: string) { await stopMeetingTransport().catch(() => undefined); await stopNativeCapture().catch(() => undefined); await stopMeeting(meetingId).catch(() => undefined); }

export type MeetingEventSubscription = (() => void) & { ready: Promise<void> };

export function listenToMeetingEvents(handlers: Partial<Record<EventName, (payload: EventPayload) => void>>): MeetingEventSubscription {
  let cancelled = false; let cleanupRequested = false; let cleanups: Array<() => void> = [];
  const runCleanups = () => { if (!cleanupRequested) return; cleanups.splice(0).forEach((unlisten) => unlisten()); };
  const cleanup = (() => { if (cleanupRequested) return; cleanupRequested = true; cancelled = true; runCleanups(); void subscription.ready.then(runCleanups, runCleanups); }) as MeetingEventSubscription;
  const subscription = cleanup; subscription.ready = Promise.resolve(); if (!isNativeMeetingHost()) return subscription;
  const names: Record<EventName, string> = { "capture-status": "capture://status", "capture-meter": "capture://meter", "transport-status": "meeting://transport-status", "meeting-status": "meeting://status", "backend-event": "meeting://backend-event", degraded: "meeting://degraded", backpressure: "meeting://backpressure" };
  const registrations = (Object.keys(handlers) as EventName[]).map((name) => listen<unknown>(names[name], ({ payload }) => { if (!cancelled) handlers[name]?.(object(payload) as EventPayload); }));
  subscription.ready = Promise.all(registrations).then((unlisteners) => { cleanups = unlisteners; if (cancelled) runCleanups(); }, (error) => { cleanupRequested = true; cancelled = true; return Promise.all(registrations.map((registration) => registration.then((unlisten) => { cleanups.push(unlisten); }, () => undefined))).then(() => { runCleanups(); throw error; }); });
  return subscription;
}

export const adapters = { transportStatus(payload: unknown) { const item = object(payload); return { phase: text(item.phase) ? item.phase : "unknown", message: text(item.error) ? item.error : undefined }; }, meetingStatus(payload: unknown) { const item = object(payload); return { status: text(item.status) ? item.status : "unknown", meetingId: text(item.meeting_id) ? item.meeting_id : "" }; }, backpressure(payload: unknown) { const item = object(payload); const dropped = number(item.droppedFrames) ? item.droppedFrames : 0; return item.type === "captureDrop" && source(item.source) ? { kind: "capture" as const, source: item.source, droppedFrames: dropped, message: `${dropped || "Some"} audio frame${dropped === 1 ? " was" : "s were"} discarded and lost.` } : item.type === "processor" ? { kind: "processor" as const, message: "Processor queue is saturated; retrying while capture continues." } : null; }, sourceStatuses(payload: unknown): AudioSourceState[] { const item = object(payload); return [item.microphone, item.system].flatMap((value) => { const result = adapters.sourceStatus(value); return result ? [result] : []; }); }, sourceStatus(payload: unknown): AudioSourceState | null { const item = object(payload); return source(item.source) ? { source: item.source, label: item.source === "microphone" ? "You" : "System audio", detail: item.source === "system" ? "System audio; non-meeting sound may be included" : "Native microphone", connected: item.status === "active" || item.running === true, level: number(item.rms) ? Math.min(100, Math.round(item.rms * 100)) : 0, droppedFrames: number(item.droppedFrames) ? item.droppedFrames : 0 } : null; }, transcript(payload: unknown): TranscriptLine | null { const item = object(payload); return text(item.segment_id) && source(item.source) && text(item.text) && number(item.start_ms) && number(item.end_ms) ? { id: item.segment_id, source: item.source, text: item.text, timestamp: `${Math.round(item.start_ms / 1000)}s` } : null; }, question(payload: unknown): DetectedQuestion | null { const item = object(payload); return text(item.question_id) && text(item.text) ? { id: item.question_id, question: item.text, answer: "", confidence: "medium" } : null; }, answer(payload: unknown) { const item = object(payload); return text(item.question_id) && text(item.answer) ? { id: item.question_id, answer: item.answer, citations: Array.isArray(item.citations) && item.citations.every(text) ? item.citations : [] } : null; } };
