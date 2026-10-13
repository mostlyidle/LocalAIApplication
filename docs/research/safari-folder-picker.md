# Safari folder picker research

Updated: 2026-10-13

## Finding

The app's folder control uses `<input type="file" webkitdirectory multiple accept="...">` (see `frontend/src/components/rag/ContainerUploader.tsx`). WebKit has supported directory upload in macOS Safari since Safari 11.1, so this is not a general Safari limitation.

I checked the same fixture folder in Safari 27.0.1 on macOS 27.0.1 with a minimal local page. The unfiltered `<input type="file" webkitdirectory multiple>` let me select the folder and returned both files with correct `webkitRelativePath` values. An otherwise identical input with the app's kind of `accept` filter left **Upload** disabled for the same folder. This A/B points to the `accept` attribute on the directory input as the cause. The earlier app E2E used that filtered input, so it did not demonstrate a Safari directory-picker limitation.

**Fix applied:** removed `accept` from only the folder input and kept it on the regular file input. `accept` is only a picker hint; it is not validation. The backend validates file types and returns per-file failures, so unsupported files continue to be rejected there.

WebKit bug [284457](https://bugs.webkit.org/show_bug.cgi?id=284457), reported against Safari 17.5 and 18.0, describes picker behavior around `webkitdirectory`. The report remains **NEW** (last modified 2025-01-22), and comments disagree on whether it reproduces a directory-selection failure. It does not describe the `accept` interaction found in this Safari 27.0.1 A/B test, so it is not needed to explain this result.

WebKit's instructions for choosing a folder by navigating into it and pressing **Open** are specifically for **iOS Safari 18.4**, where WebKit added directory-picker support. They do not document macOS Safari's picker behavior. WebKit announced directory upload in macOS Safari 11.1, and described `webkitdirectory` as opening directory selection.

## What to try next

1. Complete: Safari app E2E selected root and nested `.txt` files. The UI staged `knowledge-base/root-note.txt` and `knowledge-base/reference/nested-note.txt` with paths preserved; both indexed (2 chunks total), and search returned their fixture contents. The chat RAG profile's index selector exposed the new container.
2. Native Finder folder drag-and-drop remains unconfirmed. Finder-to-Safari drag attempts in the UI automation did not visibly reach the browser drop handler. A focused Vitest regression test passes for recursive directory entries and preservation of root and nested relative paths.

The app-level folder upload, indexing, and search now pass in Safari 27.0.1/macOS 27.0.1. Chat generation was not tested because the configured `qwen2.5:7b` model is not installed; index selection was verified.

## Sources

- [WebKit: New WebKit Features in Safari 11.1](https://webkit.org/blog/8216/new-webkit-features-in-safari-11-1/) — directory upload support on macOS and iOS.
- [WebKit: Clipboard API Improvements](https://webkit.org/blog/8170/clipboard-api-improvements/) — explains `input.webkitdirectory` support added in WebKit revision r221177 and says iOS also supports dropping folders from Files.
- [WebKit: WebKit Features in Safari 18.4](https://webkit.org/blog/16574/webkit-features-in-safari-18-4/) — **iOS** picker instructions (navigate into directory, press Open); explicitly a new iOS addition.
- [WebKit Bug 284457](https://bugs.webkit.org/show_bug.cgi?id=284457) — unresolved report involving Safari 17.5/18.0; comments disagree on whether directory selection itself fails.
- [WICG File and Directory Entries API draft, HTML Forms](https://wicg.github.io/entries-api/#html-forms) — describes `webkitdirectory`, selected files, and `webkitRelativePath`; explicitly a Community Group draft, not a W3C standard.
