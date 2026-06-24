
import requests

from app.config import muse_settings


muse_name = muse_settings.get_section('muse_config').get('MUSE_NAME')

def search_web(query):
    serper_url = "https://google.serper.dev/search"
    serper_api_key = muse_settings.get_section("api_keys").get("SERPER_API_KEY")

    payload = {
        "q": query
    }
    headers = {
        'X-API-KEY': serper_api_key,
        'Content-Type': 'application/json'
    }

    response = requests.post(serper_url, headers=headers, json=payload)

    return f"[Your web search results for query: {query}]\n{response.text}"

def search_news(query):
    serper_url = "https://google.serper.dev/news"
    serper_api_key = muse_settings.get_section("api_keys").get("SERPER_API_KEY")

    payload = {
        "q": query
    }
    headers = {
        'X-API-KEY': serper_api_key,
        'Content-Type': 'application/json'
    }

    response = requests.post(serper_url, headers=headers, json=payload)

    return f"[Your news search results for query: {query}]\n{response.text}"

def search_images(query):
    serper_url = "https://google.serper.dev/images"
    serper_api_key = muse_settings.get_section("api_keys").get("SERPER_API_KEY")

    payload = {"q": query}
    headers = {
        "X-API-KEY": serper_api_key,
        "Content-Type": "application/json",
    }

    response = requests.post(serper_url, headers=headers, json=payload)
    response.raise_for_status()

    return {
        "tool_output": f"[Your image search results for query: {query}]\n{response.text}",
        "attachments": [],
    }


def read_webpage(url):
    serper_url = "https://scrape.serper.dev"
    serper_api_key = muse_settings.get_section("api_keys").get("SERPER_API_KEY")

    payload = {
        "url": url
    }
    headers = {
        'X-API-KEY': serper_api_key,
        'Content-Type': 'application/json'
    }

    response = requests.post(serper_url, headers=headers, json=payload)

    return f"[Your requested webpage content from: {url}]\n{response.text}"


TOOL_REGISTRY = {
    "search_web": {
        "schema": {
            "type": "function",
            "name": "search_web",
            "description": "Search the web for current information or to find relevant pages when you do not already have a specific URL. Use this first when the user asks about recent events, facts that may have changed, or when you need to discover a webpage before reading it. Do not use this tool for image searches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search engine query string describing what to look for."
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is searching the web…",
            "error": "Web search failed."
        },
        "handler": search_web,
    },
    "search_news": {
        "schema": {
            "type": "function",
            "name": "search_news",
            "description": "Search recent news coverage across news sources when you need current reporting on events, developments, or public stories. Use this for headlines, breaking news, ongoing situations, or to see how a topic is being covered right now—not for general web discovery or finding a specific webpage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search engine query string describing what to look for."
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is searching the news…",
            "error": "News search failed."
        },
        "handler": search_news,
    },
    "search_images": {
        "schema": {
            "type": "function",
            "name": "search_images",
            "description": "Search for images relevant to the current conversation to illustrate, compare, inspire, visually answer the user’s request, or simply share something the user or assistant would enjoy seeing. Use this when showing is better than describing, when the user explicitly wants to see something, or when a fitting image would add delight or atmosphere to the exchange. Do not use `search_web` when the goal is to find images. You may embed appropriate image results directly into your response using markdown. When sharing an image, you may include attribution or a source link when useful, but you do not need to display the full raw URL unless it serves a debugging or provenance purpose. Prefer elegant presentation, such as a short “Source” link or site name, over long exposed URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search engine query string describing what to look for."
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is searching for images…",
            "error": "Image search failed."
        },
        "handler": search_images,
    },
    "read_webpage": {
        "schema": {
            "type": "function",
            "name": "read_webpage",
            "description": "Fetch and read the text content of a specific webpage when you already have a URL. Use this to inspect the contents of a page, article, or documentation link. Do not use it for general discovery; use search_web first if you need to find the right page. After reading a webpage, consider whether to call `search_memory` in semantic mode using focused terms from the page content. This can recover prior conversation context that the user's original message would not have triggered. Use this especially for analysis, project work, job/application help, recommendations, or personalized responses; avoid it for simple summaries or one-off factual checks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL of the webpage to read."
                    }
                },
                "required": ["url"],
                "additionalProperties": False
            },
            "strict": True
        },
        "ui": {
            "start": f"{muse_name} is reading a webpage…",
            "error": "Couldn’t read that webpage."
        },
        "handler": read_webpage,
    },
}

def register_tools(registry):
    for name, handler in TOOL_REGISTRY.items():
        print(f"Registering Web Tool: {name}")
        registry.register(name, handler)