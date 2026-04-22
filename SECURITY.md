# Salary Project Security Report

## Fixed During the Review

### 1. Import and import status without authentication (critical)
- **Before:** The `index` endpoint (POST - starts import from CRM24) and `api/import/status/` (GET) were accessible without login.
- **Risk:** Anyone could trigger imports, request status, overload the CRM API, and view progress.
- **Fixed:** The `@login_required` decorator was added to both views.

### 2. Arbitrary Python execution in the AI flow (critical)
- **Before:** Previously, the risk was tied to dynamic Python code execution in the AI path.
- **Risk:** This approach can allow unwanted data operations and makes a secure boundary harder to guarantee.
- **Current state:** The main AI path has been moved to **Function Calling (tool agent)** via a fixed set of server-side functions `crm_analytics_*`; no arbitrary user Python execution is used in the active flow.

---

## Recommendations (action required)

### 3. Secrets and production settings (high priority)

- **SECRET_KEY:** In production, always set `SECRET_KEY` via environment variables. Otherwise, `dev-insecure-secret-key` is used (the app fails in production mode, but this is still unacceptable for staging/test).
- **DEBUG:** Set `DEBUG=False` in production (via `DEBUG=0` or by omitting it in `.env`).
- **DB password:** In `settings.py`, the password is read from `DB_PASSWORD` (default is an empty string). In production, always set `DB_PASSWORD` in `.env`/deployment secrets and never store passwords in the repository.
- **ALLOWED_HOSTS:** Add your production domain to `ALLOWED_HOSTS` (currently only `.ngrok-free.app`, `localhost`, `127.0.0.1`).

### 4. HTTPS headers and cookies (high priority for production)

It is recommended to enable the following in production (for example, at the end of `settings.py` or in a separate profile):

```python
# Production security (uncomment when deploying over HTTPS)
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
```

### 5. API keys

- **OPENAI_API_KEY** and **CRM_WEBHOOK_BASE** are loaded from environment variables, which is correct. Keep them only in `.env` (and CI/deployment secrets), and do not commit `.env`.

### 6. Registration and access control

- The user registration page (`/register/`) is protected by `@login_required` and `@admin_required` - only admins can create accounts.
- `register_with_manager` (redirect to `/register?manager_id=...`) is not protected - anyone can trigger the redirect. Risk is low (only the existence of `manager_id` may be inferred). You may add `@login_required` to this view if needed.

### 7. Dependencies

- Update packages regularly: `pip list --outdated`; prioritize updates for Django and `requests`.
- Before deployment, check vulnerabilities: `pip install safety && safety check`.

---

## What Is Already Done Well

- CSRF middleware and CSRF validation for forms/API are enabled.
- Standard Django password validators are used (length, similarity to user attributes, common passwords).
- Sensitive views are protected by `@login_required` and `@admin_required` where required.
- User content is escaped in templates (for example, `|escape` for comments).
- The main AI path uses a limited set of server tools `crm_analytics_*` (Function Calling), without executing arbitrary user Python code.

---

## Current AI Flow (production)

In the current version, the main AI analytics path is based on **Function Calling (tool agent)**:

- the model calls a fixed set of server-side functions (`crm_analytics_*`);
- data access is limited by current UI filters and user permissions;
- the analytics flow runs in read-only mode with respect to business data;
- arbitrary user Python code execution is not used in the main AI flow.

## Legacy note

The legacy `CodeExecutor` sandbox path (dynamic Python execution) is not the current production path and is not used in the main AI flow.

Re-check date: 2026-04-22.
