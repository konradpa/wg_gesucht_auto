# WG-Gesucht API Reverse Engineering Challenge

## Objective
Reverse engineer the WG-Gesucht API to enable sending messages to listings programmatically.

## Current Status: BLOCKED
The API authentication has been significantly updated. Login works but protected endpoints reject all auth attempts.

---

## What Works ✓

### 1. Login Endpoint
```
POST https://www.wg-gesucht.de/api/sessions
```

**Request:**
```json
{
  "login_email_username": "user@email.com",
  "login_password": "password",
  "client_id": "wg_mobile_app",
  "display_language": "de"
}
```

**Headers:**
```
Content-Type: application/json
X-Client-Id: wg_mobile_app
X-App-Version: 1.28.0
User-Agent: Mozilla/5.0 (Linux; Android 6.0; Google Build/MRA58K; wv) AppleWebKit/537.36
X-Requested-With: com.wggesucht.android
```

**Response (202):**
```json
{
  "status": 202,
  "detail": {
    "token": "JWT_TOKEN_HERE"
  }
}
```

**JWT Payload decoded:**
```json
{
  "iss": "WG-Gesucht",
  "sub": "12345678",      // This is the user_id
  "jti": "38xGS4hJQ59EVLtsK41Stcgl4VkvitmiXMNtcrvT",  // JWT ID
  "iat": 1768301867,      // Issued at
  "exp": 1768305467       // Expires (1 hour)
}
```

**CRITICAL:** No PHPSESSID cookie is returned. No refresh_token. No access_token. Only the JWT.

### 2. City Search (Public endpoint - works)
```
GET https://www.wg-gesucht.de/api/location/cities/names/Berlin
```
Returns 200 with city data including `city_id: 8` for Berlin.

---

## What Fails ✗

### 1. Conversations Endpoint - 401 Unauthorized
```
GET https://www.wg-gesucht.de/api/conversations/user/{user_id}
```

### 2. Contact/Send Message Endpoint - 401 Unauthorized  
```
POST https://www.wg-gesucht.de/api/conversations
```
**Payload:**
```json
{
  "user_id": "12345678",
  "ad_type": 0,
  "ad_id": 12345678,
  "messages": [{"content": "Hello", "message_type": "text"}]
}
```

### 3. Offers Endpoint - Inconsistent (sometimes 400, sometimes 200)
```
GET https://www.wg-gesucht.de/api/asset/offers/
```
Params: city_id, categories, rMax, sMin, limit

### 4. Token Refresh - 405 Method Not Allowed
```
POST https://www.wg-gesucht.de/api/sessions/users/{user_id}
```
The old refresh token endpoint no longer works.

---

## Auth Methods I Tried (All Failed for Protected Endpoints)

```python
# 1. Standard Bearer
headers = {'Authorization': f'Bearer {jwt_token}'}

# 2. X-Authorization (what old API used)
headers = {'X-Authorization': f'Bearer {jwt_token}'}

# 3. Both Authorization headers + User ID
headers = {
    'Authorization': f'Bearer {jwt_token}',
    'X-Authorization': f'Bearer {jwt_token}',
    'X-User-Id': user_id
}

# 4. Token in Cookie
headers = {'Cookie': f'X-Access-Token={jwt_token}; X-User-Id={user_id}'}

# 5. Hybrid: Web session (PHPSESSID) + API JWT
session = requests.Session()
session.post('https://www.wg-gesucht.de/ajax/sessions.php', data={...})  # Gets PHPSESSID
# Then use PHPSESSID cookie + JWT token together
# Result: PHPSESSID obtained, but protected endpoints still return 401
```

---

## Old API vs New API

### OLD API (from Zero3141/WgGesuchtAPI - no longer works)
Login returned:
```json
{
  "detail": {
    "access_token": "...",
    "refresh_token": "...", 
    "user_id": "12345678",
    "dev_ref_no": "..."
  }
}
```
Plus `PHPSESSID` cookie.

### NEW API (current)
Login returns:
```json
{
  "detail": {
    "token": "JWT_TOKEN_HERE"
  }
}
```
No cookies. No refresh token. No dev_ref_no.

---

## Hypotheses to Test

1. **Two-Step Auth:** Maybe the JWT is just step 1, and there's a second call to exchange it for a session?

2. **Missing Header:** Perhaps there's a new required header like `X-Device-Id` or `X-Session-Id`?

3. **Different Endpoint:** Maybe authenticated endpoints moved to `/api/v2/` or similar?

4. **Cookie Required:** Maybe we need to:
   - First call the web login (`/ajax/sessions.php`) to get PHPSESSID
   - Then call API login to get JWT
   - Then use both somehow?

