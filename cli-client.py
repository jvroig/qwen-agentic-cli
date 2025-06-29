#!/usr/bin/env python3
import json
import requests
import sys
import os
import signal
import threading
import argparse
import select
from datetime import datetime
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.panel import Panel
from rich.prompt import Prompt
from rich.padding import Padding
from rich.live import Live
from rich.text import Text
from rich.status import Status
from rich import box

# Global variables
stop_streaming = False
console = Console()
conversation_history = []
max_result_len = 300 #Limits formatted display length only, not actual content stored in context
multiline_mode = False  # Track persistent multi-line mode

#FIXME: DELETE ME
# def signal_handler(sig, frame):
#     """Handle Ctrl+Q to stop streaming responses"""
#     global stop_streaming
#     if sig == signal.SIGQUIT:  # SIGQUIT is Ctrl+\, but we'll map to Ctrl+Q in terminal
#         stop_streaming = True
#         console.print("\n[bold red]Stopping response...[/bold red]")

def format_code_blocks(text):
    """Format code blocks within markdown text"""
    if "```" not in text:
        return text
    
    parts = []
    in_code_block = False
    code_content = ""
    code_language = ""
    
    for line in text.split("\n"):
        if line.startswith("```"):
            if in_code_block:
                # End of code block
                if code_content:
                    syntax = Syntax(code_content.strip(), code_language or "text", theme="monokai", line_numbers=True)
                    parts.append(syntax)
                in_code_block = False
                code_content = ""
                code_language = ""
            else:
                # Start of code block
                in_code_block = True
                code_language = line[3:].strip()
        elif in_code_block:
            code_content += line + "\n"
        else:
            parts.append(line)
    
    return parts

def format_tool_result(result):
    """Format tool call results using markdown"""

    try:
        # Clean up the result
        if result.startswith("Tool result: "):
            result = result[len("Tool result: "):]
        
        if len(result) >= 200:
            result = result[:180] + "... ```"

        # If it looks like structured data, format it nicely
        if "```" in result:
            # It already has markdown code blocks, just return as markdown
            return Markdown(result)
        
        # For plain text results, add some light markdown formatting
        # You could add logic here to detect different types of content
        if result.strip().startswith('{') and result.strip().endswith('}'):
            # Looks like JSON, wrap in a code block
            try:
                parsed = json.loads(result)
                formatted = json.dumps(parsed, indent=2)
                return Markdown(f"```json\n{formatted}\n```")
            except json.JSONDecodeError:
                pass

        # For regular messages, just return as markdown (handles basic formatting)
        return Markdown(result)
        
    except Exception as e:
        return Markdown(f"**Error formatting tool result:** {str(e)}\n\n```\n{result}\n```")
    

def process_streaming_response(url, messages, temperature=0.4, max_tokens=8000):
    """Process streaming response from the API"""
    global stop_streaming
    stop_streaming = False
    
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_output_tokens": max_tokens
    }
    
    try:
        assistant_message = ""
