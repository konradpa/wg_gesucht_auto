#!/usr/bin/env python3
"""
Interactive setup wizard for WG-Gesucht Bot.
Generates config.yaml and message.txt from user input.
No extra dependencies — uses only Python stdlib.
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ── Helpers ──────────────────────────────────────────────────────────────────

def ask(prompt: str, default: str = "") -> str:
    """Ask the user for input with an optional default."""
    if default:
        value = input(f"  {prompt} [{default}]: ").strip()
        return value if value else default
    else:
        while True:
            value = input(f"  {prompt}: ").strip()
            if value:
                return value
            print("    ⚠ This field is required.")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    """Ask a yes/no question."""
    hint = "Y/n" if default else "y/N"
    value = input(f"  {prompt} [{hint}]: ").strip().lower()
    if not value:
        return default
    return value in ("y", "yes", "ja", "j")


def ask_int(prompt: str, default: int) -> int:
    """Ask for an integer, re-prompting on invalid input."""
    while True:
        value = ask(prompt, str(default))
        try:
            return int(value)
        except ValueError:
            print("    ⚠ Please enter a whole number.")


def ask_list(prompt: str, example: str = "") -> list:
    """Ask for a comma-separated list."""
    hint = f" (e.g. {example})" if example else ""
    value = input(f"  {prompt}{hint} [leave empty to skip]: ").strip()
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def ask_choice(prompt: str, choices: list, default: str) -> str:
    """Ask for one of the allowed choices."""
    allowed = {choice.lower() for choice in choices}
    while True:
        value = ask(prompt, default).lower()
        if value in allowed:
            return value
        print(f"    ⚠ Please choose one of: {', '.join(choices)}")


def yaml_quote(value: str) -> str:
    """Return a YAML-safe double-quoted scalar using JSON string escaping."""
    return json.dumps(str(value), ensure_ascii=False)


def section(title: str):
    """Print a section header."""
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print()
    print("🏠 WG-Gesucht Bot — Setup Wizard")
    print("=" * 50)
    print("This will create your config.yaml and message.txt.")
    print("Press Ctrl+C at any time to cancel.\n")

    # Check if files already exist
    config_path = BASE_DIR / "config.yaml"
    message_path = BASE_DIR / "message.txt"

    if config_path.exists():
        if not ask_yes_no("config.yaml already exists. Overwrite?"):
            print("  Skipping config.yaml.")
            config_path = None

    if message_path.exists():
        if not ask_yes_no("message.txt already exists. Overwrite?"):
            print("  Skipping message.txt.")
            message_path = None

    if config_path is None and message_path is None:
        print("\n✓ Nothing to do. Both files already exist.")
        return

    # ── Search Settings ──────────────────────────────────────────────────

    city = "Hamburg"
    max_price = 650
    categories = "0"
    bezirk = []
    contact_zwischenmiete = False

    if config_path:
        section("Search Settings")
        city = ask("City", "Hamburg")
        max_price = ask_int("Max monthly rent (€)", 650)

        print("\n  Room type options:")
        print("    0 = WG-Zimmer (shared flat room)")
        print("    1 = 1-Zimmer-Wohnung (studio)")
        print("    2 = Wohnung (apartment)")
        print("    3 = Haus (house)")
        categories = ask("Room type number", "0")

        bezirk = ask_list(
            "Districts to include",
            "Altona-Altstadt, Eimsbuettel, Neustadt"
        )

        contact_zwischenmiete = ask_yes_no(
            "Include time-limited offers (Zwischenmiete)?", False
        )

    # ── AI Personalization (Optional) ────────────────────────────────────

    llm_enabled = False
    llm_provider = "gemini"
    llm_model = "gemini-1.5-flash"
    llm_base_url = ""

    if config_path:
        section("AI Personalization (Optional)")
        print("  Optional: personalize messages with an LLM.")
        print("  Supported provider values: gemini, anthropic, openai, openrouter, groq, together, openai_compatible")
        llm_enabled = ask_yes_no("Enable AI personalization?", False)
        if llm_enabled:
            print("\n  Provider tips:")
            print("    gemini = Google AI Studio (Gemini API key)")
            print("    anthropic = Claude API")
            print("    openai = OpenAI API")
            print("    openrouter/groq/together = preconfigured OpenAI-compatible APIs")
            print("    openai_compatible = any custom endpoint (LM Studio, vLLM, Ollama gateway, etc.)")

            llm_provider = ask_choice(
                "Provider",
                ["gemini", "anthropic", "openai", "openrouter", "groq", "together", "openai_compatible"],
                "gemini",
            )

            default_model_by_provider = {
                "gemini": "gemini-1.5-flash",
                "anthropic": "claude-3-5-haiku-latest",
                "openai": "gpt-4o-mini",
                "openrouter": "openai/gpt-4o-mini",
                "groq": "llama-3.1-8b-instant",
                "together": "meta-llama/Llama-3.1-8B-Instruct-Turbo",
                "openai_compatible": "gpt-4o-mini",
            }
            default_base_url_by_provider = {
                "openrouter": "https://openrouter.ai/api/v1",
                "groq": "https://api.groq.com/openai/v1",
                "together": "https://api.together.xyz/v1",
            }

            print("  Set LLM_API_KEY in your environment before starting the bot.")
            llm_model = ask("Model name", default_model_by_provider[llm_provider])

            if llm_provider == "openai_compatible":
                llm_base_url = ask("Base URL (OpenAI-compatible endpoint)", "http://localhost:1234/v1")
            elif llm_provider in default_base_url_by_provider:
                llm_base_url = ask("Base URL", default_base_url_by_provider[llm_provider])

    # ── Bot Settings ─────────────────────────────────────────────────────

    interval = 20
    max_messages = 2

    if config_path:
        section("Bot Settings")
        interval = ask_int("Check interval (minutes)", 20)
        max_messages = ask_int("Max messages per run", 2)

    # ── Contact Info (Optional) ──────────────────────────────────────────

    contact_email = ""
    contact_phone = ""

    if config_path:
        section("Contact Info (Optional)")
        print("  If a listing asks for your email/phone, the bot can include it.")
        contact_email = input("  Contact email [leave empty to skip]: ").strip()
        contact_phone = input("  Contact phone [leave empty to skip]: ").strip()

    # ── Generate config.yaml ─────────────────────────────────────────────

    if config_path:
        bezirk_yaml = ""
        if bezirk:
            bezirk_lines = "\n".join(f"    - {yaml_quote(b)}" for b in bezirk)
            bezirk_yaml = f"\n{bezirk_lines}"
        else:
            bezirk_yaml = " []"

        config_content = f"""wg_gesucht:
  # Set WG_GESUCHT_EMAIL and WG_GESUCHT_PASSWORD before starting the bot.
  email: "${{WG_GESUCHT_EMAIL}}"
  password: "${{WG_GESUCHT_PASSWORD}}"

