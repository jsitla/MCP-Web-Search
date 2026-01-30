import json
import httpx
import base64
import os
import re
import time
import hashlib
from functools import lru_cache
from fastmcp import FastMCP
from ddgs import DDGS
from lxml import html
from urllib.parse import urljoin, urlparse
from markdownify import markdownify as md

# Initialize the MCP server
mcp = FastMCP("Internet Search")

# ============================================================================
# SIMPLE CACHE IMPLEMENTATION
# ============================================================================

class SimpleCache:
    """Simple in-memory cache with TTL support."""
    
    def __init__(self, default_ttl: int = 300):  # 5 minutes default
        self._cache = {}
        self._timestamps = {}
        self.default_ttl = default_ttl
    
    def _make_key(self, *args, **kwargs) -> str:
        """Create a hash key from arguments."""
        key_str = json.dumps([args, kwargs], sort_keys=True, default=str)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, key: str):
        """Get value from cache if not expired."""
        if key in self._cache:
            if time.time() - self._timestamps[key] < self.default_ttl:
                return self._cache[key]
            else:
                # Expired, remove it
                del self._cache[key]
                del self._timestamps[key]
        return None
    
    def set(self, key: str, value, ttl: int = None):
        """Set value in cache."""
        self._cache[key] = value
        self._timestamps[key] = time.time()
    
    def clear(self):
        """Clear all cache."""
        self._cache.clear()
        self._timestamps.clear()

# Global cache instance
cache = SimpleCache(default_ttl=300)  # 5 minute cache


# ============================================================================
# WEB SEARCH TOOLS
# ============================================================================

