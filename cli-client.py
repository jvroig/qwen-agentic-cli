#!/usr/bin/env python3
import json
import requests
import sys
import signal
import threading
import argparse
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
    """Format tool call results"""
    try:
        # Check if the result contains JSON
        if "```" in result and (result.count("```") >= 2):
            # Extract the code block content
            start = result.find("```") + 3
            end = result.rfind("```")
            
            # Find the end of the first line (language specifier)
            first_line_end = result.find("\n", start)
            if first_line_end > start and first_line_end < end:
                language = result[start:first_line_end].strip()
                content = result[first_line_end+1:end].strip()
            else:
                language = "json"
                content = result[start:end].strip()
                
            try:
                # Try to parse as JSON for pretty formatting
                parsed = json.loads(content)
                syntax = Syntax(json.dumps(parsed, indent=2), "json", theme="monokai", line_numbers=True)
                #return Panel(syntax, title="Tool Result", border_style="yellow", box=box.ROUNDED)
            except json.JSONDecodeError:
                # If not valid JSON, just format with the detected language
                syntax = Syntax(content, language, theme="monokai", line_numbers=True)
                #return Panel(syntax, title="Tool Result", border_style="yellow", box=box.ROUNDED)

            return syntax

        # If no code block markers, treat as plain text
        if result.startswith("Tool result: "):
            result = result[len("Tool result: "):]
        #return Panel(result, title="Tool Result", border_style="yellow", box=box.ROUNDED)
        return result

    except Exception as e:
        #return Panel(f"Error formatting tool result: {str(e)}\n\nOriginal result: {result}", 
        #           title="Tool Result (Error)", border_style="red", box=box.ROUNDED)
        return "Error formatting tool result: {str(e)}\n\nOriginal result: {result}"
    

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
        full_response = []
        
        # Show a message while waiting for the first response
        # console.print(Padding("[dim]Waiting for response...[/dim]",(0, 0, 0, 4)))

        with Status(Padding("[dim]Waiting for response...[/dim]", (0, 0, 0, 4)), console=console):
            # Set up streaming request inside the status context
            response = requests.post(url, json=payload, stream=True, headers={'Accept': 'text/event-stream'})

        console.print("")

        # Create Live display context for updating in real-time
        with Live(Padding("", (0, 0, 0, 4)), refresh_per_second=10, console=console) as live:
            # Debug info for troubleshooting
            debug_mode = False  # Set to True to see raw response chunks

            current_role = ""            
            for chunk in response.iter_lines(decode_unicode=True):
                if stop_streaming:
                    break
                
                if not chunk:
                    continue
                
                # Debug raw chunks if needed
                if debug_mode:
                    live.update(Padding(f"[dim]DEBUG: {chunk}[/dim]", (0, 0, 0, 4)))
                    continue
                
                # Process the chunk directly as JSON (no data: prefix in this API)
                try:
                    data = json.loads(chunk)
                    role = data.get('role', '')
                    content = data.get('content', '')
                    msg_type = data.get('type', '')

                    # Detect role switch from assistant to tool_call
                    if current_role == 'assistant' and role == 'tool_call':
                        assistant_message += "\n\n"  # Add newline when switching away from assistant
                    
                    # Update current role
                    current_role = role

                    if role == 'assistant':
                        if msg_type == 'chunk':
                            assistant_message += content
                            # Format the growing message with markdown
                            md = Markdown(assistant_message)
                            live.update(Padding(md, (0, 0, 0, 4)))
                        
                        elif msg_type == 'done':
                            # Completed message
                            if assistant_message:  # Only add if we got content
                                final_content = Markdown(assistant_message + "\n")
                                    
                                # live.update(Panel(Padding(final_content, (0, 0, 0, 4)), title="Agent", border_style="violet", box=box.ROUNDED))
                                live.update(Padding(Panel(final_content, title="Agent", border_style="violet", box=box.ROUNDED), (0, 4, 0, 4)))
                                full_response.append({"role": "assistant", "content": assistant_message})
                                conversation_history.append({"role": "assistant", "content": assistant_message})
                            
                    elif role == 'tool_call':
                        # Tool call result
                        formatted_result = format_tool_result(content)
                        assistant_message += formatted_result + "\n\n"
                        live.update(Padding(assistant_message, (0, 0, 0, 4)))
                        full_response.append({"role": "tool", "content": content})
                        conversation_history.append({"role": "user", "content": content})
                
                except json.JSONDecodeError as e:
                    # If we can't parse as JSON, let's just show the raw data
                    if chunk and len(chunk) > 0:  # Only display non-empty chunks
                        live.update(Padding(f"[red]Error parsing JSON: {e}[/red]\n[dim]Raw data: {chunk}[/dim]", (0, 0, 0, 4)))
        

        
        # If we got no response at all
        if not assistant_message and not full_response:
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
            # Process code blocks the same way as in live display
            blocks = format_code_blocks(content)
            if isinstance(blocks, list):
                # Create a group of rendered blocks
                for block in blocks:
                    if isinstance(block, str):
                        console.print(Markdown(block))
                    else:
                        # This is a Syntax object (code block)
                        console.print(block)
            else:
                console.print(Markdown(blocks))
        elif role == "system":
            console.print(Panel(content, title="System", border_style="yellow", box=box.ROUNDED))

