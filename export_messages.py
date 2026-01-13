#!/usr/bin/env python3
"""
Export your WG-Gesucht message history
"""

import sys
import yaml
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.wg_api import WgGesuchtClient


def load_config():
    with open('config.yaml', 'r') as f:
        return yaml.safe_load(f)


def export_conversations():
    config = load_config()
    client = WgGesuchtClient()
    auth_mode = config.get('wg_gesucht', {}).get('auth_mode', 'mobile')
    client.set_auth_mode(auth_mode)
    
    # Login
    email = config['wg_gesucht']['email']
    password = config['wg_gesucht']['password']
    verification_code = config.get('wg_gesucht', {}).get('verification_code')
    prompt_for_code = config.get('settings', {}).get('prompt_2fa', True)
    
    print(f"Logging in as {email}...")
    if not client.login(email, password, verification_code=verification_code, prompt_for_code=prompt_for_code):
        print("Login failed!")
        return
    
    # Get conversations
    print("\nFetching conversations...")
    conversations = client.get_conversations()
    
    if not conversations:
        print("No conversations found or API error")
        return
    
    print(f"Found {len(conversations)} conversations\n")
    
    # Save to file
    output_file = 'messages_export.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(conversations, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Exported to {output_file}")
    
    # Print summary
    print("\n" + "="*60)
    print("CONVERSATION SUMMARY")
    print("="*60)
    
    for i, conv in enumerate(conversations[:10], 1):  # Show first 10
        ad_title = conv.get('ad_title', 'Unknown')
        last_message = conv.get('last_message', {})
        message_preview = last_message.get('content', '')[:50]
        
        print(f"\n{i}. {ad_title}")
        print(f"   Last: {message_preview}...")
        print(f"   ID: {conv.get('conversation_id')}")


if __name__ == "__main__":
    export_conversations()
