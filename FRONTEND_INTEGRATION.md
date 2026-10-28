# Frontend Integration Contract

Share this document with the frontend developer. The frontend calls the FastAPI
service through the public Kong proxy URL (or the API URL in local development).

## Base URL and authentication

Example local base URL: `http://localhost:8000`. In production, use the public
HTTPS hostname configured for Kong.

All `/github/*` and `/billing/*` endpoints require:

```http
Authorization: Bearer <OIDC access token>
Content-Type: application/json
```

### GitHub sign-in and registration

Start login or registration by navigating the browser to
`GET /auth/github/login`. The API redirects to GitHub and validates the OAuth
`state` on its callback. The first successful sign-in registers the member
implicitly; the stable member key is `github:<numeric GitHub account ID>`.
Existing member history and subscription records keyed by previous OIDC
subjects are not automatically linked to the new GitHub member ID; plan a
verified account-migration process before switching existing users.
No GitHub OAuth access token is exposed to the frontend or stored by the API.

After success, the API redirects to `FRONTEND_AUTH_CALLBACK_URL` with an
`access_token`, `token_type`, `expires_in`, and GitHub `login` in the URL
fragment. The frontend callback should read the fragment, immediately remove
it from the address bar with `history.replaceState`, and keep the short-lived
token in memory where practical. The token is an API-issued 60-minute bearer
token; send it in the `Authorization` header. Do not send a member ID, plan,
price, Razorpay key secret, or webhook secret from the browser. The backend
validates its signature, issuer, audience, expiry, and GitHub member subject.
GitHub login requires `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`,
`GITHUB_OAUTH_REDIRECT_URI`, and a strong `AUTH_TOKEN_SECRET` on the API.

OAuth failures redirect to the same frontend callback with an `auth_error`
fragment instead of a token.

`POST /webhooks/razorpay` is called by Razorpay, not by the browser. The
frontend must never call it directly.

## Features by membership

| Feature | Free | Premium |
|---|---:|---:|
| Analyze one public repository | Yes | Yes |
| Repository analysis limit | 3 per UTC calendar month | No free-tier cap |
| Analyze a GitHub account | No | Yes |
| View own analysis history | Yes | Yes |

Private repositories are not supported. The account analysis returns metadata
for public repositories and performs detailed source reviews on the three most
recently updated repositories.

## Repository analysis

`POST /github/repository/analyze`

Request:

```json
{
  "owner": "octocat",
  "repository": "hello-world"
}
```

Successful response (`201`):

```json
{
  "success": true,
  "analysis_id": "MongoDB analysis ID",
  "usage": {
    "used": 1,
    "limit": 3,
    "period": "2026-10"
  },
  "data": {
    "repository_name": "hello-world",
    "code_quality_score": 80,
    "architecture_score": 75,
    "readability_score": 82,
    "maintainability_score": 76,
    "testing_score": 60,
    "documentation_score": 85,
    "complexity_score": 35,
    "developer_level": "Intermediate",
    "project_difficulty": "Intermediate",
    "summary": "Example summary",
    "strengths": [],
    "issues": [],
    "detected_skills": [],
    "engineering_practices": [],
    "recommendations": [],
    "metrics": {
      "total_files": 20,
      "source_files": 12,
      "sampled_lines": 500,
      "has_readme": true,
      "has_tests": true,
      "has_docker": false,
      "has_ci": true,
      "has_license": true,
      "detected_frameworks": [],
      "dependency_files": [],
      "important_files": []
    }
  }
}
```

The sample score and summary values are illustrative; the actual analysis
content depends on the repository and AI provider.

`GET /github/usage` returns the current free-tier usage:

```json
{
  "success": true,
  "plan": "free",
  "used": 1,
  "limit": 3,
  "period": "2026-10"
}
```

Premium members receive `used: null` and `limit: null`.

## Premium GitHub account analysis

`POST /github/account/analyze`

Request:

```json
{
  "username": "octocat"
}
```

Success returns `{ "success": true, "analysis_id": "...", "data": { ... } }`.
`data` contains account scores, summary, skills, recommendations, repository
metadata, and detailed reviews for up to three recent repositories.

Free members receive `403` with a premium-upgrade message. The legacy
`POST /github/analyze` route has the same premium access rule; new clients
should use `/github/account/analyze`.

## Premium subscription checkout

1. Call `POST /billing/subscription` with the bearer token and no request body.
2. On success (`201`), redirect the browser to `data.checkout_url`.
3. After the user finishes checkout, show a pending state and poll
   `GET /billing/subscription` using the user's bearer token. A successful
   browser redirect does **not** itself grant premium.
4. The backend grants premium after receiving and verifying Razorpay's signed
   subscription webhook. Once active, `GET /billing/subscription` returns:

   ```json
   {
     "success": true,
     "data": {
       "subscription_id": "sub_...",
       "status": "active",
       "cancel_at_cycle_end": false,
       "current_end": 1790000000,
       "updated_at": "2026-10-26T10:00:00Z"
     }
   }
   ```

If the member has no subscription, `data` is `null`. Other statuses can
include `created`, `authenticated`, `pending`, `halted`, `cancelled`,
`completed`, or `paused`; only `active` enables premium features.

If an active or pending subscription already exists, creating another returns
`409`. If Razorpay plan IDs, API credentials, or the finite subscription cycle
count are not configured on the backend, checkout returns `503`.

## Cancel subscription

`POST /billing/subscription/cancel`

Request:

```json
{
  "cancel_at_cycle_end": true
}
```

Set `cancel_at_cycle_end` to `false` for immediate cancellation. On success,
the response status is `cancellation_requested`. Continue displaying the
current membership until `GET /billing/subscription` reports that the signed
webhook changed its status; do not revoke or extend premium based only on the
frontend response.

## Analysis history

- `GET /github/latest` — latest saved analysis for the current member.
- `GET /github/history` — saved analyses for the current member.
- `GET /github/{analysis_id}` — one saved analysis owned by the current member.

The backend scopes results to the bearer token subject. Never send another
member's ID as an authorization mechanism.

## Common errors

| HTTP | Meaning | Frontend behavior |
|---:|---|---|
| `400` | Invalid request or webhook payload | Show validation message; webhook is not a frontend action |
| `401` | Missing, invalid, or expired token | Refresh/login, then retry |
| `403` | Premium-only account analysis | Offer subscription checkout |
| `404` | GitHub user/repository or saved analysis not found | Show not-found state |
| `409` | Existing/pending subscription or invalid cancellation state | Refresh subscription status |
| `422` | Request fields failed validation | Show field-level validation |
| `429` | Free monthly quota or GitHub rate limit reached | Show reset period if returned |
| `413` | Oversized Razorpay webhook payload | Not a frontend action; review webhook configuration |
| `502` | GitHub, AI, or Razorpay upstream failure | Offer retry; avoid rapid loops |
| `503` | Auth, MongoDB, or billing configuration unavailable | Show temporary service/configuration error |

Quota errors include `detail.message`, `detail.used`, `detail.limit`, and
`detail.period`. FastAPI validation errors use the standard `detail` array.

## CORS and Kong

Add the exact frontend origin to backend `CORS_ORIGINS`. Use the Kong proxy
hostname as the frontend API base URL. Kong's DB-less routes are in
[`kong/kong.yml`](./kong/kong.yml). Kong forwards bearer tokens unchanged; the
backend validates API-issued tokens and owns entitlement checks. Never expose
the Kong Admin API or Razorpay secrets to the browser.
