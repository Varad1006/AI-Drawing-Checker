# Lead Checker — Definition of Done

A portfolio-grade, end-to-end **P&ID lead checker**: upload a drawing, get a findings register from a
deterministic rule engine plus an optional Groq AI review, fix the drawing by hand or by chatting with
an AI assistant that really edits it, and export the results.

## End state

| # | Capability | Done when |
|---|------------|-----------|
| 1 | **Ingest** | DXF (primary) parses lines, polylines, text, MTEXT, blocks + attributes, title block. Vector PDF (first page) parses text + vector geometry. Bad files fail with a clear error. |
| 2 | **Extraction** | Symbols are classified from block names (pump, tank, vessel, valves, instruments…); tags come from block attributes, split instrument bubbles (`FT` / `101`) or the nearest tag-like text. Text-only tags become entities too. |
| 3 | **Topology** | Pipe endpoints snap to symbols, tees and each other; inline valves are detected; flow direction follows line order. |
| 4 | **Rule engine** | 15 deterministic rules with IDs, categories and severities (tagging, connectivity, safety, instrumentation, documentation, layout). Each finding has a location and, where mechanical, a structured fix. |
| 5 | **AI review (Groq)** | Optional, runs only with `GROQ_API_KEY`; findings are labelled AI with confidence and never replace rule findings. No simulated output. |
| 6 | **Viewer** | Renders the real drawing (block symbols, pipes, signal lines, text, title block) with pan/zoom/fit, issue clouds, and click-to-locate. |
| 7 | **Editing** | Every change is an edit operation (move, rotate, retag, delete, add, connect, insert inline, …) stored as a new revision with author (user / AI / auto-fix), with undo/redo. |
| 8 | **Chat-driven editing** | The assistant uses Groq tool-calling to apply edit operations to the drawing and explains what it changed; changed objects are highlighted. Without a key, a built-in command parser handles common commands. |
| 9 | **Auto-fix** | Per-issue "Apply fix" and "Auto-fix all" for mechanically fixable findings; checks re-run after every edit. |
| 10 | **Issue workflow** | Open → Accepted / Rejected (with comment); findings that disappear after edits are counted as Fixed. |
| 11 | **Exports** | Corrected DXF (current revision), marked-up DXF (issue clouds + callouts on a `CHECKER` layer), PDF check report (drawing with clouds + issue register). |
| 12 | **Samples & tests** | Generated sample P&IDs (one with seeded errors, one clean) power the live demo; pytest covers parser, topology, every rule, edit ops, exports and API. |
| 13 | **DX** | One-command setup/run, accurate README, `.env.example`. |

## Out of scope

DWG input, scanned/raster PDFs (OCR/vision), authentication and multi-user collaboration, cloud deployment.