def _search_web_impl(query: str, max_results: int = 5) -> str:
    """
    Internal implementation of web search using DuckDuckGo.
    
    Args:
        query: The search query string
        max_results: Maximum number of results to return (default: 5)
    
    Returns:
        Search results as a JSON string containing title, URL, and snippet for each result
    """
    try:
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=max_results))
        
        if not results:
            return json.dumps({"status": "success", "results": [], "message": "No results found."})
        
        # Format results with Title, URL, and Snippet
        formatted_results = []
        for result in results:
            formatted_results.append({
                "title": result.get("title", "No title"),
                "url": result.get("href", "No URL"),
                "snippet": result.get("body", "No description")
            })
        
        return json.dumps({
            "status": "success",
            "query": query,
            "results": formatted_results
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "query": query,
            "message": f"Search failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """
    Search the internet using DuckDuckGo.
    
    Args:
        query: The search query string
        max_results: Maximum number of results to return (default: 5)
    
    Returns:
        Search results as a JSON string containing title, URL, and snippet for each result
    """
    return _search_web_impl(query, max_results)


def _fetch_webpage_impl(url: str, max_length: int = 5000) -> str:
    """
    Internal implementation of webpage fetching.
    
    Args:
        url: The URL to fetch
        max_length: Maximum length of text to return (default: 5000 characters)
    
    Returns:
        The webpage content as JSON string
    """
    try:
        # Add https:// if no protocol specified
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        
        # Parse HTML and extract text
        tree = html.fromstring(response.content)
        
        # Remove script and style elements
        for element in tree.xpath('//script | //style | //noscript'):
            element.getparent().remove(element)
        
        # Get title
        title_elem = tree.xpath('//title/text()')
        title = title_elem[0].strip() if title_elem else "No title"
        
        # Get meta description
        meta_desc = tree.xpath('//meta[@name="description"]/@content')
        description = meta_desc[0] if meta_desc else ""
        
        # Get main text content
        text_content = tree.xpath('//body//text()')
        text = ' '.join([t.strip() for t in text_content if t.strip()])
        
        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length] + "... [truncated]"
        
        return json.dumps({
            "status": "success",
            "url": url,
            "title": title,
            "description": description,
            "content": text
        }, indent=2)
    
    except httpx.HTTPStatusError as e:
        return json.dumps({
            "status": "error",
            "url": url,
            "message": f"HTTP error {e.response.status_code}: {e.response.reason_phrase}"
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "url": url,
            "message": f"Failed to fetch webpage: {str(e)}"
        }, indent=2)


@mcp.tool()
def fetch_webpage(url: str, max_length: int = 5000) -> str:
    """
    Fetch and read the content of a webpage (for static HTML pages).
    
    Args:
        url: The URL to fetch (e.g., "example.com" or "https://example.com")
        max_length: Maximum length of text content to return (default: 5000 characters)
    
    Returns:
        The webpage content as JSON string with title, description, and text content
    """
    return _fetch_webpage_impl(url, max_length)


def _fetch_webpage_js_impl(url: str, max_length: int = 5000, wait_time: int = 3) -> str:
    """
    Internal implementation of webpage fetching with JavaScript rendering using Playwright.
    
    Args:
        url: The URL to fetch
        max_length: Maximum length of text to return (default: 5000 characters)
        wait_time: Seconds to wait for JavaScript to render (default: 3)
    
    Returns:
        The webpage content as JSON string
    """
    try:
        from playwright.sync_api import sync_playwright
        
        # Add https:// if no protocol specified
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Navigate and wait for content to load
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(wait_time * 1000)  # Additional wait for JS rendering
            
            # Get title
            title = page.title() or "No title"
            
            # Get meta description
            description = ""
            meta_desc = page.query_selector('meta[name="description"]')
            if meta_desc:
                description = meta_desc.get_attribute('content') or ""
            
            # Get visible text content
            text_content = page.inner_text('body')
            
            # Clean up whitespace
            text = ' '.join(text_content.split())
            
            # Truncate if too long
            if len(text) > max_length:
                text = text[:max_length] + "... [truncated]"
            
            browser.close()
            
            return json.dumps({
                "status": "success",
                "url": url,
                "title": title,
                "description": description,
                "content": text
            }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "url": url,
            "message": f"Failed to fetch webpage: {str(e)}"
        }, indent=2)


@mcp.tool()
def fetch_webpage_js(url: str, max_length: int = 5000, wait_time: int = 3) -> str:
    """
    Fetch and read content from a JavaScript-heavy webpage using a headless browser.
    Use this for modern web apps (React, Vue, Angular) that render content with JavaScript.
    
    Args:
        url: The URL to fetch (e.g., "example.com" or "https://example.com")
        max_length: Maximum length of text content to return (default: 5000 characters)
        wait_time: Seconds to wait for JavaScript to render (default: 3)
    
    Returns:
        The webpage content as JSON string with title, description, and text content
    """
    return _fetch_webpage_js_impl(url, max_length, wait_time)


# ============================================================================
# NEWS SEARCH
# ============================================================================

def _search_news_impl(query: str, max_results: int = 5) -> str:
    """Search for news articles using DuckDuckGo."""
    try:
        ddgs = DDGS()
        results = list(ddgs.news(query, max_results=max_results))
        
        if not results:
            return json.dumps({"status": "success", "results": [], "message": "No news found."})
        
        formatted_results = []
        for result in results:
            formatted_results.append({
                "title": result.get("title", "No title"),
                "url": result.get("url", "No URL"),
                "snippet": result.get("body", "No description"),
                "source": result.get("source", "Unknown"),
                "date": result.get("date", "Unknown")
            })
        
        return json.dumps({
            "status": "success",
            "query": query,
            "results": formatted_results
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "query": query,
            "message": f"News search failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def search_news(query: str, max_results: int = 5) -> str:
    """
    Search for recent news articles using DuckDuckGo News.
    
    Args:
        query: The news search query
        max_results: Maximum number of results (default: 5)
    
    Returns:
        News articles as JSON with title, URL, snippet, source, and date
    """
    return _search_news_impl(query, max_results)


# ============================================================================
# IMAGE SEARCH
# ============================================================================

def _search_images_impl(query: str, max_results: int = 5) -> str:
    """Search for images using DuckDuckGo."""
    try:
        ddgs = DDGS()
        results = list(ddgs.images(query, max_results=max_results))
        
        if not results:
            return json.dumps({"status": "success", "results": [], "message": "No images found."})
        
        formatted_results = []
        for result in results:
            formatted_results.append({
                "title": result.get("title", "No title"),
                "image_url": result.get("image", ""),
                "thumbnail_url": result.get("thumbnail", ""),
                "source_url": result.get("url", ""),
                "width": result.get("width", 0),
                "height": result.get("height", 0),
                "source": result.get("source", "Unknown")
            })
        
        return json.dumps({
            "status": "success",
            "query": query,
            "results": formatted_results
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "query": query,
            "message": f"Image search failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def search_images(query: str, max_results: int = 5) -> str:
    """
    Search for images on the web using DuckDuckGo Images.
    
    Args:
        query: The image search query
        max_results: Maximum number of results (default: 5)
    
    Returns:
        Images as JSON with title, image_url, thumbnail_url, dimensions, and source
    """
    return _search_images_impl(query, max_results)


# ============================================================================
# SCREENSHOT
# ============================================================================

def _take_screenshot_impl(url: str, full_page: bool = False, output_path: str = None) -> str:
    """Take a screenshot of a webpage using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
        
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 720})
            
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(2000)
            
            # Generate filename if not provided
            if not output_path:
                domain = urlparse(url).netloc.replace('.', '_')
                output_path = f"screenshot_{domain}.png"
            
            # Take screenshot
            screenshot_bytes = page.screenshot(full_page=full_page)
            
            # Save to file
            with open(output_path, 'wb') as f:
                f.write(screenshot_bytes)
            
            # Also return base64 for inline viewing
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            browser.close()
            
            return json.dumps({
                "status": "success",
                "url": url,
                "saved_to": os.path.abspath(output_path),
                "full_page": full_page,
                "base64_preview": screenshot_b64[:500] + "..." if len(screenshot_b64) > 500 else screenshot_b64
            }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "url": url,
            "message": f"Screenshot failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def take_screenshot(url: str, full_page: bool = False, output_path: str = None) -> str:
    """
    Take a screenshot of a webpage.
    
    Args:
        url: The URL to screenshot
        full_page: If True, capture the entire scrollable page (default: False)
        output_path: Optional file path to save the screenshot (default: auto-generated)
    
    Returns:
        JSON with status, file path, and base64 preview
    """
    return _take_screenshot_impl(url, full_page, output_path)


# ============================================================================
# EXTRACT LINKS
# ============================================================================

def _extract_links_impl(url: str, same_domain_only: bool = False) -> str:
    """Extract all links from a webpage."""
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        
        tree = html.fromstring(response.content)
        base_domain = urlparse(url).netloc
        
        links = []
        seen = set()
        
        for anchor in tree.xpath('//a[@href]'):
            href = anchor.get('href', '')
            text = anchor.text_content().strip()[:100] if anchor.text_content() else ""
            
            # Convert relative URLs to absolute
            full_url = urljoin(url, href)
            
            # Skip non-http links, anchors, javascript
            if not full_url.startswith(('http://', 'https://')):
                continue
            
            # Filter by domain if requested
            if same_domain_only:
                link_domain = urlparse(full_url).netloc
                if link_domain != base_domain:
                    continue
            
            # Deduplicate
            if full_url in seen:
                continue
            seen.add(full_url)
            
            links.append({
                "url": full_url,
                "text": text
            })
        
        return json.dumps({
            "status": "success",
            "source_url": url,
            "total_links": len(links),
            "links": links
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "url": url,
            "message": f"Failed to extract links: {str(e)}"
        }, indent=2)


@mcp.tool()
def extract_links(url: str, same_domain_only: bool = False) -> str:
    """
    Extract all hyperlinks from a webpage.
    
    Args:
        url: The URL to extract links from
        same_domain_only: If True, only return links to the same domain (default: False)
    
    Returns:
        JSON with list of links containing URL and anchor text
    """
    return _extract_links_impl(url, same_domain_only)


# ============================================================================
# WIKIPEDIA SEARCH
# ============================================================================

def _search_wikipedia_impl(query: str, sentences: int = 3) -> str:
    """Search Wikipedia and get article summaries."""
    try:
        # Use Wikipedia API
        api_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + query.replace(' ', '_')
        
        headers = {
            'User-Agent': 'MCPSearchServer/1.0 (https://github.com/mcp; contact@example.com)'
        }
        
        with httpx.Client(follow_redirects=True, timeout=10.0) as client:
            response = client.get(api_url, headers=headers)
            
            if response.status_code == 404:
                # Try search instead
                search_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=5&format=json"
                search_resp = client.get(search_url, headers=headers)
                search_data = search_resp.json()
                
                if len(search_data) >= 4 and search_data[1]:
                    suggestions = [{"title": t, "url": u} for t, u in zip(search_data[1], search_data[3])]
                    return json.dumps({
                        "status": "not_found",
                        "query": query,
                        "message": "Article not found. Did you mean:",
                        "suggestions": suggestions
                    }, indent=2)
                else:
                    return json.dumps({
                        "status": "not_found",
                        "query": query,
                        "message": "No Wikipedia article found for this query."
                    }, indent=2)
            
            response.raise_for_status()
            data = response.json()
            
            # Truncate extract to requested sentences
            extract = data.get("extract", "")
            if sentences and extract:
                sentence_list = extract.split('. ')
                extract = '. '.join(sentence_list[:sentences])
                if not extract.endswith('.'):
                    extract += '.'
            
            return json.dumps({
                "status": "success",
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "extract": extract,
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "thumbnail": data.get("thumbnail", {}).get("source", "")
            }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "query": query,
            "message": f"Wikipedia search failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def search_wikipedia(query: str, sentences: int = 3) -> str:
    """
    Search Wikipedia and get a summary of the article.
    
    Args:
        query: The Wikipedia article title or search term
        sentences: Number of sentences to return in summary (default: 3)
    
    Returns:
        JSON with article title, description, extract, URL, and thumbnail
    """
    return _search_wikipedia_impl(query, sentences)


# ============================================================================
# YOUTUBE SEARCH
# ============================================================================

def _search_youtube_impl(query: str, max_results: int = 5) -> str:
    """Search YouTube videos using DuckDuckGo."""
    try:
        ddgs = DDGS()
        results = list(ddgs.videos(query, max_results=max_results))
        
        if not results:
            return json.dumps({"status": "success", "results": [], "message": "No videos found."})
        
        formatted_results = []
        for result in results:
            formatted_results.append({
                "title": result.get("title", "No title"),
                "url": result.get("content", ""),
                "description": result.get("description", ""),
                "publisher": result.get("publisher", "Unknown"),
                "duration": result.get("duration", ""),
                "views": result.get("statistics", {}).get("viewCount", "Unknown") if isinstance(result.get("statistics"), dict) else "Unknown",
                "thumbnail": result.get("images", {}).get("large", "") if isinstance(result.get("images"), dict) else ""
            })
        
        return json.dumps({
            "status": "success",
            "query": query,
            "results": formatted_results
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "query": query,
            "message": f"YouTube search failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def search_youtube(query: str, max_results: int = 5) -> str:
    """
    Search for YouTube videos.
    
    Args:
        query: The video search query
        max_results: Maximum number of results (default: 5)
    
    Returns:
        Videos as JSON with title, URL, description, publisher, duration, and thumbnail
    """
    return _search_youtube_impl(query, max_results)


# ============================================================================
# PAGE METADATA
# ============================================================================

def _get_page_metadata_impl(url: str) -> str:
    """Extract metadata (meta tags, OpenGraph, Twitter cards) from a webpage."""
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        
        tree = html.fromstring(response.content)
        
        # Basic metadata
        title_elem = tree.xpath('//title/text()')
        title = title_elem[0].strip() if title_elem else ""
        
        meta_desc = tree.xpath('//meta[@name="description"]/@content')
        description = meta_desc[0] if meta_desc else ""
        
        meta_keywords = tree.xpath('//meta[@name="keywords"]/@content')
        keywords = meta_keywords[0] if meta_keywords else ""
        
        # OpenGraph metadata
        og_data = {}
        for meta in tree.xpath('//meta[starts-with(@property, "og:")]'):
            prop = meta.get('property', '').replace('og:', '')
            content = meta.get('content', '')
            if prop and content:
                og_data[prop] = content
        
        # Twitter Card metadata
        twitter_data = {}
        for meta in tree.xpath('//meta[starts-with(@name, "twitter:")]'):
            name = meta.get('name', '').replace('twitter:', '')
            content = meta.get('content', '')
            if name and content:
                twitter_data[name] = content
        
        # Canonical URL
        canonical = tree.xpath('//link[@rel="canonical"]/@href')
        canonical_url = canonical[0] if canonical else ""
        
        # Favicon
        favicon = tree.xpath('//link[@rel="icon"]/@href | //link[@rel="shortcut icon"]/@href')
        favicon_url = urljoin(url, favicon[0]) if favicon else ""
        
        return json.dumps({
            "status": "success",
            "url": url,
            "title": title,
            "description": description,
            "keywords": keywords,
            "canonical_url": canonical_url,
            "favicon": favicon_url,
            "opengraph": og_data,
            "twitter_card": twitter_data
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "url": url,
            "message": f"Failed to extract metadata: {str(e)}"
        }, indent=2)


@mcp.tool()
def get_page_metadata(url: str) -> str:
    """
    Extract metadata from a webpage including OpenGraph and Twitter Card data.
    Useful for SEO analysis, link previews, and understanding page structure.
    
    Args:
        url: The URL to extract metadata from
    
    Returns:
        JSON with title, description, keywords, OpenGraph data, and Twitter Card data
    """
    return _get_page_metadata_impl(url)


# ============================================================================
# WEATHER
# ============================================================================

def _get_weather_impl(location: str) -> str:
    """Get current weather for a location using wttr.in."""
    try:
        # Use wttr.in API (free, no API key required)
        api_url = f"https://wttr.in/{location}?format=j1"
        
        headers = {
            'User-Agent': 'MCPSearchServer/1.0'
        }
        
        with httpx.Client(timeout=10.0) as client:
            response = client.get(api_url, headers=headers)
            response.raise_for_status()
        
        data = response.json()
        
        current = data.get("current_condition", [{}])[0]
        area = data.get("nearest_area", [{}])[0]
        
        location_name = area.get("areaName", [{}])[0].get("value", location)
        country = area.get("country", [{}])[0].get("value", "")
        region = area.get("region", [{}])[0].get("value", "")
        
        return json.dumps({
            "status": "success",
            "location": {
                "name": location_name,
                "region": region,
                "country": country
            },
            "current": {
                "temperature_c": current.get("temp_C", ""),
                "temperature_f": current.get("temp_F", ""),
                "feels_like_c": current.get("FeelsLikeC", ""),
                "feels_like_f": current.get("FeelsLikeF", ""),
                "condition": current.get("weatherDesc", [{}])[0].get("value", ""),
                "humidity": current.get("humidity", "") + "%",
                "wind_kph": current.get("windspeedKmph", ""),
                "wind_mph": current.get("windspeedMiles", ""),
                "wind_direction": current.get("winddir16Point", ""),
                "uv_index": current.get("uvIndex", ""),
                "visibility_km": current.get("visibility", ""),
                "pressure_mb": current.get("pressure", "")
            }
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "location": location,
            "message": f"Weather lookup failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def get_weather(location: str) -> str:
    """
    Get current weather for a location.
    
    Args:
        location: City name, zip code, or coordinates (e.g., "London", "10001", "48.8566,2.3522")
    
    Returns:
        JSON with current weather conditions including temperature, humidity, wind, and more
    """
    return _get_weather_impl(location)


# ============================================================================
# TRANSLATE TEXT
# ============================================================================

def _translate_text_impl(text: str, target_lang: str = "en", source_lang: str = "auto") -> str:
    """Translate text using MyMemory Translation API (free)."""
    try:
        # Detect language if auto
        if source_lang == "auto":
            # Use a simple detection - try to translate from detected language
            # MyMemory doesn't support auto, so we'll use their detection endpoint
            detect_url = f"https://api.mymemory.translated.net/get?q={text[:100]}&langpair=en|en"
            with httpx.Client(timeout=10.0) as client:
                detect_resp = client.get(detect_url)
                detect_data = detect_resp.json()
                detected = detect_data.get("responseData", {}).get("detectedLanguage", "en")
                source_lang = detected if detected else "en"
        
        # Use MyMemory free translation API
        api_url = "https://api.mymemory.translated.net/get"
        
        params = {
            "q": text,
            "langpair": f"{source_lang}|{target_lang}"
        }
        
        with httpx.Client(timeout=10.0) as client:
            response = client.get(api_url, params=params)
            response.raise_for_status()
        
        data = response.json()
        
        if data.get("responseStatus") == 200:
            translated = data.get("responseData", {}).get("translatedText", "")
            
            return json.dumps({
                "status": "success",
                "original_text": text,
                "translated_text": translated,
                "source_language": source_lang,
                "target_language": target_lang
            }, indent=2)
        else:
            return json.dumps({
                "status": "error",
                "message": data.get("responseDetails", "Translation failed")
            }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "text": text,
            "message": f"Translation failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def translate_text(text: str, target_lang: str = "en", source_lang: str = "auto") -> str:
    """
    Translate text between languages.
    
    Args:
        text: The text to translate
        target_lang: Target language code (e.g., "en", "es", "fr", "de", "it", "ja", "zh")
        source_lang: Source language code, or "auto" to detect (default: "auto")
    
    Returns:
        JSON with original text, translated text, and language codes
    """
    return _translate_text_impl(text, target_lang, source_lang)


# ============================================================================
# MAPS / LOCATION SEARCH
# ============================================================================

def _search_maps_impl(query: str, max_results: int = 5) -> str:
    """Search for places/locations using DuckDuckGo."""
    try:
        ddgs = DDGS()
        results = list(ddgs.maps(query, max_results=max_results))
        
        if not results:
            return json.dumps({"status": "success", "results": [], "message": "No places found."})
        
        formatted_results = []
        for result in results:
            formatted_results.append({
                "title": result.get("title", "No title"),
                "address": result.get("address", ""),
                "city": result.get("city", ""),
                "state": result.get("state", ""),
                "country": result.get("country", ""),
                "phone": result.get("phone", ""),
                "website": result.get("url", ""),
                "latitude": result.get("latitude", ""),
                "longitude": result.get("longitude", ""),
                "category": result.get("category", "")
            })
        
        return json.dumps({
            "status": "success",
            "query": query,
            "results": formatted_results
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "query": query,
            "message": f"Maps search failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def search_maps(query: str, max_results: int = 5) -> str:
    """
    Search for places, businesses, and locations.
    
    Args:
        query: The place/location search query (e.g., "coffee shops in New York")
        max_results: Maximum number of results (default: 5)
    
    Returns:
        Places as JSON with name, address, phone, website, and coordinates
    """
    return _search_maps_impl(query, max_results)


# ============================================================================
# FETCH AS MARKDOWN (Clean output for LLMs)
# ============================================================================

def _fetch_as_markdown_impl(url: str, max_length: int = 10000) -> str:
    """Fetch a webpage and convert to clean Markdown."""
    try:
        # Check cache first
        cache_key = cache._make_key("markdown", url, max_length)
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        }
        
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        
        # Parse HTML
        tree = html.fromstring(response.content)
        
        # Get title
        title_elem = tree.xpath('//title/text()')
        title = title_elem[0].strip() if title_elem else "No title"
        
        # Remove unwanted elements
        for element in tree.xpath('//script | //style | //noscript | //nav | //footer | //header | //aside | //iframe | //form'):
            if element.getparent() is not None:
                element.getparent().remove(element)
        
        # Get main content area if exists, otherwise body
        main_content = tree.xpath('//main | //article | //div[@role="main"]')
        if main_content:
            html_content = html.tostring(main_content[0], encoding='unicode')
        else:
            body = tree.xpath('//body')
            html_content = html.tostring(body[0], encoding='unicode') if body else ""
        
        # Convert to Markdown
        markdown_content = md(html_content, heading_style="ATX", strip=['img', 'a'])
        
        # Clean up excessive whitespace
        markdown_content = re.sub(r'\n{3,}', '\n\n', markdown_content)
        markdown_content = markdown_content.strip()
        
        # Truncate if too long
        if len(markdown_content) > max_length:
            markdown_content = markdown_content[:max_length] + "\n\n... [truncated]"
        
        result = json.dumps({
            "status": "success",
            "url": url,
            "title": title,
            "content_markdown": markdown_content
        }, indent=2)
        
        # Cache the result
        cache.set(cache_key, result)
        return result
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "url": url,
            "message": f"Failed to fetch as markdown: {str(e)}"
        }, indent=2)


@mcp.tool()
def fetch_as_markdown(url: str, max_length: int = 10000) -> str:
    """
    Fetch a webpage and convert it to clean Markdown format.
    Best for LLM processing - removes ads, navigation, scripts.
    
    Args:
        url: The URL to fetch
        max_length: Maximum content length (default: 10000 characters)
    
    Returns:
        JSON with title and clean Markdown content
    """
    return _fetch_as_markdown_impl(url, max_length)


# ============================================================================
# YOUTUBE TRANSCRIPT
# ============================================================================

def _get_youtube_transcript_impl(video_url: str, language: str = "en") -> str:
    """Get transcript from a YouTube video."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        # Extract video ID from URL
        video_id = None
        patterns = [
            r'(?:v=|/v/|youtu\.be/|/embed/)([a-zA-Z0-9_-]{11})',
            r'^([a-zA-Z0-9_-]{11})$'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, video_url)
            if match:
                video_id = match.group(1)
                break
        
        if not video_id:
            return json.dumps({
                "status": "error",
                "message": "Could not extract video ID from URL"
            }, indent=2)
        
        # Check cache
        cache_key = cache._make_key("youtube", video_id, language)
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        # Try to get transcript using new API
        try:
            ytt_api = YouTubeTranscriptApi()
            transcript_data = ytt_api.fetch(video_id)
            
            # Format transcript
            full_text = ""
            segments = []
            for entry in transcript_data:
                text = entry.text if hasattr(entry, 'text') else entry.get('text', '')
                start = entry.start if hasattr(entry, 'start') else entry.get('start', 0)
                duration = entry.duration if hasattr(entry, 'duration') else entry.get('duration', 0)
                full_text += text + " "
                segments.append({
                    "start": round(start, 2),
                    "duration": round(duration, 2),
                    "text": text
                })
            
            result = json.dumps({
                "status": "success",
                "video_id": video_id,
                "language": language,
                "full_text": full_text.strip(),
                "segments": segments[:100]  # Limit segments to avoid huge responses
            }, indent=2)
            
            cache.set(cache_key, result)
            return result
                
        except Exception as inner_e:
            return json.dumps({
                "status": "error",
                "video_id": video_id,
                "message": f"Transcript error: {str(inner_e)}"
            }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "url": video_url,
            "message": f"Failed to get transcript: {str(e)}"
        }, indent=2)


@mcp.tool()
def get_youtube_transcript(video_url: str, language: str = "en") -> str:
    """
    Get the transcript/captions from a YouTube video.
    
    Args:
        video_url: YouTube video URL or video ID
        language: Preferred language code (default: "en")
    
    Returns:
        JSON with full transcript text and timestamped segments
    """
    return _get_youtube_transcript_impl(video_url, language)


# ============================================================================
# CRAWL WEBSITE (Multiple pages)
# ============================================================================

def _crawl_website_impl(url: str, max_pages: int = 10, same_domain: bool = True) -> str:
    """Crawl a website and extract content from multiple pages."""
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        base_domain = urlparse(url).netloc
        visited = set()
        to_visit = [url]
        pages = []
        
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            while to_visit and len(pages) < max_pages:
                current_url = to_visit.pop(0)
                
                if current_url in visited:
                    continue
                
                visited.add(current_url)
                
                try:
                    response = client.get(current_url, headers=headers)
                    response.raise_for_status()
                    
                    tree = html.fromstring(response.content)
                    
                    # Get title
                    title_elem = tree.xpath('//title/text()')
                    title = title_elem[0].strip() if title_elem else "No title"
                    
                    # Remove scripts/styles
                    for element in tree.xpath('//script | //style | //noscript'):
                        if element.getparent() is not None:
                            element.getparent().remove(element)
                    
                    # Get text content
                    text_content = tree.xpath('//body//text()')
                    text = ' '.join([t.strip() for t in text_content if t.strip()])[:2000]
                    
                    pages.append({
                        "url": current_url,
                        "title": title,
                        "content_preview": text
                    })
                    
                    # Find more links
                    for anchor in tree.xpath('//a[@href]'):
                        href = anchor.get('href', '')
                        full_url = urljoin(current_url, href)
                        
                        # Filter URLs
                        if not full_url.startswith(('http://', 'https://')):
                            continue
                        
                        if same_domain and urlparse(full_url).netloc != base_domain:
                            continue
                        
                        # Skip common non-content URLs
                        skip_patterns = ['.pdf', '.jpg', '.png', '.gif', '.css', '.js', '#', 'mailto:', 'tel:']
                        if any(p in full_url.lower() for p in skip_patterns):
                            continue
                        
                        if full_url not in visited and full_url not in to_visit:
                            to_visit.append(full_url)
                
                except Exception as e:
                    continue
        
        return json.dumps({
            "status": "success",
            "start_url": url,
            "pages_crawled": len(pages),
            "pages": pages
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "url": url,
            "message": f"Crawl failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def crawl_website(url: str, max_pages: int = 10, same_domain: bool = True) -> str:
    """
    Crawl a website and extract content from multiple pages.
    
    Args:
        url: The starting URL to crawl
        max_pages: Maximum number of pages to crawl (default: 10)
        same_domain: Only crawl pages on the same domain (default: True)
    
    Returns:
        JSON with list of crawled pages, each with URL, title, and content preview
    """
    return _crawl_website_impl(url, max_pages, same_domain)


# ============================================================================
# READ PDF FROM URL
# ============================================================================

def _read_pdf_url_impl(url: str, max_pages: int = 20) -> str:
    """Download and read a PDF from a URL."""
    try:
        import fitz  # PyMuPDF
        
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Check cache
        cache_key = cache._make_key("pdf", url, max_pages)
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        
        # Check if it's actually a PDF
        content_type = response.headers.get('content-type', '')
        if 'pdf' not in content_type.lower() and not url.lower().endswith('.pdf'):
            return json.dumps({
                "status": "error",
                "url": url,
                "message": "URL does not appear to be a PDF file"
            }, indent=2)
        
        # Open PDF from bytes
        pdf_bytes = response.content
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Extract metadata
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", ""),
            "total_pages": len(doc)
        }
        
        # Extract text from pages
        full_text = ""
        pages_content = []
        
        for page_num in range(min(len(doc), max_pages)):
            page = doc[page_num]
            text = page.get_text()
            pages_content.append({
                "page": page_num + 1,
                "text": text[:3000]  # Limit per page
            })
            full_text += text + "\n\n"
        
        doc.close()
        
        # Truncate full text if too long
        if len(full_text) > 50000:
            full_text = full_text[:50000] + "\n\n... [truncated]"
        
        result = json.dumps({
            "status": "success",
            "url": url,
            "metadata": metadata,
            "full_text": full_text.strip(),
            "pages": pages_content
        }, indent=2)
        
        cache.set(cache_key, result)
        return result
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "url": url,
            "message": f"Failed to read PDF: {str(e)}"
        }, indent=2)


@mcp.tool()
def read_pdf_url(url: str, max_pages: int = 20) -> str:
    """
    Download and read a PDF document from a URL.
    
    Args:
        url: The URL of the PDF file
        max_pages: Maximum number of pages to read (default: 20)
    
    Returns:
        JSON with PDF metadata, full text, and page-by-page content
    """
    return _read_pdf_url_impl(url, max_pages)


# ============================================================================
# BATCH SEARCH (Multiple queries at once)
# ============================================================================

def _batch_search_impl(queries: list, max_results_per_query: int = 3) -> str:
    """Search multiple queries at once."""
    try:
        ddgs = DDGS()
        all_results = {}
        
        for query in queries[:10]:  # Limit to 10 queries
            try:
                results = list(ddgs.text(query, max_results=max_results_per_query))
                all_results[query] = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")
                    }
                    for r in results
                ]
            except Exception as e:
                all_results[query] = {"error": str(e)}
        
        return json.dumps({
            "status": "success",
            "total_queries": len(queries),
            "results": all_results
        }, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Batch search failed: {str(e)}"
        }, indent=2)


@mcp.tool()
def batch_search(queries: list, max_results_per_query: int = 3) -> str:
    """
    Search multiple queries at once for efficiency.
    
    Args:
        queries: List of search queries (max 10)
        max_results_per_query: Results per query (default: 3)
    
    Returns:
        JSON with results organized by query
    """
    return _batch_search_impl(queries, max_results_per_query)


# ============================================================================
# CACHE MANAGEMENT
# ============================================================================

@mcp.tool()
def clear_cache() -> str:
    """
    Clear the internal cache to force fresh data on next requests.
    
    Returns:
        Confirmation message
    """
    cache.clear()
    return json.dumps({
        "status": "success",
        "message": "Cache cleared successfully"
    }, indent=2)


if __name__ == "__main__":
    import sys
    
    # If run with --test flag, test the search function directly
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Testing search_web function...\n")
        
        # Test query - you can change this to test different searches
        test_query = sys.argv[2] if len(sys.argv) > 2 else "Python programming"
        
        print(f"Query: {test_query}")
        print("-" * 50)
        
        result = _search_web_impl(test_query, max_results=3)
        print(result)
    else:
        # Run the MCP server normally
        mcp.run()
