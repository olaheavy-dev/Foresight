import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { affordabilityResponse, answerScript, clarifyScript, errorScript, uid, WORKSPACE_ID } from "@/test/workspaceFixtures";
import { Workspace } from "./Workspace";

class RO {
  observe() {}
  disconnect() {}
}

class FakeEventSource {
  static all: FakeEventSource[] = [];
  readyState = 1;
  listeners = new Map<string, ((e: Event) => void)[]>();
  constructor(public url: string) {
    FakeEventSource.all.push(this);
  }
  addEventListener(type: string, fn: (e: Event) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() {
    this.readyState = 2;
  }
  emit(type: string, data: unknown, id: string) {
    const e = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: id });
    for (const fn of this.listeners.get(type) ?? []) fn(e);
  }
  play(script: { event: string; data: unknown }[], from = 0, to = script.length) {
    script.slice(from, to).forEach((s, i) => this.emit(s.event, s.data, String(from + i + 1)));
  }
}

const THREAD = uid("thr", 3);
const RUN = uid("run", 3);
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, "", "/workspace");
  FakeEventSource.all = [];
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("EventSource", FakeEventSource);
  fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/threads") return new Response(JSON.stringify({ thread_id: THREAD }), { status: 201 });
    if (url.endsWith("/messages")) return new Response(JSON.stringify({ run_id: RUN }), { status: 202 });
    if (url.startsWith("/api/responses/")) return new Response(JSON.stringify(affordabilityResponse()), { status: 200 });
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
});

const props = {
  workspaceId: WORKSPACE_ID,
  firstName: "Sam",
  locale: "en-GB",
  timeZone: "Europe/London",
  currency: "GBP",
  initialQuestion: null,
  flags: { auditTrail: true, checkedAdvice: true },
};

async function askViaComposer(text: string) {
  fireEvent.change(screen.getByLabelText("Ask a question"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(FakeEventSource.all).toHaveLength(1));
}

describe("AI Workspace", () => {
  it("opens on the welcome state with four starters and a pinned question box", () => {
    render(<Workspace {...props} />);
    expect(screen.getByRole("heading", { name: "Ask anything about your money." })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Start with a question" }).querySelectorAll("li")).toHaveLength(4);
    expect(screen.getByLabelText("Ask a question")).toBeInTheDocument();
  });

  it("streams the steps, then shows the checked answer and remembers the thread", async () => {
    render(<Workspace {...props} />);
    await askViaComposer("Can I afford a trip in December?");
    const es = FakeEventSource.all[0];
    expect(es.url).toBe(`/api/runs/${RUN}/events`);
    const [, init] = fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/messages"))!;
    expect(JSON.parse(init.body)).toMatchObject({ text: "Can I afford a trip in December?", client_msg_id: expect.any(String) });

    const script = answerScript(affordabilityResponse(), "Can I afford a one-off trip in December?");
    act(() => es.play(script, 0, 6));
    expect(screen.getByRole("heading", { name: "Checking before you see it" })).toBeInTheDocument();
    expect(screen.getByText("Verifier rejected a draft")).toBeInTheDocument();
    expect(screen.getAllByText(/Checking: Can I afford a one-off trip in December\?/).length).toBeGreaterThan(0);

    act(() => es.play(script, 6));
    expect(await screen.findByRole("heading", { level: 1, name: /pay for it after your 27 November payday/ })).toBeInTheDocument();
    expect(es.readyState).toBe(2);
    // Follow-up chips come from the answer's ask actions.
    expect(screen.getByRole("button", { name: "What if it costs more?" })).toBeEnabled();
    const stored = JSON.parse(sessionStorage.getItem(`foresight.workspace.threads.${WORKSPACE_ID}`)!);
    expect(stored[0].threadId).toBe(THREAD);
    expect(stored[0].turns[0].run.responseId).toBe(affordabilityResponse().response_id);
  });

  it("reopens a stored thread from its snapshot without re-running the agents", async () => {
    const { unmount } = render(<Workspace {...props} />);
    await askViaComposer("Can I afford a trip in December?");
    act(() => FakeEventSource.all[0].play(answerScript(affordabilityResponse(), "q")));
    await screen.findByRole("heading", { level: 1, name: /27 November payday/ });
    const key = JSON.parse(sessionStorage.getItem(`foresight.workspace.threads.${WORKSPACE_ID}`)!)[0].key;
    unmount();

    FakeEventSource.all = [];
    window.history.replaceState(null, "", `/workspace?thread=${key}`);
    render(<Workspace {...props} />);
    expect(await screen.findByRole("heading", { level: 1, name: /27 November payday/ })).toBeInTheDocument();
    expect(FakeEventSource.all).toHaveLength(0);
    expect(fetchMock).toHaveBeenCalledWith(`/api/responses/${affordabilityResponse().response_id}`, expect.anything());
  });

  it("offers the clarifying options as buttons", async () => {
    render(<Workspace {...props} />);
    await askViaComposer("Can I afford a trip?");
    act(() => FakeEventSource.all[0].play(clarifyScript()));
    expect(screen.getByRole("heading", { name: "Which trip did you mean?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "A one-off trip" })).toBeEnabled();
  });

  it("an engine failure says so, shows no figures and offers to try again", async () => {
    render(<Workspace {...props} />);
    await askViaComposer("How does next month look?");
    act(() => FakeEventSource.all[0].play(errorScript()));
    expect(screen.getByRole("alert")).toHaveTextContent("The forecast engine didn’t respond.");
    expect(screen.getByRole("alert")).toHaveTextContent("No figures were shown, because none were checked.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("a question that can't be posted fails honestly instead of spinning", async () => {
    fetchMock.mockImplementation(async () => new Response("{}", { status: 503 }));
    render(<Workspace {...props} />);
    fireEvent.change(screen.getByLabelText("Ask a question"), { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Foresight couldn’t take the question right now.");
    expect(FakeEventSource.all).toHaveLength(0);
  });

  it("asks the ?q= question once on arrival", async () => {
    render(<Workspace {...props} initialQuestion="Why is my spending up?" />);
    await waitFor(() => expect(FakeEventSource.all).toHaveLength(1));
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).endsWith("/messages"))).toHaveLength(1);
  });
});