#        full_response = []
        current_role = ""
        current_live = None
        
        # Show a message while waiting for the first response
        # console.print(Padding("[dim]Waiting for response...[/dim]",(0, 0, 0, 4)))

        with Status(Padding("[dim]Waiting for response...[/dim]", (0, 0, 0, 4)), console=console):
            # Set up streaming request inside the status context
            response = requests.post(url, json=payload, stream=True, headers={'Accept': 'text/event-stream'})

        console.print("")
    
        def start_assistant_live():
            """Start a new Live component for assistant responses"""
            live = Live(
                Padding(Markdown(""), (0, 0, 0, 4)), 
                refresh_per_second=10, 
                console=console
            )
            live.start()
            return live
        
        def start_tool_live():
            """Start a new Live component for tool responses"""
            live = Live(
                Padding("", (0, 0, 0, 4)), 
                refresh_per_second=10, 
                console=console
            )
            live.start()
            return live
        
        def finalize_assistant_live(live, message):
            """Finalize assistant Live with a Panel"""
            if message:
                final_content = Markdown(message)
                final_panel = Panel(
                    final_content, 
                    title="Assistant", 
                    border_style="violet", 
                    box=box.ROUNDED
                )
                live.update(Padding(final_panel, (0, 4, 0, 4)))
            conversation_history.append({"role": "assistant", "content": message})

            live.stop()
        
        def finalize_tool_live(live, content):
            """Finalize tool Live with a Panel"""
            formatted_result = format_tool_result(content)
            final_panel = Panel(
                formatted_result, 
                title="Tool Result", 
                border_style="cyan",
                box=box.ROUNDED
            )
            live.update(Padding(final_panel, (0, 4, 0, 4)))
            live.stop()


        try:
            for chunk in response.iter_lines(decode_unicode=True):
                if stop_streaming:
                    break
                
                if not chunk:
                    continue
                
                try:
                    data = json.loads(chunk)
                    role = data.get('role', '')
                    content = data.get('content', '')
                    msg_type = data.get('type', '')

                    # Handle role transitions
                    if current_role != role:
                        # Finish previous Live component
                        if current_live:
                            if current_role == 'assistant':
                                finalize_assistant_live(current_live, assistant_message)
                            elif current_role == 'tool_call':
                                # Tool content should already be handled
                                current_live.stop()
                        
                        # Start new Live component
                        if role == 'assistant':
                            current_live = start_assistant_live()
                            assistant_message = ""  # Reset for new assistant message
                        elif role == 'tool_call':
                            current_live = start_tool_live()
                        
                        current_role = role

                    # Handle content based on role
                    if role == 'assistant':
                        if msg_type == 'chunk':
                            assistant_message += content
                            # Update the live assistant display
                            md = Markdown(assistant_message)
                            current_live.update(Padding(md, (0, 0, 0, 4)))
                        
                        elif msg_type == 'done':
                            # This will be handled by role transition or final cleanup
                            pass
                            
                    elif role == 'tool_call':
                        # Handle tool call immediately and finalize
                        finalize_tool_live(current_live, content)
                        current_live = None  # Will be reset on next role transition
                        
                        # Store in conversation history
 #                       full_response.append({"role": "tool", "content": content})
                        conversation_history.append({"role": "user", "content": content})

                except json.JSONDecodeError as e:
                    if chunk and len(chunk) > 0:
                        console.print(f"[red]Error parsing JSON: {e}[/red]\n[dim]Raw data: {chunk}[/dim]")

        finally:
            # Clean up any remaining Live component
            if current_live:
                if current_role == 'assistant':
                    finalize_assistant_live(current_live, assistant_message)
                else:
                    current_live.stop()
        

        
        # If we got no response at all
#        if not assistant_message and not full_response:
        if not assistant_message:
            console.print("[yellow]No response received from the server. You might need to check API connectivity or server logs.[/yellow]")
            # Add a debug option for investigating response format
            console.print("[dim]Try setting debug_mode=True in the script to see raw response data.[/dim]")
            
    except requests.RequestException as e:
        console.print(f"[bold red]Network error: {str(e)}[/bold red]")
    except Exception as e:
        console.print(f"[bold red]Error: {str(e)}[/bold red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


def save_conversation(filename=None):
    """Save the conversation history to a file"""
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"conversation_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(conversation_history, f, indent=2)
    
    console.print(f"[green]Conversation saved to {filename}[/green]")

def load_conversation(filename):
    """Load a conversation history from a file"""
    global conversation_history
    
    try:
        with open(filename, 'r') as f:
            conversation_history = json.load(f)
        console.print(f"[green]Loaded conversation from {filename}[/green]")
        
        # Display the loaded conversation
        display_conversation_history()
    except FileNotFoundError:
        console.print(f"[red]File not found: {filename}[/red]")
    except json.JSONDecodeError:
        console.print(f"[red]Invalid JSON format in file: {filename}[/red]")

def display_conversation_history():
    """Display the current conversation history"""
    for message in conversation_history:
        role = message.get("role", "")
        content = message.get("content", "")
        
        if role == "user":
            console.print(Panel(content, title="User", border_style="green", box=box.ROUNDED))
        elif role == "assistant":
            final_content = Markdown(content)
            console.print(Panel(final_content, title="Assistant", border_style="violet", box=box.ROUNDED))
        elif role == "system":
            console.print(Panel(content, title="System", border_style="yellow", box=box.ROUNDED))

def has_pending_input():
    """Check if there's input waiting in the buffer (indicates paste)"""
    try:
        if sys.stdin.isatty():
            # Unix/Linux/Mac - use select to check for pending input
            return select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], [])
    except (OSError, AttributeError):
        # Windows or other systems where select doesn't work on stdin
        pass
    return False

