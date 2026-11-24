/** Mirrors `backend/app/api/chats/schemas.py` (JSON field names are snake_case on purpose). */

export type ChatFilter = "all" | "unread" | "tenants" | "contractors";

export type Direction = "inbound" | "outbound";
export type DeliveryStatus = "sent" | "delivered" | "read" | "failed";
export type PersonKind = "tenant" | "contractor" | "owner" | "other";

export interface ChatItem {
  chat_key: string;
  name: string | null;
  person_kind: PersonKind | null;
  last_message_id: string;
  last_at: string;
  last_text: string;
  last_kind: string | null;
  last_direction: Direction;
  last_delivery: DeliveryStatus | null;
  last_pending: boolean;
  unread: number;
  cursor: string;
}

export interface ChatQuote {
  id: string;
  text: string;
}

export interface ChatAttachment {
  id: string;
  filename: string | null;
  mime_type: string;
  size_bytes: number;
  url: string;
}

export interface ChatMessage {
  id: string;
  direction: Direction;
  sent_at: string;
  text: string;
  kind: string | null;
  delivery_status: DeliveryStatus | null;
  error: string | null;
  suspicious: boolean;
  suspicious_reason: string | null;
  reply_to: ChatQuote | null;
  attachments: ChatAttachment[];
  pending: boolean;
}

export interface ChatThread {
  chat_key: string;
  name: string | null;
  person_kind: PersonKind | null;
  case_id: string | null;
  messages: ChatMessage[];
}
