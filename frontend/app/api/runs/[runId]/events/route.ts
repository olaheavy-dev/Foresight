/**
 * Streams a run's events (SSE) from the backend to the browser. Route handlers take precedence
 * over the /api/* rewrite, and this one passes the stream through unbuffered: it marks it
 * `no-transform` so the server's gzip never holds events back until the run ends (which is what
 * the plain rewrite does), and it forwards Last-Event-ID so a reconnect resumes where it stopped.
 */
export const dynamic = "force-dynamic";

const API = process.env.API_BASE_URL ?? "http://backend:8000";
const RUN_ID = /^run_[0-9A-HJKMNP-TV-Z]{26}$/;

export async function GET(request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  if (!RUN_ID.test(runId)) return Response.json({ detail: "Not found" }, { status: 404 });
  const incoming = new URL(request.url);
  const upstreamUrl = new URL(`${API}/api/runs/${runId}/events`);
  const last = incoming.searchParams.get("last_event_id");
  if (last) upstreamUrl.searchParams.set("last_event_id", last);

  const headers = new Headers({ accept: "text/event-stream" });
  for (const name of ["cookie", "last-event-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, { headers, cache: "no-store", signal: request.signal });
  } catch {
    return Response.json({ detail: "The answer stream isn't available." }, { status: 502 });
  }
  if (!upstream.ok || !upstream.body) {
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      "x-accel-buffering": "no",
      connection: "keep-alive",
    },
  });
}