def handle_paste_input(first_line):
    """Handle detected paste input by collecting all buffered lines"""
    lines = [first_line]
    
    # Collect all remaining lines in buffer
    while has_pending_input():
        try:
            line = input()
            lines.append(line)
        except EOFError:
            break
        except Exception:
            break  # Safety break for any unexpected errors
    
    # Check for any remaining partial line without newline
    try:
        # Read remaining bytes that don't end with newline
        remaining = os.read(sys.stdin.fileno(), 4096)
        if remaining:
            # Decode and add the partial line
            partial_line = remaining.decode('utf-8', errors='replace').rstrip('\n')
            if partial_line:  # Only add if there's actual content
                lines.append(partial_line)
    except (OSError, BlockingIOError):
        # If os.read() would block or fails, just continue
        pass
    
    content = "\n".join(lines)
    console.print(f"[green]📋 Auto-detected multi-line paste ({len(lines)} lines)[/green]")
    return content

def intelligent_input_handler():
    """Main input handler that auto-detects paste vs normal typing"""
    try:
        # Get first line with our custom prompt
        first_line = input("│ ")
        
        # AUTO-DETECTION: Check for pasted content
        if has_pending_input():
            return handle_paste_input(first_line)
        
        # SINGLE LINE: Normal typed input
        return first_line
        
    except EOFError:
        # Handle Ctrl+D in single-line mode
        console.print("\n[yellow]Input cancelled[/yellow]")
        return None
    except KeyboardInterrupt:
        # Handle Ctrl+C
        console.print("\n[yellow]Input cancelled[/yellow]")
        return None

def get_multiline_input(prompt_text="[bold green]You[/bold green]"):
    """
    Get multi-line input from user. 
    User can type multiple lines and end with 'END' on its own line,
    or use Ctrl+D (EOF) to finish input.
    """
    console.print(f"\n{prompt_text}")
    console.print("[dim]Multi-line mode: Type your message. When done, type 'END' on a new line or press Ctrl+D[/dim]")
    
    lines = []
    try:
        while True:
            try:
                line = input("│ ")
                if line.strip() == "END":
                    break
                lines.append(line)
            except EOFError:
                # Ctrl+D pressed
                break
    except KeyboardInterrupt:
        # Ctrl+C pressed
        console.print("\n[yellow]Input cancelled[/yellow]")
        return None
    
    # Join all lines with newlines
    user_input = "\n".join(lines).strip()
    
    # If empty input, return None
    if not user_input:
        console.print("[yellow]Empty input received[/yellow]")
        return None
    
    return user_input

def print_help():
    """Display help information"""
    help_text = """
    [bold]Commands:[/bold]
    /help          - Show this help message
    /quit or /exit - Exit the program
    /multiline     - Switch to multi-line input for next message
    /m             - Shortcut for /multiline
    /multiline toggle or /m toggle - Toggle persistent multi-line mode
    /debug         - Print contents of the conversation history variable for debugging
    /save [file]   - Save conversation to a file (default: conversation_timestamp.json)
    /load [file]   - Load conversation from a file
    /history       - Display conversation history
    /clear         - Clear the conversation history
    /temp [value]  - Set temperature (0.0-1.0)
    /tokens [n]    - Set max tokens
    
    [bold]Input Modes:[/bold]
    • Default: Type and press Enter (single-line)
    • Auto-paste: Multi-line content automatically detected 📋
    • /multiline or /m: One-time multi-line mode (end with 'END' or Ctrl+D)
    • /multiline toggle or /m toggle: Persistent multi-line mode
    
    [bold]Smart Features:[/bold]
    📋 Paste detection - Multi-line content handled automatically
    🔄 Mode switching - /m for quick multi-line access
    🔒 Persistent mode - /m toggle to stay in multi-line mode
    
    [bold]Hotkeys:[/bold]
    Ctrl+C         - Stop current response or cancel input
    Ctrl+D         - Finish multi-line input (in multi-line mode)
    """
    console.print(Panel(help_text, title="Help", border_style="blue"))


