"""
Main WG-Gesucht Bot Logic
"""

import json
import time
import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Set

from .wg_api import WgGesuchtClient
from .gemini_helper import GeminiHelper
from .logger import get_logger


class WgGesuchtBot:
    """Main bot for automating WG-Gesucht inquiries"""

    def __init__(self, config: dict):
        self.config = config
        self.client = WgGesuchtClient()
        auth_mode = config.get('wg_gesucht', {}).get('auth_mode', 'mobile')
        try:
            self.client.set_auth_mode(auth_mode)
        except ValueError as e:
            get_logger().warning(f"Invalid auth_mode '{auth_mode}', defaulting to mobile")
        self.gemini: Optional[GeminiHelper] = None
        self.contacted_file = Path(__file__).parent.parent / "contacted.json"
        self.session_file = Path(__file__).parent.parent / "session.json"
        self.message_template = self._load_message_template()
        self.contacted_ids: Set[str] = self._load_contacted()
        self.city_id: Optional[str] = None

        # Initialize Gemini if enabled
        if config.get('gemini', {}).get('enabled') and config.get('gemini', {}).get('api_key'):
            try:
                self.gemini = GeminiHelper(
                    api_key=config['gemini']['api_key'],
                    model=config['gemini'].get('model', 'gemini-1.5-flash')
                )
            except Exception as e:
                get_logger().warning(f"Gemini init failed: {e}, continuing without AI")

    def _load_message_template(self) -> str:
        """Load message template from file"""
        message_file = Path(__file__).parent.parent / "message.txt"
        if message_file.exists():
            return message_file.read_text(encoding='utf-8')
        return "Hallo {name}, ich bin interessiert an eurem Angebot. LG"

    def _load_contacted(self) -> Set[str]:
        """Load previously contacted offer IDs"""
        if self.contacted_file.exists():
            try:
                data = json.loads(self.contacted_file.read_text())
                return set(data.get('contacted_ids', []))
            except Exception:
                pass
        return set()

    def _save_contacted(self) -> None:
        """Save contacted offer IDs"""
        data = {'contacted_ids': list(self.contacted_ids)}
        self.contacted_file.write_text(json.dumps(data, indent=2))

    def _save_session(self) -> None:
        """Save session for reuse"""
        data = self.client.export_account()
        self.session_file.write_text(json.dumps(data, indent=2))

    def _load_session(self) -> bool:
        """Try to load existing session"""
        if self.session_file.exists():
            try:
                data = json.loads(self.session_file.read_text())
                saved_mode = data.get('auth_mode', 'mobile')
                if saved_mode != self.client.auth_mode:
                    return False
                if data.get('access_token'):
                    self.client.import_account(data)
                    if self.client.auth_mode == 'web':
                        response = self.client.get_conversations_web()
                        if response is not None:
                            print("✓ Restored previous session (web)")
                            return True
                    else:
                        # Test if session is still valid
                        profile = self.client.my_profile()
                        if profile:
                            print("✓ Restored previous session")
                            return True
            except Exception:
                pass
        return False

    def login(self) -> bool:
        """Login to WG-Gesucht"""
        # Try existing session first
        if self._load_session():
            return True

        # Fresh login
        email = self.config['wg_gesucht']['email']
        password = self.config['wg_gesucht']['password']
        verification_code = self.config.get('wg_gesucht', {}).get('verification_code')
        prompt_for_code = self.config.get('settings', {}).get('prompt_2fa', True)

        if self.client.login(email, password, verification_code=verification_code, prompt_for_code=prompt_for_code):
            self._save_session()
            return True
        return False

    def _find_city_id(self) -> Optional[str]:
        """Find city ID from config"""
        if self.city_id:
            return self.city_id

        city_name = self.config['search']['city']
        cities = self.client.find_city(city_name)

        if cities and len(cities) > 0:
            self.city_id = str(cities[0].get('city_id'))
            print(f"✓ Found city: {cities[0].get('city_name')} (ID: {self.city_id})")
            return self.city_id
        
        print(f"✗ City not found: {city_name}")
        return None

    def _filter_by_bezirk(self, offers: List[Dict]) -> List[Dict]:
        """Filter offers by Bezirk if specified"""
        bezirk_filter = self.config['search'].get('bezirk', [])
        
        if not bezirk_filter:
            return offers
        def normalize(value: str) -> str:
            cleaned = value.strip().strip('"').strip("'")
            cleaned = re.sub(r'[\s\.\-]', '', cleaned.lower())
            return cleaned

        normalized_filter = [normalize(b) for b in bezirk_filter if isinstance(b, str)]
        normalized_filter = [b for b in normalized_filter if b]

        if not normalized_filter:
            return offers

        filtered = []
        for offer in offers:
            # Check various district field names
            district_raw = " ".join(filter(None, [
                offer.get('district', ''),
                offer.get('area', ''),
                offer.get('city_quarter', ''),
                offer.get('district_custom', ''),
                offer.get('town_name', ''),
            ]))
            if not district_raw:
                continue

            district_norm = normalize(district_raw)
            for bezirk in normalized_filter:
                if bezirk and bezirk in district_norm:
                    filtered.append(offer)
                    break

        printable_filter = [b.strip().strip('"').strip("'") for b in bezirk_filter if isinstance(b, str)]
        print(f"  Filtered to {len(filtered)} offers in: {', '.join(printable_filter)}")
        return filtered

    def _has_real_end_date(self, value: Optional[object]) -> bool:
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value > 0
        text = str(value).strip().lower()
        if not text:
            return False
        if text in ('0', '0.0', '00.00.0000', '00.00.0000, 00:00:00', 'null', 'none'):
            return False
        return True

    def _contains_time_limit_keyword(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        keywords = (
            'zwischenmiete',
            'zwischenmiet',
            'untermiete',
            'sublet',
            'temporary',
            'befristet',
            'befristung',
            'zeitmiete',
        )
        return any(word in lowered for word in keywords)

    def _is_time_limited(self, offer: Dict) -> bool:
        duration = offer.get('duration')
        if duration is not None and str(duration).strip().lower() not in ('', '0', '0.0', 'null', 'none'):
            return True

        available_to = (
            offer.get('available_to_date') or
            offer.get('available_to') or
            offer.get('available_to_date_string')
        )
        if self._has_real_end_date(available_to):
            return True

        title = offer.get('offer_title') or offer.get('title') or ''
        return self._contains_time_limit_keyword(title)

    def _filter_time_limited(self, offers: List[Dict]) -> List[Dict]:
        """Exclude zwischenmiete/time-limited offers when configured."""
        contact_zwischenmiete = self.config['search'].get('contact_zwischenmiete', True)
        if contact_zwischenmiete:
            return offers

        kept = []
        removed = 0
        for offer in offers:
            if self._is_time_limited(offer):
                removed += 1
                continue
            kept.append(offer)

        if removed:
            print(f"  Excluded {removed} time-limited offers")
        return kept

    def _filter_time_limited_silent(self, offers: List[Dict]) -> List[Dict]:
        """Silent time-limit filter (no logging)."""
        contact_zwischenmiete = self.config['search'].get('contact_zwischenmiete', True)
        if contact_zwischenmiete:
            return offers

        kept = []
        for offer in offers:
            if self._is_time_limited(offer):
                continue
            kept.append(offer)
        return kept

    def _filter_by_bezirk_silent(self, offers: List[Dict]) -> List[Dict]:
        """Silent Bezirk filter (no logging)."""
        bezirk_filter = self.config['search'].get('bezirk', [])
        if not bezirk_filter:
            return offers

        def normalize(value: str) -> str:
            cleaned = value.strip().strip('"').strip("'")
            cleaned = re.sub(r'[\s\.\-]', '', cleaned.lower())
            return cleaned

        normalized_filter = [normalize(b) for b in bezirk_filter if isinstance(b, str)]
        normalized_filter = [b for b in normalized_filter if b]
        if not normalized_filter:
            return offers

        filtered = []
        for offer in offers:
            district_raw = " ".join(filter(None, [
                offer.get('district', ''),
                offer.get('area', ''),
                offer.get('city_quarter', ''),
                offer.get('district_custom', ''),
                offer.get('town_name', ''),
            ]))
            if not district_raw:
                continue
            district_norm = normalize(district_raw)
            for bezirk in normalized_filter:
                if bezirk and bezirk in district_norm:
                    filtered.append(offer)
                    break
        return filtered

    def _collect_filtered_offers(self, city_id: str) -> List[Dict]:
        """Fetch multiple pages and apply filters before stopping."""
        search = self.config['search']
        settings = self.config.get('settings', {})

        max_pages = int(search.get('max_pages', 1))
        limit = int(search.get('limit', 20))
        target_filtered = int(search.get('target_filtered_offers', 0))
        if target_filtered <= 0:
            target_filtered = int(settings.get('max_messages_per_run', 5))

        collected = []
        seen_ids: Set[str] = set()
        raw_total = 0
        removed_time = 0
        pages_fetched = 0

        for page in range(1, max_pages + 1):
            page_offers = self.client.get_offers(
                city_id=city_id,
                categories=search.get('categories', '0'),
                max_rent=search.get('max_price', 1000),
                min_size=search.get('min_size', 10),
                page=page,
                limit=limit,
            )

            if not page_offers:
                break

            pages_fetched += 1
            deduped = []
            for offer in page_offers:
                offer_id = str(offer.get('id') or offer.get('offer_id') or '')
                if not offer_id or offer_id in seen_ids:
                    continue
                seen_ids.add(offer_id)
                deduped.append(offer)

            raw_total += len(deduped)

            if not search.get('contact_zwischenmiete', True):
                before = len(deduped)
                deduped = self._filter_time_limited_silent(deduped)
                removed_time += before - len(deduped)

            deduped = self._filter_by_bezirk_silent(deduped)
            collected.extend(deduped)

            if len(collected) >= target_filtered:
                break

        if pages_fetched > 0:
            print(f"Found {raw_total} offers across {pages_fetched} page(s)")
        if not search.get('contact_zwischenmiete', True):
            print(f"  Excluded {removed_time} time-limited offers")

        bezirk_filter = search.get('bezirk', [])
        if bezirk_filter:
            printable_filter = [b.strip().strip('"').strip("'") for b in bezirk_filter if isinstance(b, str)]
            print(f"  Filtered to {len(collected)} offers in: {', '.join(printable_filter)}")

        return collected

    def _get_recipient_name(self, offer: Dict, detail: Optional[Dict] = None) -> str:
        """Extract recipient name from offer"""
        # Try various field names
        name = (
            offer.get('user_name') or
            offer.get('contact_name') or
            (detail.get('user', {}).get('first_name') if detail else None) or
            'du'
        )
        return name.split()[0] if name else 'du'  # Use first name only

    def _prepare_message(self, offer: Dict, detail: Optional[Dict] = None) -> str:
        """Prepare message for an offer"""
        recipient_name = self._get_recipient_name(offer, detail)
        
        # Try Gemini personalization
        if self.gemini and detail:
            listing_info = {
                'title': offer.get('title', ''),
                'description': detail.get('description', '') or detail.get('freetext_property_description', ''),
                'district': offer.get('district', ''),
                'rent': offer.get('rent', '')
            }
            
            personalized = self.gemini.personalize_message(
                self.message_template,
                listing_info,
                recipient_name
            )
            
            if personalized:
                print(f"  ✓ Used Gemini personalization")
                return personalized

        # Fallback to template
        return self.message_template.replace('{name}', recipient_name)

    def run(self) -> int:
        """
        Run one iteration of the bot
        
        Returns:
            Number of messages sent
        """
        logger = get_logger()
        logger.start_run()
        
        settings = self.config.get('settings', {})
        dry_run = settings.get('dry_run', True)
        max_messages = settings.get('max_messages_per_run', 5)
        delay = settings.get('delay_between_messages', 10)
        
        logger.set_stats(dry_run=dry_run)
        
        if dry_run:
            logger.info("🔸 Running in DRY RUN mode (no messages will be sent)")

        # Login
        if not self.login():
            logger.log_error("Login failed!")
            logger.end_run(success=False)
            return 0

        # Get city ID
        city_id = self._find_city_id()
        if not city_id:
            logger.log_error("City not found")
            logger.end_run(success=False)
            return 0

        # Get offers (paginate to find enough filtered results)
        offers = self._collect_filtered_offers(city_id)
        logger.set_stats(offers_found=len(offers) if offers else 0)
        
        if not offers:
            logger.info("No offers matched filters")
            logger.end_run(success=True)
            return 0

        # Filter out already contacted
        new_offers = [
            o for o in offers 
            if str(o.get('id') or o.get('offer_id')) not in self.contacted_ids
        ]
        logger.set_stats(offers_filtered=len(offers), offers_new=len(new_offers))
        logger.info(f"New offers to contact: {len(new_offers)}")

        if not new_offers:
            logger.info("✓ All offers already contacted")
            logger.end_run(success=True)
            return 0

        # Send messages
        messages_sent = 0
        mark_in_dry_run = settings.get('mark_contacted_in_dry_run', False)
        for offer in new_offers[:max_messages]:
            offer_id = str(offer.get('id') or offer.get('offer_id'))
            title = (offer.get('title') or offer.get('offer_title') or 'Unknown')[:50]
            
            logger.info(f"\n→ Processing: {title} (ID: {offer_id})")

            # Get details for AI personalization
            detail = None
            if self.gemini:
                detail = self.client.get_offer_detail(offer_id)

            # Prepare message
            message = self._prepare_message(offer, detail)

            if dry_run:
                logger.info(f"  [DRY RUN] Would send message:")
                logger.info(f"  {message[:100]}...")
                logger.log_contacted(offer_id, title, success=True)
            else:
                result = self.client.contact_offer(offer_id, message)
                if result:
                    logger.info(f"  ✓ Message sent!")
                    messages_sent += 1
                    self.contacted_ids.add(offer_id)
                    self._save_contacted()
                    logger.log_contacted(offer_id, title, success=True)
                else:
                    logger.info(f"  ✗ Failed to send message")
                    logger.log_contacted(offer_id, title, success=False)

            if dry_run and mark_in_dry_run:
                self.contacted_ids.add(offer_id)
                self._save_contacted()

            # Delay between messages
            if messages_sent < max_messages - 1:
                time.sleep(delay)

        logger.end_run(success=True)
        return messages_sent
