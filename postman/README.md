# Postman tests

Import these files into Postman:

- `feature-flag-api.postman_collection.json`: 75 ordered automated requests with response assertions and JSON request bodies.
- `local.postman_environment.json`: localhost, authentication disabled by default.
- `digitalocean.postman_environment.json`: deployed HTTPS API, authentication required.
- `manual-checks.postman_collection.json`: optional restart and local database-outage checks; run one folder at a time.

## Run the automated collection

1. In Postman, choose **Import** and select the JSON files above. Save the imported collections in your workspace.
2. Select either **Feature Flag API - local** or **Feature Flag API - digitalocean** as the active environment.
3. For DigitalOcean, set `api_key` to the `API_KEY` value in your local ignored `.env.deployment` file. This is the application key, not the DigitalOcean access token. Keep its value local and do not share or export a populated environment. The committed environment files deliberately contain an empty key.
4. For local use, start the API using the repository README. Standard Docker Compose runs without authentication. If you separately configured a local API key, set `api_key` and change `auth_required` to `true`.
5. Open **Feature Flag API - Automated acceptance**, select **Run**, include all folders, preserve their order, and use one iteration. Enable **Keep variable values** if you want to run the manual persistence checks afterward.
6. Review the runner's assertions. Expected negative responses (`401`, `404`, `409`, `422`) count as passing tests when they match the assertions. Authentication requests are skipped when `auth_required=false`.

The first request generates unique names and saves them in the selected environment. Each iteration creates three flags: the main test flag, a maximum-length flag, and a flag without a description. The API has no delete endpoint, so these records remain in the selected database. No existing user flags are modified. Re-running the whole collection generates fresh names; manually repeating only the create request will intentionally return `409`.

To send an individual request, first run setup and create the main flag, then follow its preceding state changes. Stateful assertions assume the collection order. View each request's **Body > raw > JSON** for its input and **Scripts > Post-response** for its assertions.

Postman's [Collection Runner instructions](https://learning.postman.com/docs/tests-and-scripts/running-collections/intro-to-collection-runs) explain run results and keeping variable values. Its [environment variable documentation](https://learning.postman.com/docs/use/send-requests/variables/environment-variables) explains local and shared values.

## Coverage

| Folder | Requests | Checks |
|---|---:|---|
| Setup and public health | 3 | Public liveness, readiness, and interactive docs; unique test names |
| Flag lifecycle and precedence | 21 | Create/read, duplicate rejection, all four default/override combinations, user isolation, idempotent updates, repeated evaluation, changed state visible after writes |
| Unknown flags | 4 | Read, evaluate, default update, and override update return 404 |
| Validation and unchanged state | 30 | Required fields, strict booleans, malformed JSON, unknown fields, name/user/description limits, NUL, unchanged state after rejected writes |
| Accepted boundary values | 4 | 100-character name, 1,000-character description, 128-character user ID, omitted description |
| Authentication | 13 | Missing and incorrect keys on all five flag routes, authentication challenge, rejected writes leave state unchanged |

The main flag ends with `default_enabled=true`, Alice's override `false`, and Bob following the default (`true`).

## JSON inputs

Variables are resolved by Postman. The collection already contains every body, including deliberately invalid inputs.

Create a flag (`POST {{base_url}}/flags`, expected `201`):

```json
{
  "name": "{{flag_name}}",
  "description": "Postman acceptance test",
  "default_enabled": false
}
```

Change the default (`PUT {{base_url}}/flags/{{flag_name}}/default`, expected `200`):

```json
{
  "default_enabled": true
}
```

Set a user override (`PUT {{base_url}}/flags/{{flag_name}}/users/alice`, expected `200`):

```json
{
  "enabled": false
}
```

Example invalid override (same endpoint, expected `422`):

```json
{
  "enabled": "false"
}
```

Read and evaluate requests have no JSON body. For example, `GET {{base_url}}/flags/{{flag_name}}/evaluate?user_id=alice` ends with this expected response:

```json
{
  "flag_name": "{{flag_name}}",
  "user_id": "alice",
  "enabled": false,
  "source": "override"
}
```

## Manual persistence check

1. Finish the automated collection and keep its environment values. Do not run initialization again before this check.
2. Restart only the API: locally, run `docker compose restart api`; on DigitalOcean, restart only the `api` component of this app.
3. Wait for readiness, then run **01 After API restart** in the manual collection using the same environment. All four requests should pass, demonstrating the stored default and override survived the restart.

Do not run the entire manual collection as a single workflow: its folders require different external states.

## Manual database outage check — local only

1. Finish the automated local collection and retain the environment values.
2. Run `docker compose stop db`, then set `manual_outage=true` in the local environment.
3. Run only **02 Local database stopped**. Liveness should return `200`; readiness, a unique uncached evaluation, and a write should return `503`. Allow up to 15 seconds per request for database timeouts.
4. Always restore PostgreSQL with `docker compose start db`, wait for readiness, and reset `manual_outage=false`.
5. Run **01 After API restart** again to check that the failed write did not change persisted state; no additional restart is necessary for this recovery check.

The outage folder skips requests unless `base_url` is exactly `http://localhost:8000` and `manual_outage=true`. The collection never stops services itself.

## What Postman cannot establish

Repeated evaluations and write-followed-by-read checks verify observable behavior. They do not prove that a response was a cache hit, count SQL queries, prove TTL/LRU eviction, or deterministically reproduce overlapping reads and writes. The existing pytest suite covers those internals, concurrency, fail-closed startup, and database failures. Response-time thresholds would not reliably prove caching and are intentionally absent. The manual outage checks do not attempt a timing-sensitive cached-read-during-outage assertion.

## Verification

The automated collection was executed using Newman 6 against the local API: 62 requests, 138 assertions, no failures; the 13 authentication requests were skipped because local authentication is disabled. The protected DigitalOcean run executed all 75 requests and 176 assertions with no failures. The manual collection requires the external steps described above and was not executed as part of this collection-generation task.