def print_ascii_banner():
    """Print ASCII art banner for Qwen"""
    banner = """
 ██████  ██     ██ ███████ ███    ██ 
██    ██ ██     ██ ██      ████   ██ 
██    ██ ██  █  ██ █████   ██ ██  ██ 
██ ▄▄ ██ ██ ███ ██ ██      ██  ██ ██ 
 ██████   ███ ███  ███████ ██   ████ 
    ▀▀                              

 █████   ██████  ███████ ███    ██ ████████ ██  ██████ 
██   ██ ██       ██      ████   ██    ██    ██ ██      
███████ ██   ███ █████   ██ ██  ██    ██    ██ ██      
██   ██ ██    ██ ██      ██  ██ ██    ██    ██ ██      
██   ██  ██████  ███████ ██   ████    ██    ██  ██████ 
"""
    console.print(banner, style="violet")

def main():
    """Main function to run the CLI client"""
    parser = argparse.ArgumentParser(description="Qwen Agentic CLI Client")
    parser.add_argument("--url", default="http://localhost:5001/api/chat",
                      help="API endpoint URL (default: http://localhost:5001/api/chat)")
    parser.add_argument("--temp", type=float, default=0.7,
                      help="Temperature (0.0-1.0, default: 0.7)")
    parser.add_argument("--tokens", type=int, default=8000,
                      help="Max tokens (default: 8000)")
    parser.add_argument("--load", type=str, help="Load conversation from file")
    args = parser.parse_args()

    #FIXME: DELETE ME    
    # # Set up signal handling for Ctrl+Q (need to map in terminal)
    # signal.signal(signal.SIGQUIT, signal_handler)
    
    url = args.url
    temperature = args.temp
    max_tokens = args.tokens

    # Clear screen using rich
    console.clear()

    # Print ASCII banner
    print_ascii_banner()

    # Print welcome message with help information
    welcome_text = f"""[bold blue]Qwen Agentic CLI Client[/bold blue]

[green]Configuration:[/green]
- API Endpoint: {url}
- Temperature: {temperature}
- Max Tokens: {max_tokens}

[bold yellow]Commands:[/bold yellow]
- [bold]/help[/bold]           - Show detailed help
- [bold]/m[/bold] or [bold]/multiline[/bold] - Multi-line input (one-time or toggle)
- [bold]/quit[/bold] or [bold]/exit[/bold]  - Exit the program
- [bold]/save \[file][/bold]    - Save conversation
- [bold]/load \[file][/bold]    - Load conversation
- [bold]/history[/bold]        - Show conversation history
- [bold]/clear[/bold]          - Clear conversation history
- [bold]/temp \[value][/bold]   - Set temperature (0.0-1.0)
- [bold]/tokens \[value][/bold] - Set max tokens
- [bold]/debug[/bold]          - Debug conversation history

[bold yellow]Hotkeys:[/bold yellow]
- [bold]Ctrl+C[/bold] - Stop current response generation

[dim]Ready to chat! Use /m for multi-line input, /m toggle for persistent mode.[/dim]"""

    console.print(Panel(
        welcome_text,
        title="Welcome", 
        border_style="green",
        expand=False
    ))
    # Load conversation if specified
    if args.load:
        load_conversation(args.load)
    
    global conversation_history, multiline_mode

    # Main interaction loop
    while True:
        try:
            # Show current mode in prompt
            if multiline_mode:
                console.print("\n[bold green]You[/bold green] [dim](multi-line mode)[/dim]")
                user_input = get_multiline_input()
            else:
                console.print("\n[bold green]You[/bold green]")
                # Use intelligent input handler that auto-detects paste
                user_input = intelligent_input_handler()
            
            # Handle cancelled input
            if user_input is None:
                continue
            
            # Process commands
            if user_input.startswith("/"):
                cmd_parts = user_input.split()
                cmd = cmd_parts[0].lower()
                
                if cmd in ["/quit", "/exit"]:
                    break
                elif cmd in ["/multiline", "/m"]:
                    # Check for toggle sub-command
                    if len(cmd_parts) > 1 and cmd_parts[1].lower() == "toggle":
                        multiline_mode = not multiline_mode
                        status = "enabled" if multiline_mode else "disabled"
                        mode_indicator = " [dim](all inputs will be multi-line)[/dim]" if multiline_mode else ""
                        console.print(f"[green]Multi-line mode {status}{mode_indicator}[/green]")
                        continue
                    else:
                        # One-time multi-line input (original behavior)
                        if not multiline_mode:  # Only show message if not already in multi-line mode
                            console.print("[green]Switching to multi-line input mode for next message[/green]")
                        user_input = get_multiline_input()
                        if user_input is None:  # Handle cancellation
                            continue
                        # Fall through to normal message processing (don't continue)
                elif cmd == "/debug":
                    console.print("[bold]Current conversation history:[/bold]")
                    for i, msg in enumerate(conversation_history):
                        console.print(f"[{i}] Role: {msg.get('role', 'unknown')}, Content: {msg.get('content', '')[:50]}...")
                    continue
                elif cmd == "/help":
                    print_help()
                    continue
                elif cmd == "/save":
                    filename = cmd_parts[1] if len(cmd_parts) > 1 else None
                    save_conversation(filename)
                    continue
                elif cmd == "/load":
                    if len(cmd_parts) > 1:
                        load_conversation(cmd_parts[1])
                    else:
                        console.print("[red]Error: Please specify a file to load[/red]")
                    continue
                elif cmd == "/history":
                    display_conversation_history()
                    continue
                elif cmd == "/clear":
                    conversation_history = []
                    console.print("[green]Conversation history cleared[/green]")
                    continue
                elif cmd == "/temp":
                    if len(cmd_parts) > 1:
                        try:
                            temperature = float(cmd_parts[1])
                            if 0 <= temperature <= 1:
                                console.print(f"[green]Temperature set to {temperature}[/green]")
                            else:
                                console.print("[red]Temperature must be between 0.0 and 1.0[/red]")
                        except ValueError:
                            console.print("[red]Invalid temperature value[/red]")
                    else:
                        console.print(f"[green]Current temperature: {temperature}[/green]")
                    continue
                elif cmd == "/tokens":
                    if len(cmd_parts) > 1:
                        try:
                            max_tokens = int(cmd_parts[1])
                            console.print(f"[green]Max tokens set to {max_tokens}[/green]")
                        except ValueError:
                            console.print("[red]Invalid max tokens value[/red]")
                    else:
                        console.print(f"[green]Current max tokens: {max_tokens}[/green]")
                    continue
                else:
                    console.print("[red]Unknown command. Type /help for available commands.[/red]")
                    continue
            
            # Add user message to history
            conversation_history.append({"role": "user", "content": user_input})
            
            # Display user message in a panel
            console.print("")
            console.print(Padding(Panel(user_input, title="User", border_style="green", box=box.ROUNDED), (0, 4, 0, 4)))
            console.print("")
            
            # Process the response
            console.print("")
            console.print("[bold yellow on black]Assistant:[/bold yellow on black]")
            process_streaming_response(url, conversation_history, temperature, max_tokens)
            
        except KeyboardInterrupt:
            console.print("\n[bold red]Interrupted by user. Type /exit to quit.[/bold red]")
        except Exception as e:
            console.print(f"[bold red]Error: {str(e)}[/bold red]")

if __name__ == "__main__":
    main()
