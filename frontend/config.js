// Minimal config for the static frontend viewer.
// Paths are relative to the frontend/ directory when served locally.

const DATA_BASE = "../Pre-Processing/output/summaries/";

export default {
  // Use enhanced index (with 2D coords); fallback to index.json if needed.
  indexUrl: `${DATA_BASE}index_enhanced.json`,
  dataBasePath: DATA_BASE,
  cache: {
    enabled: false,
    strategy: "no-cache",
  },
  ui: {
    maxLogEntries: 100,
    sidebarCollapseBreakpoint: 1024,
  },
  performance: {
    debounceDelay: 150,
  },
};
