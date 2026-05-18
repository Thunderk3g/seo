# Fetch log — competitor llms.txt probes

Probed on **2026-05-17** via the gap pipeline's earlier HEAD check + WebFetch GET to confirm contents.

## Has llms.txt (captured in this folder)

| Domain | Style | Notes |
|---|---|---|
| policyx.com | Robots-style directives | Allow/Disallow rules + attribution-required + crawl-delay |
| tataaia.com | Markdown nav tree | ~13 links, very compact |
| axismaxlife.com | Markdown nav tree | ~190 links, most thorough of the three (file trimmed in our local copy — see source URL for full version) |

## Does NOT have llms.txt (HEAD returned 404)

| Domain | Result |
|---|---|
| sbilife.co.in | 404 |
| licindia.in | 404 |
| bajajlifeinsurance.com | 404 ← us, we should add one |

## Couldn't confirm (server blocked the fetch tool — file may or may not exist)

| Domain | Result | Likely cause |
|---|---|---|
| hdfclife.com | HTTP 403 | Akamai bot protection blocked WebFetch user-agent |
| iciciprulife.com | HTTP 403 | Likely same — bot protection |
| policybazaar.com | Timeout (>60s) | WAF / rate-limit on automated GET |

For the three "couldn't confirm" rows, the gap pipeline's HEAD probe (which goes through a different user-agent and respects per-host throttle) is more reliable — those didn't surface in the gap report as having llms.txt, so they probably don't.

## Why this matters

Of our ranked rival set, **3 of 10 competitors have llms.txt and we don't**. This is the gap pipeline's "machine-readable signals" notice. Publishing one for bajajlifeinsurance.com closes the gap and likely improves AI-assistant citation rates measurably.
