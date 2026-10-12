"""
ImmoScout24 API Client (mobile API, read-only)

Uses the undocumented API of the ImmoScout24 mobile app. The endpoints and
user agents were reverse-engineered by the Fredy project
(https://github.com/orangecoding/fredy, lib/services/immoscout/mobileApi.js).
"""

import requests
from typing import Optional, Dict, List


class ImmoScoutClient:
    """Unofficial client for api.mobile.immobilienscout24.de"""

    BASE_URL = 'https://api.mobile.immobilienscout24.de'
    EXPOSE_URL = 'https://www.immobilienscout24.de/expose/'
    # The search and exposé endpoints expect different app versions.
    SEARCH_USER_AGENT = 'ImmoScout_28.1_26.5.2_._'
    EXPOSE_USER_AGENT = 'ImmoScout_27.3_26.0_._'

    def __init__(self):
        self.session = requests.Session()

    def search(self, geocode: str, real_estate_type: str = 'apartmentrent',
               max_price: Optional[int] = None, min_size: Optional[int] = None,
               min_rooms: Optional[float] = None, price_type: str = 'calculatedtotalrent',
               page: int = 1) -> Optional[List[Dict]]:
        """
        Get one page of listings, newest first.

        Args:
            geocode: Region path, e.g. '/de/hamburg/hamburg' or
                '/de/hamburg/hamburg/altona/altona-altstadt'
            real_estate_type: 'apartmentrent', 'houserent', 'flatshareroom', ...
            max_price: Maximum rent in EUR
            min_size: Minimum living space in m²
            min_rooms: Minimum number of rooms
            price_type: 'calculatedtotalrent' (warm, apartments only) or 'rentpermonth' (cold)
            page: Page number, starting at 1
        """
        params = {
            'searchType': 'region',
            'geocodes': geocode,
            'realestatetype': real_estate_type,
            'sorting': '-firstactivation',
            'pagenumber': str(page),
        }
        if real_estate_type.endswith('rent'):
            params['pricetype'] = price_type
        if max_price:
            params['price'] = f'-{float(max_price)}'
        if min_size:
            params['livingspace'] = f'{float(min_size)}-'
        if min_rooms:
            params['numberofrooms'] = f'{float(min_rooms)}-'

        try:
            response = self.session.post(
                f'{self.BASE_URL}/search/list',
                params=params,
                headers={
                    'User-Agent': self.SEARCH_USER_AGENT,
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                },
                json={'supportedResultListTypes': [], 'userData': {}},
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"Request error: {e}")
            return None

        if response.status_code not in range(200, 300):
            # 412 names the rejected parameter in the body
            print(f"Search failed ({response.status_code}): {response.text[:300]}")
            return None

        try:
            items = response.json().get('resultListItems', [])
        except Exception as e:
            print(f"Search error: {e}")
            return None

        return [
            self._parse_list_item(entry['item'])
            for entry in items
            if entry.get('type') == 'EXPOSE_RESULT' and entry.get('item')
        ]

    def _parse_list_item(self, item: Dict) -> Dict:
        """Flatten a search result into the fields the bot needs."""
        attributes = [a.get('value') or '' for a in item.get('attributes', [])]

        def attribute_with(unit: str) -> str:
            # Labels are empty, so the unit is the only way to tell values apart
            return next((value for value in attributes if unit in value), '')

        address = item.get('address') or {}
        paywall = item.get('paywallListing') or {}
        return {
            'id': str(item.get('id')),
            'title': (item.get('title') or '').strip(),
            'url': f"{self.EXPOSE_URL}{item.get('id')}",
            'address': address.get('line', ''),
            'rent': attribute_with('€'),
            'size': attribute_with('m²'),
            'rooms': attribute_with('Zi'),
            'published': item.get('published', ''),
            'is_private': item.get('isPrivate', False),
            # Early access listings can only be contacted with a paid "Suchen+" account
            'paywall_active': bool(paywall.get('active')),
            'raw': item,
        }

    def get_expose(self, expose_id: str) -> Optional[Dict]:
        """Get the full exposé of a listing."""
        try:
            response = self.session.get(
                f'{self.BASE_URL}/expose/{expose_id}',
                headers={'User-Agent': self.EXPOSE_USER_AGENT, 'Accept': 'application/json'},
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"Request error: {e}")
            return None

        if response.status_code not in range(200, 300):
            print(f"Expose failed ({response.status_code}): {response.text[:200]}")
            return None

        try:
            return self._parse_expose(response.json())
        except Exception as e:
            print(f"Expose error: {e}")
            return None

    def _parse_expose(self, data: Dict) -> Dict:
        """Extract description, attributes and contact form requirements."""
        sections = data.get('sections', [])

        def attributes_of(section_type: str) -> Dict[str, str]:
            result = {}
            for section in sections:
                if section.get('type') != section_type:
                    continue
                for attribute in section.get('attributes', []):
                    label = (attribute.get('label') or '').rstrip(': ').strip()
                    if label and attribute.get('text'):
                        result[label] = attribute['text']
            return result

        texts = [
            f"{s.get('title', '')}\n{s.get('text', '')}".strip()
            for s in sections if s.get('type') == 'TEXT_AREA'
        ]

        contact = data.get('contact') or {}
        contact_data = contact.get('contactData') or {}
        agent = contact_data.get('agent') or {}
        return {
            'description': "\n\n".join(texts),
            'top_attributes': attributes_of('TOP_ATTRIBUTES'),
            'attributes': attributes_of('ATTRIBUTE_LIST'),
            'contact_name': agent.get('name', ''),
            'contact_company': agent.get('company', ''),
            'can_message': contact.get('mailButtonState') == 'active',
            'premium_required': str(contact.get('premiumProfileRequiredForContacting')).lower() == 'true',
            # e.g. {'firstnameField': 'MANDATORY', 'incomeAmountField': 'OPTIONAL', ...}
            'form_fields': contact_data.get('formFieldConfig', {}),
            'raw': data,
        }
