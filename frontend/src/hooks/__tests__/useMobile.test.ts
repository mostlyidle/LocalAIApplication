import { describe, it, expect, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useIsMobile } from "../use-mobile";

describe("useIsMobile", () => {
  it("returns false for desktop width", () => {
    Object.defineProperty(window, "innerWidth", { value: 1024, writable: true });
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });

  it("returns true for mobile width", () => {
    Object.defineProperty(window, "innerWidth", { value: 500, writable: true });
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it("returns false at exactly 768px", () => {
    Object.defineProperty(window, "innerWidth", { value: 768, writable: true });
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });

  it("returns true at 767px", () => {
    Object.defineProperty(window, "innerWidth", { value: 767, writable: true });
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });
});
