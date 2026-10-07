# ADR 0005: Google Drive (scope `drive.file`) for document filing

Status: accepted (2026-10-07)

## Context
Agent #9 (Document Filing) files tenant and contractor attachments (invoices, leases, quotes, photos) where Harjot
can find them. Harjot already works in Google Workspace, and we already depend on google-api-python-client and
google-auth for Gmail. A second storage product (SharePoint, Dropbox) would add a new vendor and new credentials.

## Decision
- **Google Drive API v3** through google-api-python-client, behind the `DriveStore` port (`app/storage/drive.py`),
  with `MemoryDrive` for tests and the simulator.
- OAuth scope **`drive.file` only**: the app can see and change only the files and folders it created itself. It
  cannot read or list the rest of Harjot's Drive. Credentials are a separate authorized-user file (not the Gmail
  ones), created for Harjot's account with this scope alone.
- Layout `EstateOS/<doc_type>/<YYYY>/`, file name rule v1 `YYYY-MM-DD_<doc_type>_<party>_<title>.<ext>`
  (`app/pipeline/document_policy.py`). Folders are created on demand and found again by name inside their parent,
  which `drive.file` limits to app-created folders.
- Idempotency: every upload carries `appProperties.estateos_attachment_id`. Filing looks it up before uploading,
  and the `documents` table is unique on `attachment_id`.
- Confidence below 0.80 → `documents.status = review` and the owner picks the type. Nothing is uploaded until then.

## Consequences
- Harjot sees the files in his Drive under `EstateOS/`. Moving them elsewhere in Drive is allowed: the app finds
  files by app property, not by path. If he renames or moves an app-created folder, a new one is created next time.
- Filing into Harjot's existing folders would need the full `drive` scope. That is a deliberate non-goal for
  Phase 1 (least privilege). Revisit with M3, when units from BRIXX allow per-unit folders, with a versioned naming
  rule v2.
- Rate limits and 5xx errors raise `DriveApiError(retryable=True)` for the DBOS step to retry
  (`app.storage.drive.is_transient`). Other errors fail the step and are visible in `make workflows`.
