# History and hotspot API contract

The dashboard contract for a future history endpoint is a map keyed by normalized repository-relative path:

```json
{
  "path": "src/service.py",
  "commit_count": 12,
  "recent_change_frequency": 0.03,
  "author_count": 3,
  "ownership_concentration": 0.58,
  "file_age_days": 420.0,
  "recent_churn": 184,
  "complexity": 18.0,
  "finding_density": 2.0,
  "hotspot_score": 0.74,
  "score_explanation": "complexity=18.00*0.50; recent_churn=184*0.30; finding_density=2.00*0.20"
}
```

Scores are explainable heuristics, not developer-performance or quality judgments. History is bounded by a configurable window, commit count, timeout, and output size. Rename handling uses Git's similarity detection and may not preserve identity for every complex rename.
