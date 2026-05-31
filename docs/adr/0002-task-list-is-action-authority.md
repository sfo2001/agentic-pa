# tasks.todo.txt is the single source of truth for Action state

An Action's existence and status live **only** in `tasks.todo.txt`. A meeting
record's `## Actions` section is *frozen provenance* (what was agreed in that
meeting, never updated after filing), and a topic's `## Open actions` is a
*generated, date-stamped snapshot* regenerated from the Task list — never
hand-edited. This removes the dual-write drift that would otherwise arise from an
Action being visible in three places (meeting, task list, topic).

## Consequences

A future reader will see meeting/topic action copies that look out of date
relative to `tasks.todo.txt`. This is intentional — they are historical
provenance and a stamped view, respectively. **Do not "re-sync" them back into
authority.** The only authority is the Task list (and the Agenda service that
reads it).
