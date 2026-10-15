import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { Transactions } from "./Transactions";

const U = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const page = (narration: string) => ({
  workspace_id: `wsp_${U}`,
  total: 1,
  limit: 100,
  offset: 0,
  items: [
    {
      transaction_id: `txn_${U}`,
      account_id: `acct_${U}`,
      posted_on: "2026-10-12",
      narration,
      channel: "card",
      amount: { kind: "money", minor: -350, currency: "GBP", display: "−£3.50", precision: "exact" },
    },
  ],
});
const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

describe("Transactions", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("never lets a slow answer for an older search overwrite a newer one (Codex review on #41)", async () => {
    let releaseOld: () => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const q = new URL(url, "http://x").searchParams.get("q");
        if (!url.includes("/api/transactions")) return new Response("{}", { status: 404 });
        if (q === "old")
          return new Promise<Response>((resolve) => (releaseOld = () => resolve(reply(page("Old result")))));
        return reply(page(q === "new" ? "New result" : "Everything"));
      }),
    );
    render(<Transactions tab="all" readOnly={false} locale="en-GB" />);
    await screen.findByText("Everything");
    const search = screen.getByPlaceholderText("Search payee or description");

    fireEvent.change(search, { target: { value: "old" } });
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).includes("q=old"))).toBe(true));
    fireEvent.change(search, { target: { value: "new" } });
    await screen.findByText("New result");

    releaseOld();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText("New result")).toBeInTheDocument();
    expect(screen.queryByText("Old result")).not.toBeInTheDocument();
  });
});
