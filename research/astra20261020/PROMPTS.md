# Eight Astra research prompts

Paste one complete prompt into each Astra conversation. Select the same GitHub
repository `burak113/OptiScaler` and allow it to read the research branch/tag.
Jobs01–07 can start independently; job08 builds acceptance tools first and must
wait for the actual candidates plus local GPU verdicts before final integration.

Do not paste all eight into one conversation. Each prompt explicitly requests
subagents, implementation, CPU tests, a skeptical review and a PR or source ZIP.
If a chat only has GitHub reading tools, its return must be a downloadable source
package; no prompt can grant repository write or execution access.

- [Astra Pro job 01: portable CPU/HLSL numerical and sampling contracts](prompts/01-numerical-contract.md)
- [Astra Pro job 02: native anchor estimation under sparse heavy tails and genuine illumination change](prompts/02-anchor-estimator.md)
- [Astra Pro job 03: a noise-aware native colour representation with safe boundaries](prompts/03-native-colour.md)
- [Astra Pro job 04: geometric temporal transport and boundary-safe reconstruction](prompts/04-geometry-transport.md)
- [Astra Pro job 05: less glass specular grain while preserving the user's sharp Temporal-OFF NZR baseline](prompts/05-glass-nzr.md)
- [Astra Pro job 06: diagnosing a moving bottle through input support, motion and specular history](prompts/06-moving-bottle.md)
- [Astra Pro job 07: mixed-coverage foliage guides without false material semantics](prompts/07-foliage-guides.md)
- [Astra Pro job 08: independent host, ABI, lifetime and adversarial integration acceptance](prompts/08-integration-acceptance.md)
