export type MeetingPhase = "preflight" | "consent" | "live" | "review";
export type CaptureSource = "microphone" | "system";

export interface CapabilityCheck {
  id: string;
  label: string;
  detail: string;
  passed: boolean;
  required: boolean;
  state?: "granted" | "denied" | "not_determined" | "not_applicable" | "unknown";
}

export interface AudioSourceState {
  source: CaptureSource;
  label: string;
  detail: string;
  connected: boolean;
  level: number;
  droppedFrames?: number;
}

export interface TranscriptLine {
  id: string;
  source: CaptureSource;
  text: string;
  timestamp: string;
}

export interface DetectedQuestion {
  id: string;
  question: string;
  answer: string;
  confidence: "high" | "medium";
}

export interface MeetingFixture {
  title: string;
  startedAt: string;
  durationSeconds: number;
  transcript: TranscriptLine[];
  questions: DetectedQuestion[];
}

export interface MeetingController {
  mode: "normal" | "design-preview";
  phase: MeetingPhase;
  capabilities: CapabilityCheck[];
  isLoading: boolean;
  error: string | null;
  meeting: MeetingFixture;
  sources: AudioSourceState[];
  consentGiven: boolean;
  setConsent: (given: boolean) => void;
  beginConsent: () => void;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  reset: () => Promise<void>;
  recheck: () => Promise<void>;
  requestPermissions: () => Promise<void>;
  openPermissionSettings: () => Promise<void>;
}
