# GitHub Analyzer

FastAPI service that analyzes public GitHub repositories, stores member history
in MongoDB, enforces free-tier usage, and sells premium access through Razorpay
subscriptions.

## Product features

- **Free:** analyze one public repository per request, up to three analyses per
  member per UTC calendar month.
- **Premium:** analyze a public GitHub account. All public repository metadata
  is included; detailed source reviews are limited to the three most recently
  updated repositories.
- **Billing:** create and cancel Razorpay subscriptions; premium access is
  granted only by verified Razorpay subscription webhooks.
- **Member data:** authenticated analysis history is scoped to the verified
  member identity.
- **API gateway:** optional Kong Gateway OSS declarative configuration is in
  [`kong/kong.yml`](./kong/kong.yml).

## Frontend handoff

The complete endpoint contract, authentication flow, request/response examples,
error behavior, and payment lifecycle are documented in
[`FRONTEND_INTEGRATION.md`](./FRONTEND_INTEGRATION.md). Share that file with the
frontend developer.

## Backend setup

1. Create and activate a virtual environment, then install development
   dependencies:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt
   ```

2. Copy `.env.example` to `.env`. Configure MongoDB, GitHub OAuth, an AI
   provider, and Razorpay as needed. Never commit `.env` or expose Razorpay's
   secret key to the browser.
3. Create a GitHub OAuth App. Set its Authorization callback URL to the API's
   `GITHUB_OAUTH_REDIRECT_URI` (for local development,
   `http://localhost:8000/auth/github/callback`), then configure
   `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`,
   `GITHUB_OAUTH_REDIRECT_URI`, and `FRONTEND_AUTH_CALLBACK_URL`. Generate a
   random `AUTH_TOKEN_SECRET` of at least 32 characters. The first successful
   GitHub sign-in creates the member identity; the API uses GitHub's immutable
   numeric account ID as the member key. Access tokens issued by this API are
   valid for 60 minutes. Premium is derived from active subscription records
   written by the verified Razorpay webhook, never from a client request.
4. Create an INR monthly subscription plan in Razorpay Dashboard and set
   `RAZORPAY_PLAN_ID`. Set Razorpay API credentials, webhook secret, and
   `RAZORPAY_SUBSCRIPTION_TOTAL_COUNT` in `.env`. Razorpay subscriptions have a
   finite cycle count, so choose the term and renewal policy before enabling
   checkout. This project intentionally does not invent a price or plan.
5. In Razorpay Dashboard, configure the webhook URL as
   `https://<public-api-domain>/webhooks/razorpay`, set the matching webhook
   secret, and subscribe to `subscription.activated`, `subscription.charged`,
   `subscription.cancelled`, `subscription.completed`, `subscription.halted`,
   `subscription.paused`, `subscription.pending`, `subscription.resumed`, and
   `subscription.updated`.
6. Set `CORS_ORIGINS` to the real frontend origins. The app and Kong should
   share a private network; do not expose MongoDB or Kong's Admin API publicly.

Run the API directly for development:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Interactive API docs are at `/docs`. Run the test suite with:

```powershell
python -m pytest -q
```

## Kong Gateway OSS

[`kong/kong.yml`](./kong/kong.yml) is a DB-less declarative configuration. It
routes requests to the API container at `github-analyzer-api:8000`. Put Kong
and the API on the same private Docker network, and set
`KONG_DATABASE=off` and `KONG_DECLARATIVE_CONFIG=/etc/kong/kong.yml`.
Configure the public listener only; do not expose the Admin API to the
internet.

Kong OSS routes requests but does **not** validate the API-issued bearer
tokens. The FastAPI application validates their signature, issuer, audience,
and expiry. Kong must forward the `Authorization` header unchanged.

## Configuration and billing boundaries

- `.env.example` lists environment-variable names and safe placeholders.
- Payment amounts and subscription terms are configured in Razorpay Dashboard;
  the frontend cannot choose a plan or amount.
- Razorpay webhook signatures are verified against the raw request body.
- Webhook payloads are capped at 1 MB.
- Duplicate webhook events are idempotently ignored. Subscription state is
  persisted in MongoDB and is the source of truth for premium access.
- GitHub OAuth login and token issuance are handled by this service. The
  frontend is separate and must consume the token fragment on its configured
  callback page. The API does not store GitHub OAuth access tokens.
