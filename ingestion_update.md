# Ingestion Update

This document records the changes made for empty uploads directory detection and the related notification flow.

## What Was Added

- A reusable helper that checks whether `data/uploads/` contains supported files.
- A watchdog-based watcher that re-checks directory state on create, delete, and move events.
- An SSE notification stream for directory state changes.
- A startup check in FastAPI lifespan so empty uploads are detected immediately.
- A frontend SSE listener and modal to show and clear the "No documents found" notice.
- The missing `watchdog` dependency declaration.

## Old Behavior

Before this change:

- If you manually copied files into `data/uploads/`, the backend did not auto-ingest them just because they existed there.
- You had to run the ingest script/process separately to ingest those files.
- There was no explicit check for whether `data/uploads/` was empty.
- There was no event for "directory became empty" or "directory restored".
- The frontend had no UI hook for empty uploads directory state.

## New Behavior

The new flow is:

1. FastAPI starts.
2. The document watcher starts.
3. The backend scans `data/uploads/`.
4. If there are no supported files, it emits `NO_DOCUMENTS_IN_DIRECTORY`.
5. The frontend receives that event over SSE and opens a modal.
6. When a file is added, moved in, deleted, or moved out, the watcher rescans the directory.
7. If the directory transitions from non-empty to empty, the backend emits `NO_DOCUMENTS_IN_DIRECTORY`.
8. If the directory transitions from empty to non-empty, the backend emits `DOCUMENTS_RESTORED`.
9. The frontend receives `DOCUMENTS_RESTORED` and closes the modal automatically.

## File Responsibilities

### `src/main.py`

- Starts the `DocumentWatcher` during FastAPI lifespan.
- Runs the startup directory check after watcher startup.
- Keeps the app running if watcher startup or the directory scan fails.
- Registers the new notification router.

### `src/services/document_watcher.py`

- Monitors `data/uploads/` with `watchdog`.
- Handles:
  - `on_created`
  - `on_deleted`
  - `on_moved`
- Keeps an in-memory `was empty` state.
- Re-validates state against the filesystem before broadcasting changes.
- Triggers ingestion for supported stable files.

### `src/services/upload_directory_status.py`

- Contains the reusable directory scan helper.
- Counts supported upload files only.
- Keeps the file-extension filter in one place.

### `src/services/upload_directory_notifications.py`

- Stores the in-memory notification hub.
- Tracks subscribers for the SSE stream.
- Broadcasts:
  - `NO_DOCUMENTS_IN_DIRECTORY`
  - `DOCUMENTS_RESTORED`

### `src/api/notifications.py`

- Exposes `/api/events/stream`.
- Streams directory notifications to the frontend through SSE.

### `src/services/ingestion_service.py`

- Restores the watcher ingestion trigger entry point.
- Serializes ingestion per file path.
- Keeps watcher-triggered ingestion separate from the directory-state logic.

### `LocalMind_UI/src/components/Layout.jsx`

- Opens the SSE connection.
- Listens for directory notification events.
- Shows the "No Documents Found" modal.
- Dismisses the modal when `DOCUMENTS_RESTORED` arrives.

### `pyproject.toml`

- Adds `watchdog>=4.0` to project dependencies.

### `requirements.txt`

- Adds `watchdog>=4.0` for non-`pyproject` installs.

## Notification Payloads

### Empty Directory

```json
{
  "type": "NO_DOCUMENTS_IN_DIRECTORY",
  "message": "No documents found in the uploads directory.",
  "path": "data/uploads"
}
```

### Restored Directory

```json
{
  "type": "DOCUMENTS_RESTORED"
}
```

## State Tracking

The watcher keeps `_directory_has_supported_files` in memory.

Why:

- It avoids recomputing state logic twice in the same event path.
- It still rescans the filesystem before deciding whether the state changed.
- That gives a balance between efficiency and correctness if filesystem events are missed or arrive out of order.

## Modified Files

- `src/main.py`
- `src/services/document_watcher.py`
- `src/services/upload_directory_status.py`
- `src/services/upload_directory_notifications.py`
- `src/services/ingestion_service.py`
- `src/api/notifications.py`
- `LocalMind_UI/src/components/Layout.jsx`
- `pyproject.toml`
- `requirements.txt`

## Notes

- This change does not modify the query pipeline, embedding pipeline, vector store, or empty knowledge base detection logic.
- The empty uploads directory feature is separate from knowledge-base emptiness.
- No migration is required.
