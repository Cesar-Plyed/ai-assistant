"""
Browser-related tools.

- get_installed_browsers / open_browser: detect and launch a real browser
  window (Brave, Chrome, Firefox, Edge, Chromium), same behavior as before
  but renamed and cleaned up.
- fetch_web_page_text: lets the assistant actually *read* a page's content
  (title + visible text + links) instead of only being able to open it, which
  is what "interacting better with the browser" mainly means for a text
  based assistant. Falls back gracefully if `requests`/`bs4` aren't installed.
"""

import platform
import shutil
import subprocess
import time

from core import desktop_manager
import config


def get_installed_browsers() -> dict[str, str]:
    """Detect available web browsers. Returns {alias: launch_command}."""
    system = platform.system().lower()
    browsers: dict[str, str] = {}

    if "linux" in system:
        candidates = {
            "brave": ["brave-browser", "brave", "flatpak run com.brave.Browser"],
            "chrome": ["google-chrome", "google-chrome-stable", "flatpak run com.google.Chrome"],
            "firefox": ["firefox", "flatpak run org.mozilla.firefox"],
            "edge": ["microsoft-edge", "flatpak run com.microsoft.Edge"],
            "chromium": ["chromium", "chromium-browser", "flatpak run org.chromium.Chromium"],
        }
        for name, commands in candidates.items():
            for cmd in commands:
                if cmd.startswith("flatpak run"):
                    flatpak_id = cmd.split()[-1]
                    check = subprocess.run(
                        f"flatpak info {flatpak_id}", shell=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    if check.returncode == 0:
                        browsers[name] = cmd
                        break
                elif shutil.which(cmd):
                    browsers[name] = cmd
                    break
    else:
        candidates_win = {"brave": "brave", "chrome": "chrome", "msedge": "msedge", "firefox": "firefox"}
        for name, cmd in candidates_win.items():
            if shutil.which(cmd):
                browsers[name] = cmd

    return browsers


def open_browser(url_or_query: str = "", browser: str = "auto") -> str:
    """
    Open an installed browser on a secondary virtual desktop, with an
    optional URL or search query.
    """
    system = platform.system().lower()
    available = get_installed_browsers()

    if not available:
        return "Error: no supported web browser was detected on this system."

    query = browser.lower().strip()
    if query in available:
        base_cmd = available[query]
    elif "brave" in available:
        base_cmd = available["brave"]
    else:
        base_cmd = list(available.values())[0]

    target_url = ""
    if url_or_query:
        if not (url_or_query.startswith("http://") or url_or_query.startswith("https://")):
            target_url = f"https://www.google.com/search?q={url_or_query.replace(' ', '+')}"
        else:
            target_url = url_or_query

    final_cmd = f'{base_cmd} "{target_url}"'.strip() if target_url else base_cmd

    try:
        desktop_manager.move_to_secondary_desktop()
        time.sleep(0.5)

        if "windows" in system:
            subprocess.Popen(f'start "" {final_cmd}', shell=True)
        else:
            subprocess.Popen(final_cmd, shell=True)

        time.sleep(1.5)
        desktop_manager.return_to_main_desktop()

        return f"Browser launched successfully (`{final_cmd}`)."
    except Exception as e:
        desktop_manager.return_to_main_desktop()
        return f"Error opening browser with command `{final_cmd}`: {e}"


def fetch_web_page_text(url: str, max_chars: int = 6000) -> str:
    """
    Fetch a web page and return its title, visible text, and top links, so
    the assistant can 'read' pages without opening a visible browser window.
    Controlled by settings.enable_browser_page_reading.
    """
    if not config.SETTINGS.get("enable_browser_page_reading", True):
        return "Page reading is disabled in Settings (enable_browser_page_reading)."

    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return (
            "Error: page reading requires the 'requests' and 'beautifulsoup4' packages. "
            "Install them with: pip install requests beautifulsoup4"
        )

    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (assistant)"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string.strip() if soup.title and soup.title.string else "(no title)"

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        truncated = len(text) > max_chars
        text = text[:max_chars]

        links = []
        for a in soup.find_all("a", href=True)[:15]:
            label = a.get_text(strip=True) or a["href"]
            links.append(f"- {label}: {a['href']}")

        result = f"Title: {title}\nURL: {url}\n\nText content:\n{text}"
        if truncated:
            result += "\n[... truncated ...]"
        if links:
            result += "\n\nTop links:\n" + "\n".join(links)
        return result

    except Exception as e:
        return f"Error fetching page '{url}': {e}"


def register(registry) -> None:
    registry.register(
        name="open_browser",
        description="Open an installed web browser (Brave, Chrome, Firefox, Edge, Chromium), optionally to a URL or search query.",
        parameters={
            "type": "object",
            "properties": {
                "url_or_query": {"type": "string", "description": "URL to open or text to search for (optional)."},
                "browser": {"type": "string", "description": "Preferred browser: 'brave', 'chrome', 'firefox', 'auto'."},
            },
        },
        func=open_browser,
    )
    registry.register(
        name="fetch_web_page_text",
        description="Fetch a web page's title, visible text, and top links without opening a visible browser window. Use this to read page content.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The page URL to fetch."},
                "max_chars": {"type": "integer", "description": "Maximum characters of text to return."},
            },
            "required": ["url"],
        },
        func=fetch_web_page_text,
    )
