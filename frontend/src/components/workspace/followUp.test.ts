import { describe, expect, it } from "vitest";

import type { ThreadDetail, ThreadMessage } from "@/lib/ask";

import { findFollowUp, turnsFromThread } from "./Workspace";

const msg = (id: string, role: "user" | "assistant", responseId: string | null = null): ThreadMessage => ({
  message_id: id,
  role,
  text: role === "user" ? "Can I afford a holiday?" : "",
  standalone_question: null,
  run_id: null,
  response_id: responseId,
  created_at: "2026-10-14T10:00:00Z",
});

const thread = (messages: ThreadMessage[]): ThreadDetail => ({ thread_id: "thr_1", title: "t", messages });

describe("advice follow-ups (docs/06 §13)", () => {
  it("a second answer to a question is its follow-up and never replaces the answer", () => {
    const [turn] = turnsFromThread(
      thread([msg("m1", "user"), msg("m2", "assistant", "rsp_a"), msg("m3", "assistant", "rsp_b")]),
    );
    expect(turn.run.answer?.responseId).toBe("rsp_a");
    expect(turn.followUp?.responseId).toBe("rsp_b");
  });

  it("finds the follow-up after its answer, and never one from a later question", () => {
    const withFollowUp = thread([msg("m1", "user"), msg("m2", "assistant", "rsp_a"), msg("m3", "assistant", "rsp_b")]);
    expect(findFollowUp(withFollowUp, "rsp_a")).toBe("rsp_b");
    const later = thread([
      msg("m1", "user"),
      msg("m2", "assistant", "rsp_a"),
      msg("m3", "user"),
      msg("m4", "assistant", "rsp_c"),
    ]);
    expect(findFollowUp(later, "rsp_a")).toBeNull();
    expect(findFollowUp(withFollowUp, "rsp_missing")).toBeNull();
  });
});
