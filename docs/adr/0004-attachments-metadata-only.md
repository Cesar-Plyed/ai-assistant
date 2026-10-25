# ADR 0004 — Attachments persist as metadata
Status: accepted. Chats store id/path/sha256/index, never base64; model-ready derivatives are
regenerated from disk. Only the current turn's pixels are re-sent to limit tokens and cost.
