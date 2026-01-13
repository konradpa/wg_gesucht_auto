"""
WG-Gesucht API Client
Adapted from https://github.com/Zero3141/WgGesuchtAPI with improvements
"""

import requests
import json
import time
import re
from typing import Optional, Dict, List, Any


class WgGesuchtClient:
    """Unofficial API client for wg-gesucht.de"""

    BASE_URL = 'https://www.wg-gesucht.de'
    API_URL = 'https://www.wg-gesucht.de/api/{}'
    APP_VERSION = '1.28.0'
    APP_PACKAGE = 'com.wggesucht.android'
    CLIENT_ID = 'wg_mobile_app'
    WEB_CLIENT_ID = 'wg_desktop_website'
    WEB_SMP_CLIENT = 'WG-Gesucht'
    USER_AGENT = 'Mozilla/5.0 (Linux; Android 6.0; Google Build/MRA58K; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/74.0.3729.186 Mobile Safari/537.36'
    WEB_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'

    def __init__(self):
        self.auth_mode: str = 'mobile'
        self.user_id: Optional[str] = None
        self.access_token: Optional[str] = None
        self.refresh_token_value: Optional[str] = None
        self.php_session: Optional[str] = None
        self.dev_ref_no: Optional[str] = None
        self.csrf_token: Optional[str] = None
        self.login_token: Optional[str] = None
        self.session = requests.Session()
        self.web_session = requests.Session()

    def set_auth_mode(self, mode: str) -> None:
        """Set authentication mode ('mobile' or 'web')."""
        mode = (mode or '').strip().lower()
        if mode not in {'mobile', 'web'}:
            raise ValueError(f"Unsupported auth_mode: {mode}")
        self.auth_mode = mode

    def _clear_web_auth_state(self) -> None:
        """Clear web auth tokens and cookies to avoid mixing sessions."""
        self.user_id = None
        self.access_token = None
        self.refresh_token_value = None
        self.php_session = None
        self.dev_ref_no = None
        self.csrf_token = None
        self.login_token = None
        self.web_session = requests.Session()

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, 
                 payload: Optional[Dict] = None, attempt: int = 0) -> Optional[requests.Response]:
        """Perform API request with automatic token refresh"""
        
        url = self.API_URL.format(endpoint)

        # Build cookies
        cookies = []
        if self.php_session:
            cookies.append(f'PHPSESSID={self.php_session}')
        cookies.append(f'X-Client-Id={self.CLIENT_ID}')
        if self.refresh_token_value:
            cookies.append(f'X-Refresh-Token={self.refresh_token_value}')
        if self.access_token:
            cookies.append(f'X-Access-Token={self.access_token}')
        if self.dev_ref_no:
            cookies.append(f'X-Dev-Ref-No={self.dev_ref_no}')
        
        cookie_header = '; '.join(cookies)

        # Build headers
        headers = {
            'X-App-Version': self.APP_VERSION,
            'User-Agent': self.USER_AGENT,
            'Content-Type': 'application/json',
            'Accept-Encoding': 'gzip, deflate',
            'Accept': 'application/json',
            'X-Client-Id': self.CLIENT_ID,
            'Cookie': cookie_header,
            'X-Requested-With': self.APP_PACKAGE,
        }
        
        if self.access_token:
            # Use both headers for compatibility
            headers['Authorization'] = f'Bearer {self.access_token}'
            headers['X-Authorization'] = f'Bearer {self.access_token}'
        if self.user_id:
            headers['X-User-Id'] = str(self.user_id)
        if self.dev_ref_no:
            headers['X-Dev-Ref-No'] = self.dev_ref_no
        if not self.access_token:
            headers['Origin'] = 'file://'

        # Perform request
        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=json.dumps(payload) if payload else None,
                timeout=30
            )

            if response.status_code in range(200, 300):
                return response

            elif response.status_code == 401 and attempt < 1:
                # Try to refresh token (may not work with new JWT API)
                print("Access token expired, attempting refresh...")
                if self._refresh_token():
                    return self._request(method, endpoint, params, payload, attempt + 1)
                else:
                    print("Token refresh failed - re-login may be needed")
                    return None
            else:
                print(f"Request failed ({response.status_code}): {response.text[:200]}")
                return None

        except requests.RequestException as e:
            print(f"Request error: {e}")
            return None

    def import_account(self, config: Dict) -> None:
        """Import saved session data"""
        self.user_id = config.get('user_id')
        self.access_token = config.get('access_token')
        self.refresh_token_value = config.get('refresh_token')
        self.php_session = config.get('php_session')
        self.dev_ref_no = config.get('dev_ref_no')
        self.csrf_token = config.get('csrf_token')
        if config.get('auth_mode'):
            self.auth_mode = config.get('auth_mode')
        if self.auth_mode == 'web':
            if self.php_session:
                self.web_session.cookies.set('PHPSESSID', self.php_session)
            if self.access_token:
                self.web_session.cookies.set('X-Access-Token', self.access_token)
            if self.refresh_token_value:
                self.web_session.cookies.set('X-Refresh-Token', self.refresh_token_value)
            if self.dev_ref_no:
                self.web_session.cookies.set('X-Dev-Ref-No', self.dev_ref_no)
            if self.user_id:
                self.web_session.cookies.set('X-User-Id', str(self.user_id))
            self.web_session.cookies.set('X-Client-Id', self.WEB_CLIENT_ID)

    def export_account(self) -> Dict:
        """Export session data for saving"""
        return {
            'user_id': self.user_id,
            'access_token': self.access_token,
            'refresh_token': self.refresh_token_value,
            'php_session': self.php_session,
            'dev_ref_no': self.dev_ref_no,
            'csrf_token': self.csrf_token,
            'auth_mode': self.auth_mode,
        }

    def login(self, email: str, password: str, verification_code: Optional[str] = None,
              prompt_for_code: bool = True) -> bool:
        """Login with email and password (mobile or web depending on auth_mode)."""
        if self.auth_mode == 'web':
            return self.login_web(email, password, verification_code, prompt_for_code)
        return self.login_mobile(email, password)

    def login_mobile(self, email: str, password: str) -> bool:
        """Login via mobile API with email and password."""
        
        payload = {
            'login_email_username': email,
            'login_password': password,
            'client_id': self.CLIENT_ID,
            'display_language': 'de'
        }

        response = self._request('POST', 'sessions', payload=payload)

        if response:
            try:
                data = response.json()
                detail = data.get('detail', {})
                
                # Check if we have a JWT token (new API)
                if 'token' in detail and isinstance(detail['token'], str):
                    self.access_token = detail['token']
                    self.php_session = response.cookies.get('PHPSESSID')
                    
                    # Decode JWT to get user_id
                    import base64
                    try:
                        token_parts = self.access_token.split('.')
                        if len(token_parts) >= 2:
                            payload = token_parts[1]
                            payload += '=' * (4 - len(payload) % 4)
                            decoded = json.loads(base64.b64decode(payload))
                            self.user_id = str(decoded.get('sub') or decoded.get('user_id') or '')
                    except Exception:
                        self.user_id = "unknown"
                    
                    self.refresh_token_value = detail.get('refresh_token', '')
                    self.dev_ref_no = detail.get('dev_ref_no', '')
                    
                elif 'access_token' in detail:
                    # Old API structure
                    self.access_token = detail.get('access_token')
                    self.refresh_token_value = detail.get('refresh_token')
                    self.user_id = str(detail.get('user_id') or '')
                    self.dev_ref_no = detail.get('dev_ref_no')
                    self.php_session = response.cookies.get('PHPSESSID')
                
                if self.access_token:
                    print(f"✓ Logged in successfully as user {self.user_id}")
                    return True
                else:
                    print(f"✗ Login failed - no access token")
                    return False
                    
            except Exception as e:
                print(f"Login parsing error: {e}")
                return False
        return False

    def _web_headers(self, include_auth: bool = True, extra: Optional[Dict] = None) -> Dict[str, str]:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'X-Client-Id': self.WEB_CLIENT_ID,
            'X-Smp-Client': self.WEB_SMP_CLIENT,
            'User-Agent': self.WEB_USER_AGENT,
        }
        if include_auth and self.user_id:
            headers['X-User-Id'] = str(self.user_id)
        if include_auth and self.access_token:
            headers['X-Authorization'] = f'Bearer {self.access_token}'
        if include_auth and self.dev_ref_no:
            headers['X-Dev-Ref-No'] = self.dev_ref_no
        if extra:
            headers.update(extra)
        return headers

    def _update_web_tokens_from_response(self, response: requests.Response) -> None:
        """Extract tokens/csrf/user_id from response JSON/cookies."""
        try:
            data = response.json()
        except Exception:
            data = {}

        detail = data.get('detail', {}) if isinstance(data, dict) else {}
        if isinstance(detail, dict):
            if detail.get('access_token'):
                self.access_token = detail.get('access_token')
            if detail.get('refresh_token'):
                self.refresh_token_value = detail.get('refresh_token')
            if detail.get('user_id'):
                self.user_id = str(detail.get('user_id'))
            if detail.get('dev_ref_no'):
                self.dev_ref_no = detail.get('dev_ref_no')
            if detail.get('csrf_token'):
                self.csrf_token = detail.get('csrf_token')

        # Also read from cookies if present
        cookies = self.web_session.cookies
        if not self.access_token:
            self.access_token = cookies.get('X-Access-Token')
        if not self.refresh_token_value:
            self.refresh_token_value = cookies.get('X-Refresh-Token')
        if not self.dev_ref_no:
            self.dev_ref_no = cookies.get('X-Dev-Ref-No')
        if not self.user_id:
            user_id_cookie = cookies.get('X-User-Id')
            if user_id_cookie:
                self.user_id = str(user_id_cookie)
        if not self.csrf_token:
            self.csrf_token = cookies.get('csrf_token') or cookies.get('X-CSRF-Token')
        if not self.php_session:
            self.php_session = cookies.get('PHPSESSID')

    def _sync_web_session_state(self) -> None:
        """Fetch user_id/csrf_token from a logged-in page."""
        paths = (
            '/nachrichten.html',
            '/mein-wg-gesucht.html',
            '/mein-wg-gesucht-profil.html',
        )
        for path in paths:
            try:
                resp = self.web_session.get(f"{self.BASE_URL}{path}", timeout=30)
            except requests.RequestException:
                continue
            if resp.status_code != 200:
                continue
            text = resp.text

            if not self.user_id:
                for pattern in (
                    r'\buser_id\b\s*[:=]\s*[\'"]?(\d+)',
                    r'data-user-id=\"(\d+)\"',
                ):
                    match = re.search(pattern, text)
                    if match:
                        self.user_id = match.group(1)
                        break

            if not self.csrf_token:
                match = re.search(r'name=\"csrf_token\"[^>]*value=\"([^\"]+)\"', text)
                if not match:
                    match = re.search(r'data-csrf_token=\"([^\"]+)\"', text)
                if match:
                    self.csrf_token = match.group(1)

            if self.user_id and self.csrf_token:
                return

    def _web_request(self, method: str, path: str, params: Optional[Dict] = None,
                     payload: Optional[Dict] = None, attempt: int = 0,
                     handle_unauthorized: bool = True, include_auth: bool = True,
                     extra_headers: Optional[Dict] = None) -> Optional[requests.Response]:
        url = f"{self.BASE_URL}{path}"
        headers = self._web_headers(include_auth=include_auth, extra=extra_headers)

        try:
            response = self.web_session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=json.dumps(payload) if payload else None,
                timeout=30
            )

            if response.status_code in range(200, 300):
                return response

            if response.status_code == 401 and handle_unauthorized and attempt < 1:
                if self._refresh_web_tokens():
                    return self._web_request(
                        method, path, params=params, payload=payload,
                        attempt=attempt + 1, handle_unauthorized=False,
                        include_auth=include_auth, extra_headers=extra_headers
                    )
            return response
        except requests.RequestException as e:
            print(f"Web request error: {e}")
            return None

    def _refresh_web_tokens(self) -> bool:
        """Refresh tokens for web auth."""
        for action in ('refresh_tokens', 'refresh'):
            resp = self._web_request(
                'PUT',
                f'/ajax/sessions.php?action={action}',
                handle_unauthorized=False,
            )
            if resp and resp.status_code in range(200, 300):
                self._update_web_tokens_from_response(resp)
                if self.access_token:
                    return True

            resp = self._web_request(
                'PUT',
                f'/ajax/sessions.php?action={action}',
                handle_unauthorized=False,
                include_auth=False,
            )
            if resp and resp.status_code in range(200, 300):
                self._update_web_tokens_from_response(resp)
                if self.access_token:
                    return True
        return False

    def login_web(self, email: str, password: str, verification_code: Optional[str] = None,
                  prompt_for_code: bool = True) -> bool:
        """Login via web Ajax flow; handles 2FA verification when required."""
        self._clear_web_auth_state()
        # Prime session cookies
        self.web_session.get(f"{self.BASE_URL}/mein-wg-gesucht-login.html", timeout=30)

        payload = {
            'login_email_username': email,
            'login_password': password,
            'login_form_auto_login': '0',
            'display_language': 'de'
        }
        headers = {
            'Origin': self.BASE_URL,
            'Referer': f'{self.BASE_URL}/mein-wg-gesucht-login.html',
        }
        response = self._web_request(
            'POST',
            '/ajax/sessions.php?action=login',
            payload=payload,
            handle_unauthorized=False,
            include_auth=False,
            extra_headers=headers,
        )

        if not response:
            return False

        if response.status_code == 202:
            try:
                data = response.json()
                self.login_token = data.get('detail', {}).get('token')
            except Exception:
                self.login_token = None

            if not self.login_token:
                print("✗ Web login failed - no login token")
                return False

            if not verification_code and prompt_for_code:
                verification_code = input("Enter WG-Gesucht verification code: ").strip()

            if not verification_code:
                print("⚠ Web login requires verification code")
                return False

            return self.verify_login_web(verification_code)

        if response.status_code in range(200, 300):
            self._update_web_tokens_from_response(response)
            if not self.access_token:
                self._refresh_web_tokens()
            if not self.user_id or not self.csrf_token:
                self._sync_web_session_state()
            if self.access_token:
                self.php_session = self.web_session.cookies.get('PHPSESSID')
                print(f"✓ Web login successful as user {self.user_id}")
                return True
            print("✗ Web login failed - no access token")
            return False

        print(f"✗ Web login failed ({response.status_code}): {response.text[:200]}")
        return False

    def verify_login_web(self, verification_code: str) -> bool:
        """Verify web login using a 2FA code."""
        if not self.login_token:
            print("✗ Missing login token; run login_web first")
            return False

        payload = {
            'token': self.login_token,
            'verification_code': verification_code,
        }
        response = self._web_request(
            'POST',
            '/ajax/sessions.php?action=verify_login',
            payload=payload,
            handle_unauthorized=False,
            include_auth=False,
            extra_headers={'Origin': self.BASE_URL},
        )

        if response and response.status_code in range(200, 300):
            self._update_web_tokens_from_response(response)
            if not self.access_token:
                self._refresh_web_tokens()
            if not self.user_id or not self.csrf_token:
                self._sync_web_session_state()
            self.login_token = None
            if self.access_token:
                print(f"✓ Web login verified as user {self.user_id}")
                return True
            print("✗ Web login verification succeeded but no access token")
            return False

        if response is not None:
            print(f"✗ Web login verification failed ({response.status_code}): {response.text[:200]}")
        return False

    def _refresh_token(self) -> bool:
        """Refresh access token"""
        
        payload = {
            'grant_type': 'refresh_token',
            'access_token': self.access_token,
            'refresh_token': self.refresh_token_value,
            'client_id': self.CLIENT_ID,
            'dev_ref_no': self.dev_ref_no,
            'display_language': 'de'
        }

        url = f'sessions/users/{self.user_id}'
        response = self._request('POST', url, payload=payload)

        if response:
            try:
                data = response.json()
                detail = data.get('detail', {})
                self.access_token = detail.get('access_token')
                self.refresh_token_value = detail.get('refresh_token')
                self.dev_ref_no = detail.get('dev_ref_no')
                return True
            except Exception as e:
                print(f"Token refresh parsing error: {e}")
                return False
        return False

    def find_city(self, query: str) -> Optional[List[Dict]]:
        """Search for city by name"""
        
        url = f'location/cities/names/{query}'
        response = self._request('GET', url)

        if response:
            try:
                return response.json().get('_embedded', {}).get('cities', [])
            except Exception as e:
                print(f"City search error: {e}")
                return None
        return None

    def get_offers(self, city_id: str, categories: str = "0",
                   max_rent: int = 1000, min_size: int = 10,
                   page: int = 1, limit: int = 20) -> Optional[List[Dict]]:
        """
        Get available offers
        
        Args:
            city_id: City ID from find_city()
            categories: 0=WG-Zimmer, 1=1-Zimmer-Wohnung, 2=Wohnung, 3=Haus
            max_rent: Maximum rent in EUR
            min_size: Minimum size in m²
            page: Page number
        """
        
        params = {
            'ad_type': '0',
            'categories': categories,
            'city_id': city_id,
            'noDeact': '1',
            'img': '1',
            'limit': str(limit),
            'rMax': str(max_rent),
            'sMin': str(min_size),
            'rent_types': categories,
            'page': str(page)
        }

        response = self._request('GET', 'asset/offers/', params=params)

        if response:
            try:
                return response.json().get('_embedded', {}).get('offers', [])
            except Exception as e:
                print(f"Offers error: {e}")
                return None
        return None

    def get_offer_detail(self, offer_id: str) -> Optional[Dict]:
        """Get detailed information about an offer"""
        
        url = f'public/offers/{offer_id}'
        response = self._request('GET', url)

        if response:
            try:
                return response.json()
            except Exception as e:
                print(f"Offer detail error: {e}")
                return None
        return None

    def contact_offer(self, offer_id: str, message: str) -> Optional[List[Dict]]:
        """Send a message to an offer"""
        if self.auth_mode == 'web':
            return self.contact_offer_web(offer_id, message)
        
        payload = {
            'user_id': self.user_id,
            'ad_type': 0,
            'ad_id': int(offer_id),
            'messages': [
                {
                    'content': message,
                    'message_type': 'text'
                }
            ]
        }

        response = self._request('POST', 'conversations', payload=payload)

        if response:
            try:
                return response.json().get('messages', [])
            except Exception as e:
                print(f"Contact error: {e}")
                return None
        return None

    def contact_offer_web(self, offer_id: str, message: str) -> Optional[Any]:
        """Send a message to an offer via web Ajax endpoint."""
        base_payload = {
            'ad_type': 0,
            'ad_id': int(offer_id),
        }
        if self.user_id:
            base_payload['user_id'] = str(self.user_id)
        if self.csrf_token:
            base_payload['csrf_token'] = self.csrf_token

        payload_variants = [
            {
                **base_payload,
                'messages': [{'content': message, 'message_type': 'text'}],
            },
            {
                **base_payload,
                'nachricht_freitext': message,
            },
        ]

        referer = f"{self.BASE_URL}/{offer_id}.html"
        extra_headers = {
            'Origin': self.BASE_URL,
            'Referer': referer,
        }

        for payload in payload_variants:
            response = self._web_request(
                'POST',
                '/ajax/conversations.php?action=conversations',
                payload=payload,
                extra_headers=extra_headers,
            )
            if response and response.status_code in range(200, 300):
                try:
                    return response.json()
                except Exception:
                    return {'status': response.status_code}
            if response is not None and response.status_code != 400:
                # Non-validation errors shouldn't be retried with another payload
                print(f"Web contact failed ({response.status_code}): {response.text[:200]}")
                return None

        return None

    def get_conversations(self, page: int = 1) -> Optional[List[Dict]]:
        """Get list of conversations"""
        if self.auth_mode == 'web':
            return self.get_conversations_web()
        
        url = f'conversations/user/{self.user_id}'
        params = {
            'page': str(page),
            'limit': '25',
            'language': 'de',
            'filter_type': '0'
        }

        response = self._request('GET', url, params=params)

        if response:
            try:
                return response.json().get('_embedded', {}).get('conversations', [])
            except Exception as e:
                print(f"Conversations error: {e}")
                return None
        return None

    def get_conversations_web(self) -> Optional[Any]:
        """Get list of conversations via web Ajax endpoint."""
        response = self._web_request('GET', '/ajax/conversations.php?action=all-conversations-notifications')
        if response:
            try:
                return response.json()
            except Exception as e:
                print(f"Web conversations error: {e}")
                return None
        return None

    def my_profile(self) -> Optional[Dict]:
        """Get own profile"""
        
        url = f'public/users/{self.user_id}'
        response = self._request('GET', url)

        if response:
            try:
                return response.json()
            except Exception as e:
                print(f"Profile error: {e}")
                return None
        return None
