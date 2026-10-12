import argparse
import uuid
from getpass import getpass

from langgraph.types import Command
from rich.console import Console

from agents.graph import build_graph
from agents.state import INITIAL_STATE
from config.settings import APP_NAME, APP_VERSION, DEFAULT_PROVIDER
from services.credential_manager import CredentialManager
from services.llm_client import initialize_client
from ui.console import print_welcome

console = Console()

PROVIDER_KEY_NAME = {
    "gemini":     "GEMINI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
PROVIDER_LABEL = {
    "gemini":     "Gemini (Google)",
    "anthropic":  "Anthropic (Claude)",
    "openrouter": "OpenRouter",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="travel-agent",
        description=f"{APP_NAME} v{APP_VERSION} — AI-powered CLI travel planner",
    )
    parser.add_argument(
        "--provider",
        choices=["gemini", "anthropic", "openrouter"],
        default=DEFAULT_PROVIDER,
        help="LLM provider to use (default: gemini — free tier available)",
    )
    return parser.parse_args()


def bootstrap_credentials(provider: str) -> CredentialManager:
    """Unlock or set up the credential store for the given provider."""
    cm = CredentialManager(provider=provider)
    label = PROVIDER_LABEL[provider]

    if not cm.is_configured():
        console.print(
            f"\n[bold yellow]First run ({label}) — setting up encrypted credential storage.[/bold yellow]"
        )
        console.print("[dim]Your API keys will be encrypted with your master password.[/dim]\n")
        while True:
            password = getpass("  Set master password: ")
            confirm = getpass("  Confirm password   : ")
            if password != confirm:
                console.print("[red]  Passwords do not match. Try again.[/red]\n")
                continue
            if len(password) < 6:
                console.print("[red]  Password must be at least 6 characters.[/red]\n")
                continue
            break
        console.print(f"\n[dim]Enter your API keys for {label}:[/dim]")
        cm.setup(master_password=password)
        console.print("[green]  Credentials saved and encrypted.[/green]\n")
    else:
        password = getpass("  Master password: ")
        try:
            cm.unlock(master_password=password)
        except ValueError as e:
            console.print(f"[red]  {e}[/red]")
            raise SystemExit(1)

    return cm


def run() -> None:
    args = parse_args()
    provider = args.provider

    print_welcome()
    console.print(f"[dim]Provider: {PROVIDER_LABEL[provider]}[/dim]\n")

    cm = bootstrap_credentials(provider)

    # Initialize the LLM singleton before the graph runs
    api_key = cm.get_credential(PROVIDER_KEY_NAME[provider])
    initialize_client(provider, api_key)

    graph = build_graph(use_sqlite=True)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    console.print(f"[dim]Session: {thread_id}[/dim]\n")
    console.print("[bold green]Let's start planning your trip![/bold green]\n")

    # Seed initial state with provider so nodes can access it if needed
    state = dict(INITIAL_STATE)
    state["provider"] = provider

    result = graph.invoke(state, config)

    while True:
        interrupts = result.get("__interrupt__")
        if not interrupts:
            break

        interrupt_val = interrupts[0].value
        if isinstance(interrupt_val, dict):
            msg = interrupt_val.get("message")
            if msg:
                console.print(msg)
            raw_prompt = interrupt_val.get("prompt", "You: ")
        else:
            raw_prompt = str(interrupt_val)
        input_prompt = raw_prompt if raw_prompt.endswith((" ", ": ")) else raw_prompt + " "

        try:
            user_input = console.input(f"[bold yellow]{input_prompt}[/bold yellow]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session ended.[/dim]")
            break

        result = graph.invoke(Command(resume=user_input), config)

    console.print("\n[bold cyan]Safe travels! ✈[/bold cyan]")


if __name__ == "__main__":
    run()
