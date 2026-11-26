# Security Architecture

## In place (IMPLEMENTED)

| Control | How |
|---|---|
| Transport | HTTPS only (nginx, Let's Encrypt); HttpOnly, Secure, SameSite=Lax session cookie |
| Authentication | app login; accounts in the database with scrypt hashes; legacy htpasswd administrator; 5 failures lead to a 5-minute block; signed sessions with issue time |
| Session revocation | deactivation or password reset voids sessions issued earlier |
| Authorisation | server-side permission map per role, checked on every request; per-authority actor and role through memberships; `X-Authority` validated against membership; revoked memberships fail closed |
| Tenant isolation | every tenant query filtered by `tenant_id`; tests for cross-tenant access (`test_multi_authority.py`, `test_users.py`, `test_committees.py`) |
| Admin safeguards | no self role change or self deactivation; at least one working administrator per authority; platform administrators only for national data |
| Audit | hash-chained per authority; appends serialised on PostgreSQL; `chain_report` separates edited rows from broken links |
| Attestation | reviewer decisions signed (HMAC) over the run digest |
| Crawler isolation | separate uid; nftables allows only public 80/443 and local DNS (private, loopback, metadata and own subnet rejected); public-address check on every redirect |
| Database | peer authentication over a local socket, no password; the app and crawler have separate roles |
| Uploads | type validation, size limits, hashing, originals kept, text extracted as data |
| AI | local-only by default; no silent cloud fallback; documents passed as evidence blocks |
| Secrets | env file mode 600; keys in `storage/_keys` mode 600; none in git |

## To add

| Threat | Control | Backlog |
|---|---|---|
| ZIP path traversal / decompression bombs | safe extraction: name checks, ratio and total-size limits, no symlinks | B-12 |
| Malicious PDF / Office content | parse in a sandboxed subprocess with limits (time, memory); no macros | B-12 |
| Prompt injection in documents | evidence delimiting, instruction stripping, schema-only outputs, never tool calls driven by document text | B-08 |
| Cache poisoning / cross-tenant leakage | tenant id inside every cache and embedding key; national entries written only by platform jobs | B-05 |
| Unauthorised rule activation | approval workflow with a role check and a source quote check (exists for drafts; extend to all rule versions) | B-03 |
| Concurrent duplicate jobs | row claim with lease (exists for crawls and onboarding; extend to all jobs) | B-06 |
| Brute force from many addresses | per-account throttling in addition to per-address | B-13 |
| MFA | TOTP for administrators | B-13 |
| Encryption at rest | disk-level encryption on the server; per-file encryption for restricted documents if required | open question |
| Backups | the owner declined app-level backups; server-level policy to be confirmed | risk R-07 |

## Non-negotiables

- No AI agent issues a legally binding permit or decision. Binding acts are made by authorised professionals and
  signed.
- Uploaded and crawled content is data, never instructions.
- Restricted documents never leave the platform without explicit authorisation.
