import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MeetingDashboard } from "../MeetingDashboard";

describe("MeetingDashboard normal mode", () => {
  it("does not present fabricated recording content", () => {
    render(<MeetingDashboard />);

    expect(screen.getByText(/Native desktop capture and backend wiring are required/)).toBeDefined();
    expect(screen.queryByText("Recording")).toBeNull();
    expect(screen.queryByText("Live transcript")).toBeNull();
    expect(screen.queryByText("Detected questions")).toBeNull();
    expect(screen.queryByRole("button", { name: /start/i })).toBeNull();
  });

  it("keeps required capture controls unavailable", () => {
    render(<MeetingDashboard />);

    expect(screen.getByRole("button", { name: "Continue to consent" })).toBeDisabled();
    expect(screen.getByText(/does not record/i)).toBeDefined();
  });
});
