# Qwen Agentic CLI

A powerful command-line interface for interacting with Qwen chatbot APIs. This CLI client provides a rich, interactive terminal experience with streaming responses, conversation management, and beautiful formatting.

You will need an LLM agentic inference service to use this. The recommended service can be found in this repo: [Qwen-Max-Agentic](https://github.com/jvroig/qwen-max-agentic). Aside from the agentic inference service, the Qwen-Max-Agentic repo also provides a browser-based GUI client.

Run the Qwen-Max-Agentic service first before starting this CLI client.

## Features

- 🚀 **Streaming Responses** - Real-time response display as the AI generates text
- 🎨 **Rich Terminal UI** - Beautiful markdown rendering with syntax-highlighted code blocks
- 💾 **Conversation Management** - Save and load chat histories to/from JSON files
- 🔧 **Configurable Parameters** - Adjust temperature, max tokens, and API endpoints
- 🛠️ **Tool Integration** - Formatted display of tool call results
- ⌨️ **Interactive Commands** - Built-in command system for managing conversations
- 📋 **History Display** - Review previous conversations with formatted output

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd qwen-agentic-cli
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Basic Usage

Run the CLI client with default settings:
```bash
python cli-client.py
```

### Command Line Options

```bash
python cli-client.py [OPTIONS]
```

**Available Options:**
- `--url` - API endpoint URL (default: `http://localhost:5001/api/chat`)
- `--temp` - Temperature for response generation (0.0-1.0, default: 0.7)
- `--tokens` - Maximum tokens per response (default: 8000)
- `--load` - Load a conversation from a JSON file

**Examples:**
```bash
# Connect to a different API endpoint
python cli-client.py --url http://localhost:8080/api/chat

# Set temperature and token limits
python cli-client.py --temp 0.3 --tokens 4000

# Load a previous conversation
python cli-client.py --load conversation_20240601_143022.json
```

### Interactive Commands

Once the CLI is running, you can use these commands:

| Command | Description |
|---------|-------------|
| `/help` | Show help message with all available commands |
| `/quit` or `/exit` | Exit the program |
| `/save [filename]` | Save conversation to file (auto-generates filename if not provided) |
| `/load filename` | Load conversation from file |
| `/history` | Display the current conversation history |
| `/clear` | Clear the conversation history |
| `/temp [value]` | Set or view temperature (0.0-1.0) |
| `/tokens [value]` | Set or view max tokens limit |
| `/debug` | Print conversation history for debugging |

### Keyboard Shortcuts

- **Ctrl+C** - Stop current response generation