5. **Mobile App Changed:** The app version constant might need updating. Current: `1.28.0`

6. **OAuth Flow:** Maybe they switched to OAuth2 with authorization codes?

7. **Request Signing:** Maybe requests need to be signed with the JWT in a specific way?

---

## Web Login Discovery

Web login to `/ajax/sessions.php` returns:
- Status: 200
- Body: Empty
- Sets cookies: `PHPSESSID`, `X-Client-Id=wg_desktop_website`

But this session alone cannot access API endpoints either.

---

## NEW FINDINGS (Desktop Web App JS)

The desktop site exposes a **different auth flow** and **different endpoints** than the mobile app. This is likely the path we need for sending messages without browser automation.

### 1) Desktop Ajax Auth Flow

**Login (step 1):**
```
POST https://www.wg-gesucht.de/ajax/sessions.php?action=login
```
**Body (JSON):**
```json
{
  "login_email_username": "user@email.com",
  "login_password": "password",
  "login_form_auto_login": "0",
  "display_language": "de"
}
```
**Headers (minimum):**
```
Accept: application/json
Content-Type: application/json
X-Requested-With: XMLHttpRequest
X-Client-Id: wg_desktop_website
X-Smp-Client: WG-Gesucht
```

**Observed response:** `202` with `detail.token` (login challenge token). This matches the 2FA flow in the web JS.

**Verify (step 2, required if login returns 202):**
```
POST https://www.wg-gesucht.de/ajax/sessions.php?action=verify_login
```
**Body (JSON):**
```json
{
  "token": "<login_token_from_step_1>",
  "verification_code": "123456"
}
```

Expected success response likely returns **access_token / refresh_token / user_id / dev_ref_no / csrf_token** (old-style tokens), and/or sets cookies like `X-Access-Token`, `X-Refresh-Token`, `X-Dev-Ref-No`.

**Refresh tokens:**
```
PUT https://www.wg-gesucht.de/ajax/sessions.php?action=refresh_tokens
```
The web JS also references `action=refresh` in the ApiCaller fallback.

### 2) Desktop Ajax Headers (from ApiCaller)

For authorized calls, the web app uses **X-Authorization** (not Authorization) and cookies:
```
X-User-Id: <user_id>
X-Authorization: Bearer <X-Access-Token>
X-Client-Id: wg_desktop_website
X-Smp-Client: WG-Gesucht
X-Dev-Ref-No: <dev_ref_no>
Accept: application/json
Content-Type: application/json
X-Requested-With: XMLHttpRequest
```

### 3) Conversations Endpoints (Desktop)

JS uses **ajax + api mix**:

- **Create conversation (send message):**
  ```
  POST /ajax/conversations.php?action=conversations
  ```
- **List conversations (notifications):**
  ```
  GET /ajax/conversations.php?action=all-conversations-notifications
  ```
- **Unread count:**
  ```
  GET /api/conversations/users/{user_id}/unread
  ```

There are also bulk and tagging endpoints under `/api/conversation-*`.

---

## Implication

The mobile JWT is likely **no longer sufficient** for protected endpoints. The desktop flow still expects **legacy access/refresh tokens + dev_ref_no + csrf_token**, which are only issued after the **verify_login** step. We should switch messaging to the **/ajax/conversations.php** flow once we can complete verification.

---

## Files in This Project

```
wg_gesucht_auto/
├── config.yaml          # Credentials (email/password configured)
├── src/wg_api.py        # Current API client implementation
├── debug_api.py         # Full API debugging script
├── debug_hybrid.py      # Tests combining web+API auth
├── debug_web_login.py   # Tests web login flow
├── capture_network.py   # Playwright script to capture real requests
```

---

## Test Credentials
- Do not store real credentials in this file.
- Use placeholders and load real values from `config.yaml` locally.

---

## Suggested Next Steps

1. **Decompile the Android APK** to see exact API calls and headers
2. **Use mitmproxy/Charles** with an Android emulator to capture real app traffic
3. **Check if app uses certificate pinning** and bypass it
4. **Look for newer forks** of WgGesuchtAPI that might have updates
5. **Try websocket endpoints** - maybe real-time messaging uses WS?
6. **Search for any device registration** endpoint that might be needed first

---

## Run Debug Scripts

```bash
cd /Users/macbookair/Desktop/wg_gesucht_auto
source .venv/bin/activate

# Full API debug
python3 debug_api.py

# Hybrid auth test
python3 debug_hybrid.py

# Capture real browser traffic
python3 capture_network.py
```

Good luck! 🍀