def print_help():
    """Display help information"""
    help_text = """
    [bold]Commands:[/bold]
    /help          - Show this help message
    /quit or /exit - Exit the program
    /debug         - Print contents of the conversation history variable for debugging
    /save [file]   - Save conversation to a file (default: conversation_timestamp.json)
    /load [file]   - Load conversation from a file
    /history       - Display conversation history
    /clear         - Clear the conversation history
    /temp [value]  - Set temperature (0.0-1.0)
    /tokens [n]    - Set max tokens
    
    [bold]Hotkeys:[/bold]
    Ctrl+C         - Stop current response
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

[dim]Ready to chat! Type your message or use commands above.[/dim]"""

    console.print(Panel(
        welcome_text,
        title="Welcome", 
        border_style="green",
        expand=False
    ))
    # Load conversation if specified
    if args.load:
        load_conversation(args.load)
    
    global conversation_history

    # Main interaction loop
    while True:
        try:
            user_input = Prompt.ask("\n[bold green]You[/bold green]")
            
            # Process commands
            if user_input.startswith("/"):
                cmd_parts = user_input.split()
                cmd = cmd_parts[0].lower()
                
                if cmd in ["/quit", "/exit"]:
                    break
                # Add this to your command processing section
                elif cmd == "/debug":
                    console.print("[bold]Current conversation history:[/bold]")
                    for i, msg in enumerate(conversation_history):
                        console.print(f"[{i}] Role: {msg.get('role', 'unknown')}, Content: {msg.get('content', '')[:50]}...")
                elif cmd == "/help":
                    print_help()
                elif cmd == "/save":
                    filename = cmd_parts[1] if len(cmd_parts) > 1 else None
                    save_conversation(filename)
                elif cmd == "/load":
                    if len(cmd_parts) > 1:
                        load_conversation(cmd_parts[1])
                    else:
                        console.print("[red]Error: Please specify a file to load[/red]")
                elif cmd == "/history":
                    display_conversation_history()
                elif cmd == "/clear":
                    conversation_history = []
                    console.print("[green]Conversation history cleared[/green]")
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
                elif cmd == "/tokens":
                    if len(cmd_parts) > 1:
                        try:
                            max_tokens = int(cmd_parts[1])
                            console.print(f"[green]Max tokens set to {max_tokens}[/green]")
                        except ValueError:
                            console.print("[red]Invalid max tokens value[/red]")
                    else:
                        console.print(f"[green]Current max tokens: {max_tokens}[/green]")
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
