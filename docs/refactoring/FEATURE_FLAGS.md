# Feature Flag System for Modular Composition Architecture

## Overview

The refactoring to a modular composition architecture uses feature flags to enable progressive rollout with instant rollback capability. This ensures production safety during the migration.

## Feature Flag: `use_modular_composition`

**Location**: `config.yaml` → `multi_camera_composition.use_modular_composition`

**Purpose**: Controls whether to use the new modular composition architecture or the original monolithic implementation.

**Default**: `false` (uses original monolithic implementation)

## Configuration

```yaml
multi_camera_composition:
  # FEATURE FLAG: Use modular composition architecture (refactored)
  # Set to false to use original monolithic implementation
  # This flag enables progressive rollout with instant rollback capability
  use_modular_composition: false
```

## Usage

### Phase 1: Configuration & Quality (Weeks 1)
```yaml
use_modular_composition: false  # Default - testing in development only
```

During Phase 1, the new configuration models and quality scoring modules are developed but not yet integrated. The flag remains `false` while we validate the modules in isolation.

### Phase 2: Alignment Engine (Week 2)
```yaml
use_modular_composition: false  # Still default - progressive testing
```

Alignment engine is integrated behind the flag. Testing with `use_modular_composition: true` in development environment only.

### Phase 3: Timeline Generation (Week 3)
```yaml
use_modular_composition: false  # High-risk phase - careful rollout
```

Timeline generation (the most complex refactoring) is integrated. Extensive testing with the flag enabled in staging environment. This is the highest-risk phase.

### Phase 4: Rendering (Week 4)
```yaml
use_modular_composition: false  # All modules integrated - final validation
```

All modules are integrated. Full regression testing with the flag enabled. Compare outputs pixel-by-pixel.

### Phase 5: Production Rollout (Week 5)
```yaml
use_modular_composition: true  # Switch default after validation passes
```

After all validation passes and performance benchmarks are within ±5% of baseline, switch the default to `true`. Monitor production closely for 48-72 hours.

### Phase 6: Legacy Removal (Post-release)
After 2-4 weeks of stable production operation with `use_modular_composition: true`:
- Remove the feature flag
- Remove the original monolithic implementation
- Clean up the codebase

## Rollback Procedure

If any issues are detected in production:

1. **Immediate Rollback** (< 1 minute):
   ```yaml
   use_modular_composition: false
   ```
   Update config.yaml and restart the service. The original implementation takes over immediately.

2. **Verify Rollback**:
   - Check logs for errors
   - Verify video outputs are correct
   - Monitor performance metrics

3. **Root Cause Analysis**:
   - Identify the issue
   - Fix in the modular implementation
   - Test thoroughly in development
   - Re-enable the flag after fix is validated

## Implementation Details

### Code Integration

The feature flag is checked in `blink_pipeline/orchestrator.py` when instantiating the MultiCameraComposer:

```python
# Pseudo-code (actual implementation may vary)
config = load_config()
use_modular = config.get('multi_camera_composition', {}).get('use_modular_composition', False)

if use_modular:
    # Use new modular implementation
    from blink_pipeline.composition import ModularComposer
    composer = ModularComposer(config)
else:
    # Use original monolithic implementation
    from blink_pipeline.multi_camera_composer import MultiCameraComposer
    composer = MultiCameraComposer(config)

# Rest of the code is identical
composer.compose_multi_camera_event(...)
```

### Testing with Feature Flag

```bash
# Test with original implementation (default)
pytest tests/integration/ -v

# Test with modular implementation
export USE_MODULAR_COMPOSITION=true
pytest tests/integration/ -v

# Or override in config
cat > test_config.yaml << EOF
multi_camera_composition:
  use_modular_composition: true
EOF
pytest tests/integration/ -v --config=test_config.yaml
```

## Success Criteria

Before switching `use_modular_composition: true` by default:

- ✅ All functional tests pass with both flag=true and flag=false
- ✅ Performance within ±5% of baseline (config_loading, quality_analysis, alignment, timeline_generation, rendering)
- ✅ Output videos match byte-for-byte or pixel-for-pixel (accounting for timestamp differences)
- ✅ No memory leaks or resource exhaustion
- ✅ Error handling maintains same behavior
- ✅ >90% code coverage for new modules
- ✅ All modules <500 lines, <10 complexity
- ✅ Successful 48-hour production trial with flag=true on staging environment

## Monitoring

During rollout, monitor:

- **Error Rates**: Should remain unchanged
- **Processing Time**: Should be within ±5% of baseline
- **Memory Usage**: Should not increase significantly
- **CPU Utilization**: Should remain similar
- **Output Quality**: Validate video quality metrics
- **User Reports**: Monitor for any user-reported issues

## FAQ

### Q: Can I use both implementations simultaneously?
A: No, the feature flag is global per config file. You can run multiple instances with different configs if needed.

### Q: What if I want to test both implementations side-by-side?
A: Use two separate config files:
```bash
python main.py --config=config_original.yaml
python main.py --config=config_modular.yaml
```

### Q: How do I know which implementation is being used?
A: Check the logs at startup:
```
INFO: Using modular composition architecture (use_modular_composition=true)
```
or
```
INFO: Using original monolithic composition (use_modular_composition=false)
```

### Q: What happens if I change the flag while processing is running?
A: The flag is read at startup. Changing it requires a restart to take effect.

### Q: Can I enable modular composition for specific groups only?
A: Not in the current implementation. The flag is global. If needed, this could be added as a per-group override in future iterations.

## References

- [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md): Detailed migration plan
- [ARCHITECTURE_ANALYSIS.md](./ARCHITECTURE_ANALYSIS.md): Current vs. proposed architecture
- [INTERFACE_SPECIFICATIONS.md](./INTERFACE_SPECIFICATIONS.md): Module interfaces
