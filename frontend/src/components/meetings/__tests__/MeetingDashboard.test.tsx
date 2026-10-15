import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MeetingDashboard } from "../MeetingDashboard";

describe("MeetingDashboard normal mode", () => {
  it("directs browser users to the native desktop workflow", async () => {
    render(<MeetingDashboard />);

    expect(await screen.findByText(/Meetings need the native desktop app/)).toBeDefined();
    expect(screen.queryByText("Recording")).toBeNull();
    expect(screen.queryByText("Live transcript")).toBeNull();
    expect(screen.queryByText("Detected questions")).toBeNull();
    expect(screen.queryByRole("button", { name: /start/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "Request permissions" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Open system settings" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Recheck" })).toBeNull();
  });

  it("keeps meeting continuation unavailable in browser mode", async () => {
    render(<MeetingDashboard />);

    expect(await screen.findByText(/Browser mode cannot request meeting capture permissions/)).toBeDefined();
    expect(screen.getByRole("button", { name: "Continue to consent" })).toBeDisabled();
  });
});
