import { fireEvent, render, screen } from "@testing-library/react";
import { AvatarMenu, initials } from "./AvatarMenu";

describe("AvatarMenu", () => {
  it("derives initials from the profile name", () => {
    expect(initials("Test Person")).toBe("TP");
    expect(initials("Mononym")).toBe("M");
    expect(initials("  ")).toBe("?");
  });

  it("opens with the button and closes on Escape, returning focus", () => {
    render(<AvatarMenu name="Test Person" subtitle="Demo profile · fictional data" />);
    const button = screen.getByRole("button", { name: /account menu/i });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Switch profile" })).toBeVisible();
    expect(screen.getByRole("radiogroup")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });
});
