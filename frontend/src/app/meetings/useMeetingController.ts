"use client";

import { useEffect, useRef, useState } from "react";
import type { AudioSourceState, CapabilityCheck, MeetingController, MeetingFixture, MeetingPhase } from "@/types/meeting";
import { adapters, checkNativeCapabilities, createConsentedMeeting, createMeetingStreamTicket, deleteMeeting, ensureMeetingReady, isNativeMeetingHost, listenToMeetingEvents, openNativePermissionSettings, requestNativePermissions, startMeetingTransport, startNativeCapture, stopMeeting, stopMeetingResources, stopMeetingTransport, stopNativeCapture } from "./meetingBridge";
import type { MeetingEventSubscription } from "./meetingBridge";

const emptyMeeting: MeetingFixture = { title: "Untitled meeting", startedAt: "", durationSeconds: 0, transcript: [], questions: [] };
const unavailable: AudioSourceState[] = [
  { source: "microphone", label: "You", detail: "Waiting for native microphone capture", connected: false, level: 0 },
  { source: "system", label: "System audio", detail: "Waiting for native system audio; non-meeting sound may be included", connected: false, level: 0 },
];

export function useMeetingController(): MeetingController {
  const [phase, setPhase] = useState<MeetingPhase>("preflight");
  const [capabilities, setCapabilities] = useState<CapabilityCheck[]>([]);
  const [sources, setSources] = useState(unavailable);
  const [meeting, setMeeting] = useState(emptyMeeting);
  const [consentGiven, setConsentGiven] = useState(false);
  const [isLoading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [meetingId, setMeetingId] = useState<string | null>(null);
  const meetingIdRef = useRef<string | null>(null);
  const eventSubscription = useRef<MeetingEventSubscription | null>(null);
  const generationRef = useRef(0);
  const startInFlightRef = useRef(false);
  const startupRef = useRef<{ generation: number; id: string | null; cancelled: boolean; completion: Promise<void> | null; rollback: Promise<void> | null } | null>(null);

  const rollbackStartup = (operation: NonNullable<typeof startupRef.current>) => { if (!operation.rollback) operation.rollback = (async () => { if (operation.id) { await stopMeetingResources(operation.id); await deleteMeeting(operation.id).catch(() => undefined); } })(); return operation.rollback; };

  useEffect(() => { void checkNativeCapabilities().then(setCapabilities).catch((cause: Error) => setError(cause.message)).finally(() => setLoading(false)); }, []);
  useEffect(() => {
    const subscription = listenToMeetingEvents({
      "capture-status": (payload) => { const updates = adapters.sourceStatuses(payload); if (updates.length) setSources((current) => current.map((item) => updates.find((update) => update.source === item.source) ?? item)); },
      "capture-meter": (payload) => { const source = adapters.sourceStatus(payload); if (source) setSources((current) => current.map((item) => item.source === source.source ? { ...item, level: source.level } : item)); },
      "transport-status": (payload) => { const status = adapters.transportStatus(payload); if (status.phase === "failed") setError(status.message ?? "Meeting transport failed."); },
      "meeting-status": (payload) => { const status = adapters.meetingStatus(payload); if (status.status === "active" && status.meetingId === meetingIdRef.current) setPhase("live"); if (status.status === "failed") setError(status.failureReason ?? "Meeting failed."); },
      "backend-event": (payload) => { const status = adapters.meetingStatus(payload); if (status.status === "active" && status.meetingId === meetingIdRef.current) setPhase("live"); if (status.status === "failed") setError(status.failureReason ?? "Meeting failed."); const transcript = adapters.transcript(payload); if (transcript) setMeeting((current) => ({ ...current, transcript: [...current.transcript, transcript] })); const question = adapters.question(payload); if (question) setMeeting((current) => ({ ...current, questions: [...current.questions, question] })); const answer = adapters.answer(payload); if (answer) setMeeting((current) => ({ ...current, questions: current.questions.map((item) => item.id === answer.id ? { ...item, answer: answer.answer } : item) })); const event = adapters.transportStatus(payload); if (event.message) setError(event.message); },
      degraded: (payload) => setError(adapters.transportStatus(payload).message ?? "Meeting processing is degraded."),
      backpressure: (payload) => { const notice = adapters.backpressure(payload); if (!notice) return; setError(notice.message); if (notice.kind === "capture") setSources((current) => current.map((item) => item.source === notice.source ? { ...item, droppedFrames: notice.droppedFrames } : item)); },
    });
    eventSubscription.current = subscription;
    return () => { subscription(); eventSubscription.current = null; };
  }, []);
  useEffect(() => () => { generationRef.current += 1; const operation = startupRef.current; if (operation && !operation.completion) operation.cancelled = true; else if (operation && !operation.cancelled) { operation.cancelled = true; void operation.completion?.then(() => rollbackStartup(operation)); } else { const id = meetingIdRef.current; if (id) void stopMeetingResources(id); } }, []);

  const beginConsent = () => { setError(null); setPhase("consent"); };
  const start = async () => {
    if (!consentGiven || !isNativeMeetingHost() || startInFlightRef.current) return;
    startInFlightRef.current = true;
    const generation = ++generationRef.current;
    const active = () => generationRef.current === generation;
    const ensureActive = () => { if (!active()) throw new Error("Meeting start cancelled."); };
    const operation = { generation, id: null as string | null, cancelled: false, completion: null as Promise<void> | null, rollback: null as Promise<void> | null };
    startupRef.current = operation;
    setLoading(true); setError(null);
    let createdId: string | null = null;
    const completion = (async () => { try { await eventSubscription.current?.ready; ensureActive(); await requestNativePermissions(); ensureActive(); const created = await createConsentedMeeting(); createdId = created.id; operation.id = createdId; ensureActive(); meetingIdRef.current = createdId; setMeetingId(createdId); await ensureMeetingReady(createdId); ensureActive(); const ticket = await createMeetingStreamTicket(createdId); ensureActive(); await startNativeCapture(); ensureActive(); await startMeetingTransport(createdId, ticket.ticket); ensureActive(); setMeeting({ ...emptyMeeting, startedAt: new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) }); setSources(unavailable); }
      catch (cause) { operation.cancelled = operation.cancelled || !active(); if (createdId) await rollbackStartup(operation); if (active()) { meetingIdRef.current = null; setMeetingId(null); setError(cause instanceof Error ? cause.message : "Could not start the meeting."); } }
      finally { startInFlightRef.current = false; if (active()) setLoading(false); if (startupRef.current === operation) startupRef.current = null; } })();
    operation.completion = completion;
    await completion;
  };
  const stop = async () => { if (!meetingId) return; setLoading(true); setError(null); let stopError: string | null = null; try { const status = await Promise.race([stopMeetingTransport(), new Promise<never>((_, reject) => window.setTimeout(() => reject(new Error("Meeting transport stop timed out.")), 5000))]); if (status.error) stopError = status.error; } catch (cause) { stopError = cause instanceof Error ? cause.message : "Meeting transport stop failed."; } try { await stopNativeCapture(); } catch (cause) { stopError ??= cause instanceof Error ? cause.message : "Native capture stop failed."; } try { const stopped = await stopMeeting(meetingId); if (stopped.status === "failed") stopError = stopped.failure_reason ?? "Meeting processing failed while stopping."; } catch (cause) { stopError ??= cause instanceof Error ? cause.message : "Backend meeting stop failed."; } if (stopError) setError(stopError); setPhase("review"); setLoading(false); };
  const reset = async () => { generationRef.current += 1; const operation = startupRef.current; const id = meetingIdRef.current; meetingIdRef.current = null; setMeetingId(null); if (operation && !operation.completion) operation.cancelled = true; if (operation?.completion) await operation.completion; else if (id) { await stopMeetingResources(id); await deleteMeeting(id).catch(() => undefined); } setMeeting(emptyMeeting); setSources(unavailable); setConsentGiven(false); setError(null); setPhase("preflight"); };

  const recheck = async () => { setLoading(true); setError(null); try { setCapabilities(await checkNativeCapabilities()); } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not check native readiness."); } finally { setLoading(false); } };
  const requestPermissions = async () => { setLoading(true); setError(null); try { await requestNativePermissions(); await recheck(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not request permissions."); setLoading(false); } };
  const openPermissionSettings = async () => { try { await openNativePermissionSettings(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not open permission settings."); } };
  return { mode: "normal", phase, capabilities, isLoading, error, meeting, sources, consentGiven, setConsent: setConsentGiven, beginConsent, start, stop, reset, recheck, requestPermissions, openPermissionSettings };
}
