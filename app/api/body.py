"""Bounded request-body reading for unauthenticated public endpoints (verification needs the body first)."""

from fastapi import HTTPException, Request


async def read_capped(request: Request, limit: int) -> bytes:
    """Read at most `limit` bytes; 413 as soon as the declared or streamed size exceeds it (chunked bodies too)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="payload too large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="payload too large")
        chunks.append(chunk)
    return b"".join(chunks)
