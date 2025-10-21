# Performance Optimization Opportunities

## Analysis of `src/media_validation.py`

### ✅ Current Strengths

1. **Good cache-first strategy**: Checks cache before expensive operations
2. **Efficient early returns**: Exits fast for cache hits and invalid videos
3. **Proper parallel processing**: Uses ProcessPoolExecutor for true multiprocessing
4. **Clean error handling**: Gracefully handles failures and falls back to originals

### 🚀 High-Impact Optimizations

#### 1. **Eliminate Redundant Video Probing for Cache Hits** ⭐⭐⭐

**Current Issue:**
```python
cache_path = Path(cache_dir) / f"repaired_{strategy}_{Path(video_path).name}"
if cache_path.exists():
    return (video_path, str(cache_path), True)  # Returns immediately

# But we still probe AFTER the return, which never executes
media_info = probe_media_info(video_path)  # DEAD CODE for cache hits
```

**Why it's not a problem:** Code already returns early on cache hit, so probe doesn't execute.

**Status:** ✅ Already optimized

---

#### 2. **Optimize Statistics Tracking** ⭐⭐

**Current Issue:**
```python
# Convoluted logic to determine if repair came from cache
if was_repaired:
    if validated_path == str(Path(cache_dir) / f"repaired_{strategy}_{Path(orig_path).name}"):
        repaired_count += 1  # Fresh repair
    else:
        cached_count += 1    # From cache? This logic seems wrong
```

**Problem:** The `was_repaired` flag is `True` for BOTH fresh repairs AND cache hits. The nested check tries to distinguish them but reconstructs the path, which is error-prone.

**Fix:** Return more granular status from worker:

```python
# Return status: 'cached', 'repaired', 'original'
def _validate_video_job(args) -> Tuple[str, str, str]:
    # ...
    if cache_path.exists():
        return (video_path, str(cache_path), 'cached')

    if needs_repair or always_repair:
        if repair_video(...):
            return (video_path, str(cache_path), 'repaired')

    return (video_path, video_path, 'original')
```

**Impact:** Clearer code, fewer string operations, accurate statistics

**Difficulty:** Easy (15 minutes)

---

#### 3. **Optimize Logging Configuration** ⭐

**Current Issue:**
```python
def _validate_video_job(args):
    logging.getLogger().setLevel(logging.ERROR)  # Called for EVERY video
```

**Problem:** Setting logging level is a relatively expensive operation, repeated for every single video.

**Fix:** Configure logging once at process initialization:

```python
def _init_worker():
    """Initialize worker process with optimized settings."""
    logging.getLogger().setLevel(logging.ERROR)

with ProcessPoolExecutor(max_workers=max_workers, initializer=_init_worker) as executor:
    # Workers now initialized once
```

**Impact:** Reduced per-video overhead by ~0.1-0.5ms (negligible on long operations, but proper design)

**Difficulty:** Easy (5 minutes)

---

#### 4. **Improve Cache Key Collision Safety** ⭐⭐

**Current Issue:**
```python
cache_path = Path(cache_dir) / f"repaired_{strategy}_{Path(video_path).name}"
```

**Problem:** If you have videos with the same filename in different directories:
- `camera1/video.mp4` → `repaired_fill_video.mp4`
- `camera2/video.mp4` → `repaired_fill_video.mp4` (COLLISION!)

**Fix:** Use hash or full path encoding:

```python
import hashlib

def _get_cache_path(video_path: str, cache_dir: str, strategy: str) -> Path:
    """Generate collision-safe cache path."""
    # Option 1: Use hash of full path
    path_hash = hashlib.md5(video_path.encode()).hexdigest()[:8]
    filename = f"repaired_{strategy}_{Path(video_path).name}_{path_hash}.mp4"

    # Option 2: Preserve directory structure (better for debugging)
    # relative_path = Path(video_path).name  # Or preserve more structure
    # return Path(cache_dir) / strategy / relative_path

    return Path(cache_dir) / filename
```

**Impact:** Prevents cache collisions, ensures correctness

**Difficulty:** Medium (30 minutes, need to handle backward compatibility)

---

#### 5. **Fast-Path Cache Checking** ⭐⭐⭐

**Current Approach:** Spawn workers for all videos, each worker checks cache

**Optimization:** Pre-check cache in main thread (parallel if many files), only spawn workers for videos that need processing:

```python
def preprocess_videos(...):
    # Fast parallel cache check (I/O bound, can use ThreadPoolExecutor)
    from concurrent.futures import ThreadPoolExecutor as TPE

    cached_videos = {}
    videos_to_process = []

    def check_cache(path):
        cache_path = Path(cache_dir) / f"repaired_{strategy}_{Path(path).name}"
        if cache_path.exists():
            return (path, str(cache_path), 'cached')
        return (path, None, 'needs_check')

    # Fast cache check with threads (I/O bound)
    with TPE(max_workers=max_workers * 2) as executor:
        for result in executor.map(check_cache, video_paths):
            path, cached, status = result
            if status == 'cached':
                cached_videos[path] = cached
            else:
                videos_to_process.append(path)

    # Report cache hits immediately
    for path, cached_path in cached_videos.items():
        path_mapping[path] = cached_path
        completed += 1
        if progress_callback:
            progress_callback(completed, total)

    # Only spawn heavy workers for videos that need processing
    if videos_to_process:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Process only non-cached videos
```

