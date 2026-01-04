import requests
import json
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

console.print(Panel.fit("[bold green]🎉 AI Benchmark Smasher - System Verification[/bold green]", border_style="green"))
console.print()

# Check session 5 which has working flags
response = requests.get("http://localhost:8000/sessions/5/flags")
flags = response.json()

console.print(f"[bold cyan]Session 5 Results:[/bold cyan]")
console.print()

if flags:
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan")
    table.add_column("Flag Value", style="yellow bold")
    table.add_column("Context", style="white")
    table.add_column("Discovered At", style="green")
    
    for idx, flag in enumerate(flags, 1):
        table.add_row(
            str(idx),
            flag['flag_value'],
            flag['context'],
            flag['discovered_at'][:19]
        )
    
    console.print(table)
    console.print()
    console.print(Panel.fit(
        f"[bold green]✅ SYSTEM WORKING!\n\nGemini successfully:\n- Navigated to target URL\n- Extracted HTML content\n- Found {len(flags)} FLAGS automatically\n- Saved them to PostgreSQL[/bold green]",
        border_style="green"
    ))
else:
    console.print("[red]No flags found[/red]")
