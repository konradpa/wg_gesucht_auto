"""
WG-Gesucht Browser Bot using Playwright
Since the API is restricted, we use browser automation
"""

import time
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser
from typing import Optional, List, Dict


class WgGesuchtBrowser:
    """Browser-based WG-Gesucht automation"""
    
    BASE_URL = "https://www.wg-gesucht.de"
    
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.logged_in = False
        
    def start(self):
        """Start browser"""
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.page = self.browser.new_page()
        self.page.set_viewport_size({"width": 1280, "height": 800})
        
    def stop(self):
        """Close browser"""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
    
    def login(self, email: str, password: str) -> bool:
        """Login to WG-Gesucht"""
        try:
            # Go directly to login page
            print("Opening login page...")
            self.page.goto(f"{self.BASE_URL}/mein-wg-gesucht-login.html")
            time.sleep(3)
            
            # Accept cookies if popup appears - try multiple selectors
            print("Handling cookie consent...")
            for selector in [
                "button:has-text('Akzeptieren')",
                "button:has-text('Accept')",
                "#cmpbntyestxt",
                ".cmpboxbtnyes",
                "button[title*='Accept']"
            ]:
                try:
                    self.page.click(selector, timeout=2000)
                    print("  → Accepted cookies")
                    time.sleep(1)
                    break
                except:
                    continue
            
            # Fill login form - use visible selector
            print("Filling login form...")
            self.page.wait_for_selector("input#login_email_username:visible", timeout=10000)
            
            self.page.fill("input#login_email_username", email)
            time.sleep(0.5)
            self.page.fill("input#login_password", password)
            time.sleep(0.5)
            
            # Click submit
            print("Submitting...")
            self.page.click("input#login_submit")
            time.sleep(4)
            
            # Check if logged in
            current_url = self.page.url.lower()
            if "mein-wg-gesucht" in current_url or "nachricht" in current_url or "inbox" in current_url:
                print("✓ Logged in successfully!")
                self.logged_in = True
                return True
            
            # Check for 2FA/email verification
            page_content = self.page.content().lower()
            if "code" in page_content or "verifizier" in page_content or "bestätig" in page_content:
                print("⚠ 2FA code required - check your email")
                print("Enter the code in the browser window...")
                print("Waiting 60 seconds...")
                time.sleep(60)
                
                if "mein-wg-gesucht" in self.page.url.lower():
                    print("✓ Logged in after 2FA!")
                    self.logged_in = True
                    return True
            
            print(f"✗ Login may have failed. Current URL: {self.page.url}")
            return False
            
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    def navigate_to_search(self, url: str):
        """Navigate to a search results page"""
        print(f"Navigating to search...")
        self.page.goto(url)
        time.sleep(2)
        
    def get_listings(self) -> List[Dict]:
        """Get listings from current search page"""
        listings = []
        
        try:
            # Get all listing cards
            cards = self.page.query_selector_all(".wgg_card.offer_list_item")
            
            for card in cards:
                try:
                    listing = {}
                    
                    # Get offer ID
                    offer_id = card.get_attribute("data-id")
                    if not offer_id:
                        continue
                    listing["id"] = offer_id
                    
                    # Get title
                    title_el = card.query_selector(".card_body .truncate_title a")
                    listing["title"] = title_el.inner_text() if title_el else "Unknown"
                    
                    # Get link
                    link = title_el.get_attribute("href") if title_el else None
                    listing["url"] = f"{self.BASE_URL}{link}" if link else None
                    
                    # Get price
                    price_el = card.query_selector(".col-xs-3 b")
                    listing["price"] = price_el.inner_text() if price_el else ""
                    
                    listings.append(listing)
                    
                except Exception as e:
                    continue
                    
            print(f"Found {len(listings)} listings")
            
        except Exception as e:
            print(f"Error getting listings: {e}")
            
        return listings
    
    def send_message(self, listing_url: str, message: str, recipient_name: str = "du") -> bool:
        """Send message to a listing"""
        try:
            print(f"Opening listing: {listing_url[:50]}...")
            self.page.goto(listing_url)
            time.sleep(2)
            
            # Replace {name} in message
            message = message.replace("{name}", recipient_name)
            
            # Find and fill message textarea
            textarea = self.page.query_selector("textarea[name='nachricht_freitext']")
            if not textarea:
                textarea = self.page.query_selector("#nachricht_freitext")
            if not textarea:
                textarea = self.page.query_selector("textarea")
            
            if textarea:
                textarea.fill(message)
                time.sleep(1)
                
                # Click send button
                send_btn = self.page.query_selector("button:has-text('Nachricht senden')")
                if not send_btn:
                    send_btn = self.page.query_selector("input[type='submit'][value*='senden']")
                if not send_btn:
                    send_btn = self.page.query_selector("button[type='submit']")
                
                if send_btn:
                    send_btn.click()
                    time.sleep(2)
                    print("✓ Message sent!")
                    return True
                else:
                    print("✗ Could not find send button")
                    return False
            else:
                print("✗ Could not find message textarea")
                return False
                
        except Exception as e:
            print(f"Send error: {e}")
            return False


def test_browser_login():
    """Test browser-based login"""
    import yaml
    
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    
    bot = WgGesuchtBrowser(headless=False)  # Show browser for debugging
    
    try:
        bot.start()
        
        success = bot.login(
            cfg['wg_gesucht']['email'],
            cfg['wg_gesucht']['password']
        )
        
        if success:
            print("\n✓ Browser login works!")
            print("Keeping browser open for 10 seconds...")
            time.sleep(10)
        else:
            print("\n✗ Browser login failed")
            time.sleep(5)
            
    finally:
        bot.stop()


if __name__ == "__main__":
    test_browser_login()
