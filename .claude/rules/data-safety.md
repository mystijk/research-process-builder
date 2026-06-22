---
description: Supabase workspace 3 = production. Verify before write. Ground-truth files immutable.
globs: ["scripts/**"]
---

# Data Safety

- Supabase workspace 3 = production. Always verify target table before any write.
- Ground truth files (`ground-truth/*.json`) are immutable reference data.
- Baselines in `baselines/` — compare against, don't modify.
- Domain classifier: `real_company` accepts, anything else rejects. Fix the classifier, don't append to `BLOCKED_DOMAINS`.
