# Risk score v1 and quality gates

CodePilot's score is an explainable heuristic, not a prediction of defect probability or developer quality.

## Formula

For each component that has real data, normalize the value to `[0, 1]` and calculate:

```text
score = sum(component_value * configured_weight) / sum(configured_weights_for_present_components)
```

Missing data is omitted; it is never invented as zero or one. Stored assessments include the score version, normalized components, and effective weights so the score can be reconstructed exactly.

| Category | Range |
| --- | --- |
| low | `< 0.33` |
| medium | `0.33–<0.66` |
| high | `0.66–<0.85` |
| critical | `>= 0.85` |

Quality gates count only newly introduced critical findings and hotspots when a baseline is available. Legacy findings remain visible but do not create a new-debt failure. Each gate failure has a stable code and a human-readable reason.
