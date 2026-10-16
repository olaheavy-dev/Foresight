// The Activity page's error state. The feed is fetched on the server, which Playwright can't
// intercept on the real stack, so the page itself is rendered here with the API failing.
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import ActivityPage from "../../../app/(app)/activity/page";

const PROFILE = {
  workspace_id: "wsp_01ARZ3NDEKTSV4RRFFQ69G5FAV",
  name: "Amara Nwosu",
  kind: "demo",
  country: "GB",
  home_currency: "GBP",
  locale: "en-GB",
  timezone: "Europe/London",
  data_version: 3,
  read_only: false,
};

vi.mock("@/lib/server", () => ({
  loadShell: async () => ({
    profile: PROFILE,
    features: [{ key: "activity", enabled: true, stage: 2, title: "Activity", suites: ["E-AUD"] }],
    options: {},
  }),
}));
vi.mock("@/lib/api", () => ({ fetchActivity: async () => null }));

describe("Activity page", () => {
  it("says Activity isn't available when the service fails, never an empty feed", async () => {
    render(await ActivityPage());
    expect(screen.getByRole("heading", { level: 1, name: "Activity" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Activity isn’t available right now");
    expect(screen.queryByText("No agent runs yet.", { exact: false })).not.toBeInTheDocument();
  });
});
