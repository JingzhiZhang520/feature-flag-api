# Decisions

| Decision | Reason and trade-off | Status |
|---|---|---|
| FastAPI + PostgreSQL | User-selected stack; persistent relational storage with uniqueness constraints. | Approved by user |
| Global state is the default; explicit user overrides win | User selected this interpretation over a global master switch. Both enabled and disabled overrides are supported. | Approved by user |
| Bounded in-process cache first | Assistant recommendation accepted by user: less setup than Redis; limited to one API process for immediate invalidation. | Approved by user; supersedes initial Redis recommendation |
| Backend first; DigitalOcean optional | User prioritizes required functionality before deployment. | Approved by user |
| Cache evaluation results, 1,024 entries, five-second TTL | Implementation choice: clear all entries after writes; generation checks prevent an overlapping read from repopulating stale data. Broad invalidation costs hit rate but keeps the implementation small. | Implemented and tested within approved scope |
| Opaque, case-sensitive user IDs; strict JSON booleans | No user-account system is required. Names and IDs have bounded lengths; malformed input returns 422. | Implementation assumption |
| Versioned database migration; local-only API initially | Schema changes are explicit. Authentication is not specified; public deployment needs an access-control decision first. | Implementation assumption; deployment deferred |

Redis is a possible later improvement, not part of the initial build. Its adoption requires shared invalidation and concurrency behavior, not merely replacing a dictionary.
