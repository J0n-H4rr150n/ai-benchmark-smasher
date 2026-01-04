import requests
import json
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich import box

console = Console()

BASE_URL = "http://localhost:8000"


def print_header(title: str):
    """Print a fancy header"""
    console.print(Panel.fit(
        f"[bold cyan]{title}[/bold cyan]",
        border_style="bright_blue"
    ))
    console.print()


def test_health():
    """Test health endpoint"""
    console.print("[bold yellow]→ Testing Health Endpoint[/bold yellow]")
    response = requests.get(f"{BASE_URL}/health")
    
    if response.status_code == 200:
        data = response.json()
        table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
        table.add_column("Check", style="cyan")
        table.add_column("Status", style="green")
        
        table.add_row("API", data['status'])
        table.add_row("Database", data['database'])
        table.add_row("Vertex AI", data['vertex_ai'])
        
        console.print(table)
    else:
        console.print(f"[red]✗ Health check failed: {response.status_code}[/red]")
    
    console.print()


def create_session(target_url: str, goal: str):
    """Create a CTF session"""
    console.print("[bold yellow]→ Creating CTF Session[/bold yellow]")
    
    payload = {
        "target_url": target_url,
        "goal": goal
    }
    
    console.print(Panel(
        f"[cyan]Target URL:[/cyan] {target_url}\n[cyan]Goal:[/cyan] {goal}",
        title="[bold]Session Configuration[/bold]",
        border_style="blue"
    ))
    
    response = requests.post(f"{BASE_URL}/sessions", json=payload)
    
    if response.status_code == 200:
        data = response.json()
        session_id = data['id']
        console.print(f"[green]✓ Session created with ID: {session_id}[/green]")
        console.print()
        return session_id
    else:
        console.print(f"[red]✗ Failed to create session: {response.text}[/red]")
        return None


def chat_with_gemini(session_id: int, message: str):
    """Send message to Gemini and show full interaction"""
    console.print("[bold yellow]→ Sending Prompt to Gemini[/bold yellow]")
    
    # Show user message
    console.print(Panel(
        Markdown(message),
        title="[bold green]User Message[/bold green]",
        border_style="green"
    ))
    
    payload = {
        "session_id": session_id,
        "message": message
    }
    
    console.print("\n[dim]Waiting for Gemini response...[/dim]\n")
    
    response = requests.post(f"{BASE_URL}/chat", json=payload)
    
    if response.status_code != 200:
        console.print(f"[red]✗ Chat failed: {response.text}[/red]")
        return
    
    data = response.json()
    
    # Show tool calls if any
    if data.get('tool_calls'):
        console.print("[bold yellow]→ Gemini's Tool Execution[/bold yellow]")
        
        tool_table = Table(
            show_header=True,
            header_style="bold magenta",
            box=box.ROUNDED,
            title="[bold]Function Calls[/bold]",
            title_style="bold yellow"
        )
        tool_table.add_column("#", style="cyan", width=3)
        tool_table.add_column("Tool", style="yellow")
        tool_table.add_column("Arguments", style="white")
        
        for idx, tool_call in enumerate(data['tool_calls'], 1):
            args_json = json.dumps(tool_call['args'], indent=2)
            tool_table.add_row(
                str(idx),
                tool_call['tool'],
                args_json
            )
        
        console.print(tool_table)
        console.print()
    
    # Show Gemini's response
    if data.get('content'):
        console.print(Panel(
            Markdown(data['content']) if data['content'] else "[dim italic]No text response (tool calls only)[/dim italic]",
            title="[bold blue]Gemini's Response[/bold blue]",
            border_style="blue"
        ))
    
    console.print()
    
    return data


def check_flags(session_id: int):
    """Check discovered flags"""
    console.print("[bold yellow]→ Checking Discovered Flags[/bold yellow]")
    
    response = requests.get(f"{BASE_URL}/sessions/{session_id}/flags")
    
    if response.status_code == 200:
        flags = response.json()
        
        if flags:
            console.print(f"\n[bold green]🎉 Found {len(flags)} FLAG(s)![/bold green]\n")
            
            flag_table = Table(
                show_header=True,
                header_style="bold green",
                box=box.DOUBLE_EDGE,
                title="[bold]Captured Flags[/bold]",
                title_style="bold green"
            )
            flag_table.add_column("#", style="cyan", width=3)
            flag_table.add_column("Flag Value", style="yellow bold")
            flag_table.add_column("Context", style="white")
            flag_table.add_column("Discovered At", style="dim")
            
            for idx, flag in enumerate(flags, 1):
                flag_table.add_row(
                    str(idx),
                    flag['flag_value'],
                    flag.get('context', 'N/A'),
                    flag['discovered_at'][:19]  # Trim timestamp
                )
            
            console.print(flag_table)
        else:
            console.print("[yellow]No flags found yet.[/yellow]")
    else:
        console.print(f"[red]✗ Failed to get flags: {response.text}[/red]")
    
    console.print()


def check_conversation_history(session_id: int):
    """Show conversation history"""
    console.print("[bold yellow]→ Conversation History[/bold yellow]")
    
    response = requests.get(f"{BASE_URL}/chat/history", params={"session_id": session_id, "limit": 10})
    
    if response.status_code == 200:
        conversations = response.json()
        
        for conv in conversations:
            role_style = "green" if conv['role'] == "user" else "blue"
            role_label = "User" if conv['role'] == "user" else "Gemini"
            
            console.print(Panel(
                conv['content'][:300] + ("..." if len(conv['content']) > 300 else ""),
                title=f"[bold {role_style}]{role_label}[/bold {role_style}]",
                border_style=role_style,
                padding=(0, 1)
            ))
    
    console.print()


def main():
    """Main test flow"""
    print_header("🎯 AI Benchmark Smasher - Interactive Test")
    
    # Health check
    test_health()
    
    # Create session
    session_id = create_session(
        target_url="http://host.docker.internal:8080/test_page.html",
        goal="Find all hidden FLAG{} values in the page"
    )
    
    if not session_id:
        return
    
    # Send initial prompt
    chat_with_gemini(
        session_id,
        "Please analyze the target URL. Use the browser tool to navigate to it and extract all content. Look for any FLAG{} patterns in the HTML, comments, JavaScript, or hidden fields."
    )
    
    # Check flags
    check_flags(session_id)
    
    # Show conversation
    # check_conversation_history(session_id)
    
    # Summary
    console.print(Panel.fit(
        "[bold green]✓ Test Complete![/bold green]",
        border_style="green"
    ))


if __name__ == "__main__":
    main()
