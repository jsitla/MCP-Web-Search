# MCP Web Search Server

A powerful Model Context Protocol (MCP) server that provides AI agents with internet search and web content capabilities.

## Features

This MCP server provides **19 tools** for web interaction:

### 🔍 Search Tools
- `search_web` - DuckDuckGo text search
- `search_news` - Latest news search
- `search_images` - Image search
- `search_youtube` - YouTube video search
- `search_wikipedia` - Wikipedia article search
- `search_maps` - Places/maps search
- `batch_search` - Multiple queries in one call

### 🌐 Web Fetching Tools
- `fetch_webpage` - Fetch static HTML pages
- `fetch_webpage_js` - Fetch JavaScript-rendered pages (Playwright)
- `fetch_as_markdown` - Convert webpage to clean Markdown (LLM-friendly)
- `crawl_website` - Multi-page website crawling

### 📄 Content Extraction Tools
- `get_youtube_transcript` - Extract YouTube video transcripts
- `read_pdf_url` - Read PDF documents from URLs
- `extract_links` - Extract all links from a page
- `get_page_metadata` - Get SEO/meta information
- `take_screenshot` - Capture webpage screenshots

### 🛠️ Utility Tools
- `get_weather` - Weather lookup
- `translate_text` - Text translation
- `clear_cache` - Clear cached results

## Installation

### Prerequisites
- Python 3.10+
- pip

### Setup

1. Clone the repository:
```bash
git clone https://github.com/YOUR_USERNAME/MCP-Web-Search.git
cd MCP-Web-Search
```

2. Create and activate virtual environment:
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

3. Install dependencies:
```bash
pip install fastmcp ddgs httpx lxml playwright markdownify youtube-transcript-api pymupdf
```

4. Install Playwright browser:
```bash
python -m playwright install chromium
```

## Configuration

### VS Code (GitHub Copilot)

Add to your `settings.json` or create `.vscode/mcp.json`:

```json
{
  "servers": {
    "internet-search": {
      "type": "stdio",
      "command": "/path/to/.venv/Scripts/python.exe",
      "args": ["/path/to/search_server.py"]
    }
  }
}
```

### Google Antigravity IDE

Add to your `mcp_config.json`:

```json
{
  "mcpServers": {
    "internet-search": {
      "command": "/path/to/.venv/Scripts/python.exe",
      "args": ["/path/to/search_server.py"],
      "env": {}
    }
  }
}
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "internet-search": {
      "command": "/path/to/.venv/Scripts/python.exe",
      "args": ["/path/to/search_server.py"]
    }
  }
}
```

## Usage Examples

Once configured, you can ask your AI assistant:

- *"Search the web for latest Python 3.13 features"*
- *"Fetch the content from python.org as markdown"*
- *"Get the transcript of this YouTube video: [URL]"*
- *"Read this PDF document: [URL]"*
- *"Take a screenshot of example.com"*
- *"What's the weather in New York?"*

## Testing

Run the server in test mode:

```bash
python search_server.py --test "your search query"
```

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
