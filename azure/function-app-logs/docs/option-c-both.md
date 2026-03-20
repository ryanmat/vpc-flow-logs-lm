# Option C: Build B First, Then Contribute A

## Summary

Build the Python transformer (Option B) first for immediate POC results, then submit the upstream PR (Option A) for the long-term product fix.

## Phasing

### Phase 1: Transformer (Option B)
- Deploy the Python Azure Function transformer
- Prove Function App logs flowing correctly into LM Logs with proper severity and message fields
- Use as demo material for PM conversation and customer presentation
- Timeline: Days

### Phase 2: Upstream Fix (Option A)
- Submit PR to logicmonitor/lm-logs-azure with the Java fix
- Reference the working transformer as proof of the correct field mapping
- Having a working implementation makes the PR review easier (the fix is proven, not theoretical)
- Timeline: Engineering review cycle

### Phase 3: Deprecate Transformer
- Once the upstream fix ships in a new lm-logs-azure release, the transformer becomes redundant
- Decommission the transformer Function App
- Document the transition for any environments that deployed it

## Effort

- More total effort than either option alone
- But each phase delivers independent value
- Phase 1 is the same effort as Option B
- Phase 2 is the same effort as Option A (slightly less because the mapping logic is already proven)

## Benefits

- Immediate tangible results (Phase 1)
- Long-term product fix (Phase 2)
- The transformer serves as a reference implementation for the upstream PR
- No single point of failure: if the PR stalls, the transformer keeps working

## Risks

- Maintaining two solutions temporarily
- Must track the upstream PR to completion to avoid permanent tech debt
- Phase 3 cleanup is easy to forget (add a reminder when the PR merges)

## Recommendation

This is the recommended approach if both short-term demo results and long-term product improvement are goals.
