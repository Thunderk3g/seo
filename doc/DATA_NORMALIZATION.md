# Data Normalization

Phase 3 transforms raw API responses into a unified semantic format.

## Semantic Observations (JSON)

Every API adapter outputs data into a standardized JSON structure.

### Why Semantic Observations?
1. **Consistency**: The reasoning agents receive data in a predictable format regardless of the source.
2. **Conflict Resolution**: Identifies duplicate data points across different APIs.
3. **Traceability**: Each observation is tagged with its source API and timestamp.

### Example Schema
- `source`: string (e.g., "Google Search Console")
- `metric`: string (e.g., "CTR")
- `value`: float
- `confidence`: float (0.0 - 1.0)
