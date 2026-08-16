# Security

This app holds personal health data (HRV, sleep, resting HR, weight, power) and
talks to a third-party account (Garmin Connect) using your real credentials.
That combination is worth being explicit about.

## Reporting a vulnerability

Open a GitHub issue for anything non-sensitive. For something that shouldn't be
public before it's fixed, use GitHub's **Security → Report a vulnerability**
(private disclosure) rather than a public issue.

## What this project does with your credentials

**You bring your own.** Nothing in this repo is pre-configured with anyone's
keys, and no credential of any kind is committed — see "What is never
committed" below.

| Credential | How it's entered | How it's stored |
|---|---|---|
| Garmin email + password | `python -m scripts.set_secrets` (hidden CLI prompt) | RSA-OAEP encrypted at rest |
| Anthropic API key | same | RSA-OAEP encrypted at rest |
| intervals.icu API key | same | RSA-OAEP encrypted at rest |
| Firebase service account | a JSON file **you** place outside the repo | referenced by path only |

### Encryption at rest

`config/secrets.py` encrypts secrets with a 4096-bit RSA-OAEP keypair:

- **Ciphertext** → `data/secrets.enc.json` (inside the repo folder, gitignored)
- **Private key** → `~/.garmin-trainer-dashboard/keys/private_key.pem`
  (**outside** the repo entirely, mode `0600`)

Splitting them is the point: copying or zipping the project directory yields
ciphertext with no key to open it.

Secrets are decrypted transiently in memory, on each access, via properties on
`config/settings.py`. They are never written back in plaintext.

**Threat model:** this protects against *the project directory leaking in
isolation* — an accidental commit, a shared folder, a backup, a support bundle.
It does **not** protect against a fully compromised user account or disk, where
the private key is readable too. It is not a substitute for full-disk
encryption.

### Credential entry is CLI-only, deliberately

There is no web form or API endpoint anywhere in this app that accepts a Garmin
password. That is an intentional constraint, not an omission: a terminal prompt
run once locally is meaningfully less attack surface than an HTTP endpoint for a
third-party account password. **Please don't add one.**

### Your Garmin password reaches a third-party package

The app does not talk to Garmin's servers itself. It spawns
[`@nicolasvegam/garmin-connect-mcp`](https://github.com/Nicolasvegam/garmin-connect-mcp)
as a subprocess and passes `GARMIN_EMAIL` / `GARMIN_PASSWORD` to it as
environment variables at spawn time (never as tool arguments, never over a
network call this app makes). That package performs the actual Garmin login.

**This means your Garmin password's safety depends on a third-party npm package
that this project does not control.** Pin a version you've reviewed if that
matters to you. Garmin has no official public API and no OAuth flow for this
data, so there is no token-based alternative that avoids handing over a password.

## Authentication

Every API route requires a valid Firebase ID token — enforced app-wide via
`dependencies=[Depends(verify_token)]` on the FastAPI app, so routes are
protected by default rather than one decorator at a time.

Because it's a single-user app, a valid token isn't sufficient: the signed-in
account's email must also match `ALLOWED_EMAIL`. Someone signing in with their
own Google account gets a 403.

**Fails closed.** If Firebase isn't configured, there is nothing to verify a
token against, so the API returns `503` for every request rather than serving
data unauthenticated. To run locally before setting Firebase up, set
`ALLOW_UNAUTHENTICATED_LOCAL_DEV=true` — which logs a warning on every request.
Never set it on anything reachable from a network.

The static-file mount that serves the built frontend intentionally sits outside
this check: the browser can't attach a Firebase token before the login page's
own JavaScript has loaded. It serves `frontend/dist` only — no data.

## What is never committed

`.gitignore` excludes, and no commit in this repo's history has ever contained:

- `.env`, `frontend/.env.local`, `deploy/env.yaml`
- `data/` — including `secrets.enc.json` (ciphertext) and `local_store.json`
  (your cached health data and GPS tracks)
- `*.pem`, `firebase-credentials.json`
- `config/athlete_profile.json` — your physiology

Every `*.example` counterpart is committed with placeholder values only. The
example physiology in `config/athlete_profile.example.json` is invented data for
a ~70 kg rider and is not anyone's real numbers.

If you fork this, **check your own `data/` directory is ignored before your
first commit.** It contains your GPS tracks — ride start points reveal home
addresses.

## Handling untrusted input

- **Uploaded activity files** (`.fit` / `.gpx` / `.tcx`) are parsed with
  `defusedxml`, not stdlib `ElementTree`, to avoid entity-expansion DoS.
- **Bring-your-own-algorithm** (`services/custom_model.py`) does **not** execute
  remote code. It POSTs to an endpoint you configure and accepts only a fixed
  set of numeric parameters, each validated and clamped to physiological bounds;
  unknown keys are rejected and an empty survivor set fails the proposal.
- **Ask-your-own-data** (`services/data_query.py`) is a deterministic regex
  parser over a bounded metric/window vocabulary — not an LLM, and not a
  query-string interpolator. Unrecognised phrasing returns "here's what I can
  answer" rather than guessing.

## Redacted Mode

The Redacted Mode toggle hides fitness-revealing numbers (FTP, power, W/kg, HRV,
weight, TSS) for screen-sharing, and disables the Coach tab entirely because
free-form LLM output can't be reliably redacted.

**It is a client-side display toggle, not an access-control boundary.** The API
still returns the underlying values. Don't rely on it to protect data from
someone with access to the browser's network tab.

## Known limitations

- Single-user by design. There is no multi-tenancy, and no per-user data
  isolation beyond the single `ALLOWED_EMAIL` check.
- Uploaded files are read fully into memory with no size cap (authenticated
  users only).
- Firebase web config in `frontend/` is public by design — it ships in every
  client bundle. Access control comes from Firestore rules and the
  allowed-email check, not from hiding those values.
