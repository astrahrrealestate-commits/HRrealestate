"""Message RAG package: conversational chunking, indexing, and hybrid retrieval."""

from app.tools.message_rag.chunker import (
    compute_content_hash,
    format_context_header,
    format_message_line,
    should_start_new_chunk,
)
from app.tools.message_rag.gate import should_index_message
from app.tools.message_rag.indexer import index_message
from app.tools.message_rag.search import (
    MessageChunkHit,
    get_message_window,
    get_thread_timeline,
    search_messages,
)

__all__ = [
    "MessageChunkHit",
    "compute_content_hash",
    "format_context_header",
    "format_message_line",
    "get_message_window",
    "get_thread_timeline",
    "index_message",
    "search_messages",
    "should_index_message",
    "should_start_new_chunk",
]
