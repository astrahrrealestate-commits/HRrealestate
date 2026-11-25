/** What the inbox's Send button does with a draft. */

export type SendResult = { ok?: boolean; status: string; message: string };

const ALREADY_DECIDED =
  "This draft was already decided or replaced. Nothing was sent. Reload the inbox to see the current state.";

/**
 * A draft with a pending approval is decided and nothing else. A refusal (already decided, rejected, held) is never
 * retried as a typed reply: that would send a cancelled or held draft, or send an approved one a second time.
 * `reply` is only for a thread with no approval to decide.
 */
export async function approveOrReply(actions: {
  approve: (() => Promise<SendResult>) | undefined;
  reply: () => Promise<SendResult>;
}): Promise<SendResult> {
  if (!actions.approve) return actions.reply();
  const decided = await actions.approve();
  if (decided.status === "already_decided") return { ...decided, ok: false, message: ALREADY_DECIDED };
  return decided;
}