search:
  city: {yaml_quote(city)}
  bezirk:{bezirk_yaml}
  max_price: {max_price}
  min_size: 0
  categories: {yaml_quote(categories)}
  limit: 20
  max_pages: 5
  target_filtered_offers: 0
  contact_zwischenmiete: {"true" if contact_zwischenmiete else "false"}

llm:
  enabled: {"true" if llm_enabled else "false"}
  provider: {yaml_quote(llm_provider)}
  api_key: "${{LLM_API_KEY:-}}"  # Set LLM_API_KEY when personalization is enabled
  model: {yaml_quote(llm_model)}
  base_url: {yaml_quote(llm_base_url)}

settings:
  interval_minutes: {interval}
  max_messages_per_run: {max_messages}
  delay_between_messages: 20
  dry_run: true
  mark_contacted_in_dry_run: false
  contact_email: {yaml_quote(contact_email)}
  contact_phone: {yaml_quote(contact_phone)}
"""
        config_path.write_text(config_content, encoding="utf-8")
        print(f"\n✓ Created config.yaml")

    # ── Generate message.txt ─────────────────────────────────────────────

    if message_path:
        section("Message Template")
        print("  Write the message you want to send to listings.")
        print("  Use {name} where you want the recipient's name inserted.")
        print("  Press Enter twice (empty line) when done.\n")

        lines = []
        print("  ── Start typing your message ──")
        while True:
            try:
                line = input()
            except EOFError:
                print("  EOF received while reading message template.")
                break
            if line == "" and lines and lines[-1] == "":
                lines.pop()  # Remove trailing empty line
                break
            lines.append(line)

        if lines:
            message_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"\n✓ Created message.txt")
        else:
            # Use example template
            example = BASE_DIR / "message.example.txt"
            if example.exists():
                message_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"\n✓ Created message.txt (from example template)")
            else:
                print("  ⚠ No message entered and no example template found.")

    # ── Done ─────────────────────────────────────────────────────────────

    print()
    print("=" * 50)
    print("✓ Setup complete!")
    print("=" * 50)
    print()
    print("Next steps:")
    print("  1. Test your login:")
    print("     python run.py --test-login")
    print()
    print("  2. (Optional) Test your AI provider:")
    print("     python run.py --test-llm")
    print()
    print("  3. Do a dry run (no messages sent):")
    print("     python run.py --once --dry-run")
    print()
    print("  4. When ready, send messages:")
    print("     python run.py --once --send")
    print()
    print("  5. Run on a schedule (checks every {} minutes):".format(interval))
    print("     python run.py")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Setup cancelled.")
        sys.exit(0)
