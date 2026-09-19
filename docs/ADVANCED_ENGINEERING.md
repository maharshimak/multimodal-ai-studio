# Advanced engineering: render workload budgets

`multimodal_studio.budget` adds an explicit resource guard before expensive edit execution.

A media profile contributes resolution, duration and frame rate. Planned operations add transparent
complexity weights. The result is a deterministic weighted megapixel-frame estimate that can be
compared with an environment-specific budget.

This is intentionally an admission-control primitive, not a claim to predict GPU runtime exactly.
It gives an orchestrator a clear place to reject oversized jobs, route them to a larger worker or
request a preview render before allocating expensive compute.
