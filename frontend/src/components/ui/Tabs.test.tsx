import { fireEvent, render, screen } from "@testing-library/react";
import { Tabs } from "./Tabs";

const items = [
  { id: "overview", label: "Overview", content: <p>Overview body</p> },
  { id: "details", label: "Details", content: <p>Details body</p> },
  { id: "checked", label: "How it was checked", content: <p>Checked body</p> },
];

describe("Tabs", () => {
  beforeEach(() => window.history.replaceState(null, "", "/"));

  it("selects the first tab and hides the other panels", () => {
    render(<Tabs items={items} label="Answer" />);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Overview body")).toBeVisible();
    expect(screen.getByText("Details body")).not.toBeVisible();
  });

  it("moves with arrow keys, Home and End, wrapping, and syncs the hash", () => {
    render(<Tabs items={items} label="Answer" />);
    const overview = screen.getByRole("tab", { name: "Overview" });
    overview.focus();
    fireEvent.keyDown(overview, { key: "ArrowRight" });
    const details = screen.getByRole("tab", { name: "Details" });
    expect(details).toHaveAttribute("aria-selected", "true");
    expect(details).toHaveFocus();
    expect(window.location.hash).toBe("#details");
    fireEvent.keyDown(details, { key: "End" });
    expect(screen.getByRole("tab", { name: "How it was checked" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("tab", { name: "How it was checked" }), { key: "ArrowRight" });
    expect(overview).toHaveFocus();
    fireEvent.keyDown(overview, { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "How it was checked" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(screen.getByRole("tab", { name: "How it was checked" }), { key: "Home" });
    expect(overview).toHaveAttribute("aria-selected", "true");
  });

  it("only the selected tab is in the tab order", () => {
    render(<Tabs items={items} label="Answer" />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.tabIndex)).toEqual([0, -1, -1]);
  });

  it("opens the tab named in the URL hash", () => {
    window.history.replaceState(null, "", "/#checked");
    render(<Tabs items={items} label="Answer" />);
    expect(screen.getByRole("tab", { name: "How it was checked" })).toHaveAttribute("aria-selected", "true");
  });
});
