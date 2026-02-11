# Data Acquisition

Phase 2 involves the parallelized gathering of raw data from multiple sources.

## API Adapter Agents (A-D)

The system utilizes specialized adapters to interface with various data providers:

- **API A Adapter**: Typically handles Search Console data (queries, impressions).
- **API B Adapter**: Managed Analytics data (user behavior, sessions).
- **API C Adapter**: External SERP data or competitor analysis.
- **API D Adapter**: Site-specific metadata and technical SEO crawls.

### Key Features
- **Parallel Execution**: Adapters run simultaneously to minimize latency.
- **Resilience**: Each adapter has built-in retry logic for network transients.
- **Isolation**: Failures in one adapter do not halt the entire pipeline.
