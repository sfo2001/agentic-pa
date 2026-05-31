# Plaintext notes + deterministic agenda engine (architecture B)

The structured-notes layer stores everything as plain markdown / `todo.txt` and
computes all date and surfacing logic (due, resurfacing, stale) in a small
deterministic, **read-only** engine — the *Agenda service* — rather than leaving
surfacing to the LLM's memory (architecture A) or enforcing the schema through a
write-capable MCP server (architecture C). This guarantees the product's core
invariant — date-based follow-ups never silently drop — in code, while keeping
the corpus hand-editable, greppable, and portable.

## Considered Options

- **A — pure prompt-driven plaintext:** smallest build, but resurfacing depends
  on the LLM remembering to check ticklers each time.
- **B — plaintext + deterministic agenda engine (chosen).**
- **C — schema-enforcing local notes write-MCP:** strongest guarantees, most
  work, loses the "it's just markdown" property.

## Consequences

C is the intended future hardening if the invariants ever need stronger
enforcement than convention + a read-only engine provides.
