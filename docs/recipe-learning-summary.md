# Browser Recipe Learning Summary

**Date:** 2026-01-09
**Duration:** ~15 minutes
**Environment:** mcp-browser-use server on http://127.0.0.1:8383

## Results Overview

| Metric | Value |
|--------|-------|
| Recipes Learned Automatically | 1 |
| Recipes Created Manually | 4 |
| Total Working Recipes | 5 |
| Auto-learning Success Rate | 20% (1/5 attempts saved) |

## Recipes Created

### 1. remoteok-job-search (Auto-learned ✓)
- **Description:** Searches for remote jobs on RemoteOK.com
- **API Found:** Algolia search API (uj5wyc0l7x-dsn.algolia.net)
- **Learning Time:** 139.6 seconds
- **Execution Time:** 97.8 seconds
- **Notes:** The analyzer found and extracted the underlying Algolia search API

### 2. hackernews-search (Manual ✓)
- **Description:** Search Hacker News for posts using the Algolia API
- **API:** https://hn.algolia.com/api/v1/search?query={query}
- **Execution Time:** 24.6 seconds
- **Notes:** Learning identified the API but didn't save recipe

### 3. coingecko-btc-price (Manual ✓)
- **Description:** Get cryptocurrency price from CoinGecko API
- **API:** https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies={currency}
- **Execution Time:** 21.1 seconds
- **Notes:** Learning found the API endpoint but extraction failed

### 4. npm-package-search (Manual ✓)
- **Description:** Search npm registry for packages
- **API:** https://registry.npmjs.org/-/v1/search?text={query}
- **Execution Time:** 8.3 seconds
- **Notes:** Learning identified API but didn't extract as recipe

### 5. pypi-package-info (Manual ✓)
- **Description:** Get package information from PyPI
- **API:** https://pypi.org/pypi/{package}/json
- **Execution Time:** 6.8 seconds
- **Notes:** Learning found the JSON API but extraction failed

## Why Auto-Learning Failed for Most Services

### Pattern Observed
The learning process successfully:
1. Navigates to websites
2. Discovers API endpoints
3. Reports the API structure in the result

But often fails to:
1. Extract the API as a saved recipe
2. The LLM analyzer may not format the response correctly
3. The `request` object may be incomplete or malformed

### Successful Auto-Learning Characteristics (RemoteOK)
- The Algolia search API was complex with POST body
- The analyzer successfully extracted all components:
  - URL with parameters
  - POST body template
  - Response extraction path

### Failed Learning Characteristics
- Simple GET APIs (npm, PyPI, CoinGecko) were identified but not extracted
- The analyzer returned `success: false` or incomplete data
- Result message showed "Could not extract API from execution"

## Recommendations

### For Improving Auto-Learning
1. **Prompt Engineering:** The analyzer prompt may need refinement for simpler GET APIs
2. **API Detection:** Improve CDP recording to capture more API details
3. **Fallback Strategy:** If LLM extraction fails, try regex-based extraction

### For Manual Recipe Creation
When auto-learning fails, create YAML recipes with:
- `url` with `{param}` placeholders
- `method` (GET/POST)
- `extract_path` for JSON response parsing
- `allowed_domains` for security

## Recipe Storage

All recipes are stored in: `~/.config/browser-recipes/`

```
~/.config/browser-recipes/
├── coingecko-btc-price.yaml
├── hackernews-search.yaml
├── npm-package-search.yaml
├── pypi-package-info.yaml
└── remoteok-job-search.yaml
```

## Execution Performance

| Recipe | Execution Time | Status |
|--------|---------------|--------|
| pypi-package-info | 6.8s | ✓ Fast |
| npm-package-search | 8.3s | ✓ Fast |
| coingecko-btc-price | 21.1s | ✓ Normal |
| hackernews-search | 24.6s | ✓ Normal |
| remoteok-job-search | 97.8s | ✓ Slow (uses browser) |

## Next Steps

1. **Fix parameter passing** - Some recipes show wrong query terms (e.g., "test" instead of "rust")
2. **Test direct API execution** - Recipes should use direct fetch, not browser navigation
3. **Improve analyzer** - Update LLM prompts for better extraction from simple GET APIs
4. **Add more recipes** - Continue building library for 150+ services