**Impact:**
- **Massive speedup** when many videos are cached (~100ms vs 30s per video)
- Better progress feedback (cache hits complete instantly)
- Reduced process spawning overhead

**Difficulty:** Medium (1 hour, needs careful refactoring)

---

#### 6. **Batch Processing for Large Collections** ⭐⭐

**Current Issue:** All futures held in memory simultaneously for large video collections (1000+ videos)

**Fix:** Process in batches:

```python
def preprocess_videos_batched(video_paths, ..., batch_size=100):
    for i in range(0, len(video_paths), batch_size):
        batch = video_paths[i:i+batch_size]
        # Process batch
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Process batch...
```

**Impact:**
- Reduced memory footprint for large collections
- More consistent progress updates
- Better resource management

**Difficulty:** Medium (45 minutes)

---

### 🔧 Medium-Impact Optimizations

#### 7. **Smarter Worker Count Auto-Detection** ⭐

**Current:** Default `max_workers=6` might be too high for HDDs or too low for NVMe

**Fix:**
```python
def _detect_optimal_workers(video_paths, cache_dir):
    """Auto-detect optimal worker count based on storage type."""
    import subprocess

    # Check if cache_dir is on SSD/NVMe
    # On macOS: diskutil info / | grep "Solid State"
    # On Linux: check /sys/block/*/queue/rotational

    if is_ssd(cache_dir):
        return min(6, os.cpu_count())
    else:
        return min(2, os.cpu_count())  # HDD: limit to 2
```

**Impact:** Better defaults for different hardware

**Difficulty:** Medium (1 hour, platform-specific)

---

#### 8. **Dry-Run Mode for Statistics** ⭐

**Addition:** Allow checking what would be done without actually doing it:

```python
def preprocess_videos(..., dry_run: bool = False):
    """If dry_run=True, only report statistics without processing."""
    if dry_run:
        # Just check cache and probe, don't repair
        for path in video_paths:
            # Check cache status, probe for sync issues
            # Report what WOULD be done
```

**Impact:** Useful for capacity planning and debugging

**Difficulty:** Easy (30 minutes)

---

### ⚡ Low-Impact Optimizations

#### 9. **Reduce Path Object Creation**
- Cache `Path(video_path).name` instead of creating multiple times
- **Impact:** Minimal (microseconds per video)
- **Difficulty:** Easy (10 minutes)

#### 10. **Use f-strings Consistently**
- Some places use `str()` concatenation, others use f-strings
- **Impact:** Marginal (f-strings slightly faster)
- **Difficulty:** Easy (5 minutes)

---

## Recommended Implementation Priority

### Phase 1 (High Value, Low Effort):
1. **Fix statistics tracking** (15 min) - Correctness issue
2. **Optimize logging setup** (5 min) - Clean design
3. **Improve cache key safety** (30 min) - Prevents bugs

### Phase 2 (High Value, Medium Effort):
4. **Fast-path cache checking** (1 hour) - Massive speedup for cached videos
5. **Batch processing** (45 min) - Better resource management

### Phase 3 (Nice-to-Have):
6. **Smarter worker detection** (1 hour) - Better defaults
7. **Dry-run mode** (30 min) - Debugging tool

---

## Performance Benchmark Estimates

**Current Performance (50 videos):**
- 25 cached: ~25 × 500ms = 12.5s
- 25 need repair: ~25 × 15s = 375s
- **Total: ~388s (~6.5 minutes)**

**With Fast-Path Cache Checking:**
- 25 cached: ~25 × 50ms = 1.25s (10× faster!)
- 25 need repair: ~25 × 15s = 375s
- **Total: ~376s (~6.3 minutes, 3% improvement)**

**With All Optimizations:**
- 25 cached: ~25 × 50ms = 1.25s
- 25 need repair: ~25 × 14.5s = 362s (slightly faster with better logging)
- **Total: ~363s (~6 minutes, 6-7% improvement)**

**Biggest win:** Scenarios with high cache hit rates (80%+)
- Current: ~250s
- Optimized: ~15s
- **~94% improvement!**

---

## Code Quality Improvements

Beyond performance, these changes also improve:
- ✅ Code clarity (better statistics tracking)
- ✅ Correctness (cache collision safety)
- ✅ Maintainability (cleaner worker initialization)
- ✅ Debuggability (dry-run mode, better progress)

---

## Backward Compatibility Notes

**Cache key changes** (improvement #4) would invalidate existing cache. Solutions:
1. Add migration function to rename old cache files
2. Check both old and new formats
3. Document as breaking change in next major version

**Recommendation:** Implement with backward compatibility check:
```python
# Try new format first, fall back to old format
new_cache = _get_cache_path_v2(video_path, cache_dir, strategy)
old_cache = _get_cache_path_v1(video_path, cache_dir, strategy)

if new_cache.exists():
    return new_cache
elif old_cache.exists():
    # Migrate to new format
    old_cache.rename(new_cache)
    return new_cache
```
