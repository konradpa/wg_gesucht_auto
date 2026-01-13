"""
Gemini AI Helper for personalizing WG-Gesucht messages
Uses the new google-genai package
"""

from google import genai
from google.genai import types
from typing import Optional


class GeminiHelper:
    """Helper class for Gemini AI message personalization"""

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        """Initialize Gemini with API key"""
        self.client = genai.Client(api_key=api_key)
        self.model = model
        print(f"✓ Gemini initialized with model: {model}")

    def personalize_message(self, base_message: str, listing_details: dict, 
                           recipient_name: str) -> Optional[str]:
        """
        Personalize a message based on listing details
        
        Args:
            base_message: The template message
            listing_details: Dict with listing info (title, description, etc.)
            recipient_name: Name of the person to address
            
        Returns:
            Personalized message or None on error
        """
        
        # Extract relevant listing info
        title = listing_details.get('title', '')
        description = listing_details.get('description', '')
        district = listing_details.get('district', '')
        rent = listing_details.get('rent', '')
        
        prompt = f"""Du bist ein freundlicher WG-Bewerber. Personalisiere die folgende Nachricht basierend auf der WG-Anzeige.

WICHTIGE REGELN:
1. Behalte den Grundton und die Struktur der Originalnachricht bei
2. Füge 1-2 spezifische Bezüge zur Anzeige hinzu (z.B. Lage, etwas Besonderes aus der Beschreibung)
3. Bleib authentisch und nicht zu übertrieben freundlich
4. Die Nachricht sollte etwa gleich lang bleiben
5. Schreibe auf Deutsch
6. Ersetze {{name}} mit dem echten Namen

ORIGINALNACHRICHT:
{base_message}

WG-ANZEIGE:
Titel: {title}
Bezirk: {district}
Miete: {rent}€
Beschreibung: {description[:500]}

EMPFÄNGER: {recipient_name}

Gib NUR die personalisierte Nachricht zurück, keine Erklärungen."""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            personalized = response.text.strip()
            
            # Basic validation
            if len(personalized) < 50:
                print("⚠ Gemini response too short, using template")
                return None
                
            return personalized
            
        except Exception as e:
            print(f"⚠ Gemini error: {e}")
            return None


def test_gemini(api_key: str) -> bool:
    """Test if Gemini API key works"""
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents="Sag einfach 'OK'"
        )
        return len(response.text) > 0
    except Exception as e:
        print(f"Gemini test failed: {e}")
        return False
