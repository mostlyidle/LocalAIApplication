import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "../MarkdownContent";

describe("MarkdownContent tables", () => {
  it("renders spaced, readable headers and cells inside a scrollable table", () => {
    const { container } = render(
      <MarkdownContent
        content={`| Region | sum_Revenue | Source rows |\n| --- | --- | --- |\n| North | 2350.0 | 2, 5, 8, 11 |`}
      />,
    );

    const table = screen.getByRole("table");
    const headers = screen.getAllByRole("columnheader");
    const cells = screen.getAllByRole("cell");

    expect(container.querySelector(".overflow-x-auto")).toContainElement(table);
    expect(table).toHaveClass("text-sm", "min-w-max");
    expect(headers[0]).toHaveClass("px-3", "py-2", "whitespace-nowrap");
    expect(cells[0]).toHaveClass("px-3", "py-2");
  });
});
