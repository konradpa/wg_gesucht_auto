"""
WG-Gesucht API Client (Web-only)
Simplified version using web authentication only.
"""

import requests
import json
import re
from typing import Optional, Dict, List, Any


class WgGesuchtClient:
    """Unofficial API client for wg-gesucht.de (web auth only)"""

    BASE_URL = 'https://www.wg-gesucht.de'
    WEB_CLIENT_ID = 'wg_desktop_website'
    WEB_SMP_CLIENT = 'WG-Gesucht'
    WEB_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'

    def __init__(self):
        self.user_id: Optional[str] = None
        self.access_token: Optional[str] = None
        self.refresh_token_value: Optional[str] = None
        self.php_session: Optional[str] = None
        self.dev_ref_no: Optional[str] = None
        self.csrf_token: Optional[str] = None
        self.session = requests.Session()

    def _clear_auth_state(self) -> None:
        """Clear auth tokens and cookies."""
        self.user_id = None
        self.access_token = None
        self.refresh_token_value = None
        self.php_session = None
        self.dev_ref_no = None
        self.csrf_token = None
        self.session = requests.Session()

    def import_account(self, config: Dict) -> None:
        """Import saved session data"""
        self.user_id = config.get('user_id')
        self.access_token = config.get('access_token')
        self.refresh_token_value = config.get('refresh_token')
        self.php_session = config.get('php_session')
        self.dev_ref_no = config.get('dev_ref_no')
        self.csrf_token = config.get('csrf_token')
        
        # Restore cookies
        if self.php_session:
            self.session.cookies.set('PHPSESSID', self.php_session)
        if self.access_token:
            self.session.cookies.set('X-Access-Token', self.access_token)
        if self.refresh_token_value:
            self.session.cookies.set('X-Refresh-Token', self.refresh_token_value)
        if self.dev_ref_no:
            self.session.cookies.set('X-Dev-Ref-No', self.dev_ref_no)
        if self.user_id:
            self.session.cookies.set('X-User-Id', str(self.user_id))
        self.session.cookies.set('X-Client-Id', self.WEB_CLIENT_ID)

    def export_account(self) -> Dict:
        """Export session data for saving"""
        return {
            'user_id': self.user_id,
            'access_token': self.access_token,
            'refresh_token': self.refresh_token_value,
            'php_session': self.php_session,
            'dev_ref_no': self.dev_ref_no,
            'csrf_token': self.csrf_token,
        }

    def _headers(self, include_auth: bool = True, extra: Optional[Dict] = None) -> Dict[str, str]:
        """Build request headers"""
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

    def _update_tokens_from_response(self, response: requests.Response) -> None:
        """Extract tokens from response JSON/cookies."""
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

        # Also read from cookies
        cookies = self.session.cookies
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

    def _sync_session_state(self) -> None:
        """Fetch user_id/csrf_token from a logged-in page."""
        paths = (
            '/nachrichten.html',
            '/mein-wg-gesucht.html',
        )
        for path in paths:
            try:
                resp = self.session.get(f"{self.BASE_URL}{path}", timeout=30)
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

    def _request(self, method: str, path: str, params: Optional[Dict] = None,
                 payload: Optional[Dict] = None, attempt: int = 0,
                 handle_unauthorized: bool = True, include_auth: bool = True,
                 extra_headers: Optional[Dict] = None) -> Optional[requests.Response]:
        """Perform web request with auth handling"""
        url = f"{self.BASE_URL}{path}"
        headers = self._headers(include_auth=include_auth, extra=extra_headers)

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

            if response.status_code == 401 and handle_unauthorized and attempt < 1:
                if self._refresh_tokens():
                    return self._request(
                        method, path, params=params, payload=payload,
                        attempt=attempt + 1, handle_unauthorized=False,
                        include_auth=include_auth, extra_headers=extra_headers
                    )
            return response
        except requests.RequestException as e:
            print(f"Request error: {e}")
            return None

    def _refresh_tokens(self) -> bool:
        """Refresh access tokens."""
        for action in ('refresh_tokens', 'refresh'):
            resp = self._request(
                'PUT',
                f'/ajax/sessions.php?action={action}',
                handle_unauthorized=False,
            )
            if resp and resp.status_code in range(200, 300):
                self._update_tokens_from_response(resp)
                if self.access_token:
                    return True
        return False

    def login(self, email: str, password: str) -> bool:
        """Login with email and password."""
        self._clear_auth_state()
        
        # Prime session cookies
        self.session.get(f"{self.BASE_URL}/mein-wg-gesucht-login.html", timeout=30)

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
        response = self._request(
            'POST',
            '/ajax/sessions.php?action=login',
            payload=payload,
            handle_unauthorized=False,
            include_auth=False,
            extra_headers=headers,
        )

        if not response:
            return False

        if response.status_code in range(200, 300):
            self._update_tokens_from_response(response)
            if not self.access_token:
                self._refresh_tokens()
            if not self.user_id or not self.csrf_token:
                self._sync_session_state()
            if self.access_token:
                self.php_session = self.session.cookies.get('PHPSESSID')
                print(f"✓ Logged in as user {self.user_id}")
                return True
            print("✗ Login failed - no access token")
            return False

        print(f"✗ Login failed ({response.status_code}): {response.text[:200]}")
        return False

    def find_city(self, query: str) -> Optional[List[Dict]]:
        """Search for city by name"""
        url = f"/api/location/cities/names/{query}"
        response = self._request('GET', url)

        if response and response.status_code in range(200, 300):
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

        response = self._request('GET', '/api/asset/offers/', params=params)

        if response and response.status_code in range(200, 300):
            try:
                return response.json().get('_embedded', {}).get('offers', [])
            except Exception as e:
                print(f"Offers error: {e}")
                return None
        return None

    def get_offer_detail(self, offer_id: str) -> Optional[Dict]:
        """Get detailed information about an offer"""
        url = f'/api/public/offers/{offer_id}'
        response = self._request('GET', url)

        if response and response.status_code in range(200, 300):
            try:
                return response.json()
            except Exception as e:
                print(f"Offer detail error: {e}")
                return None
        return None

    def contact_offer(self, offer_id: str, message: str) -> Optional[Any]:
        """Send a message to an offer"""
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
            response = self._request(
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
                print(f"Contact failed ({response.status_code}): {response.text[:200]}")
                return None

        return None

    def get_conversations(self) -> Optional[Any]:
        """Get list of conversations"""
        response = self._request('GET', '/ajax/conversations.php?action=all-conversations-notifications')
        if response and response.status_code in range(200, 300):
            try:
                return response.json()
            except Exception as e:
                print(f"Conversations error: {e}")
                return None
        return None

    def my_profile(self) -> Optional[Dict]:
        """Get own profile"""
        if not self.user_id:
            return None
        url = f'/api/public/users/{self.user_id}'
        response = self._request('GET', url)

        if response and response.status_code in range(200, 300):
            try:
                return response.json()
            except Exception as e:
                print(f"Profile error: {e}")
                return None
        return None
