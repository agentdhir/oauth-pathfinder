# Human reviews

One JSON file per guide (`<slug>.json`), kept separate from agent output so regenerating a guide never erases them.

```json
{
  "date": "2026-10-20",
  "guide_generated_at": "<generated_at of the guide version you reviewed>",
  "summary": "One or two sentences: overall verdict on the guide.",
  "checked": ["Claim X: confirmed against <url>"],
  "corrections": ["What was wrong and what is right, with source"],
  "tested": ["Hands-on attempt: what was done, how long it took, what happened"],
  "overrides": {"difficulty": "easy", "approval_wait": "None"}
}
```

`overrides` may only change the headline fields (difficulty, difficulty_reason, setup_time, approval_wait,
approval_required, approval_details). The UI shows the agent's original value next to the correction.
If the guide is regenerated, the review is shown as stale until `guide_generated_at` is updated.
