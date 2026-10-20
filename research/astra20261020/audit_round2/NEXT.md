# Next integration round

Repository: https://github.com/burak113/OptiScaler

Start from the immutable `astra-audit-20261020` tag. The original seven returned
snapshots are under `research/astra20261020/candidates/`; do not edit their frozen
evidence. Read [AUDIT.md](AUDIT.md), [INTAKE.json](INTAKE.json), and the local test
receipts first. The originals' result fields describe their authors' runs; they
do not identify the local executor and do not override the audit.

Run 09 and 10 in two separate chats, concurrently if desired. Start 11 only after
both have returned concrete commits/patches. Two implementation chats plus one
integration chat is preferable to eight simultaneous edits of the native bridge.

- [09: Native observations and support provenance](prompts/09-native-observability.md)
- [10: Native colour implementation and falsification](prompts/10-native-colour.md)
- [11: Integration and independent acceptance](prompts/11-integration-review.md)

All PRs target `sol/astra-audit-20261020`, not upstream or master. Never merge or
deploy automatically. If GitHub writes are unavailable, return a patch or ZIP
with base revision, complete source, SHA-256 manifest, and executable CPU checks.
Do not spend a chat merely proposing another plan: deliver code and measured
evidence, with unavailable GPU/game checks explicitly pending.
