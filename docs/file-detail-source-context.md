# File Detail source context

File Detail stores a bounded excerpt around each finding so a completed analysis remains useful after its temporary checkout is removed.

This is a deliberate exception to the rule against storing cloned repositories: CodePilot never stores the checkout or complete files. Only the finding window (five lines before and after, subject to size limits) is persisted.

The collector rejects paths outside the checkout, malformed line ranges, binary/invalid UTF-8 files, oversized files and common credential/configuration files. Existing analyses without a context continue to render their finding metadata, evidence and remediation.
