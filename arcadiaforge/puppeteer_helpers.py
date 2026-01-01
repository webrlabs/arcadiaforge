"""
Puppeteer Browser Automation Helpers
====================================

MCP server providing helper tools for browser automation that work around
Puppeteer MCP selector limitations. The :has-text() pseudo-selector is NOT
supported by Puppeteer - these tools provide JavaScript alternatives.

Usage Pattern:
    1. Call helper tool to get JavaScript code
    2. Execute the JavaScript via puppeteer_evaluate

Example:
    result = browser_click_text("Delete")
    puppeteer_evaluate(result["script"])
"""

from pathlib import Path
from mcp.server.fastmcp import FastMCP


# Create the MCP server
mcp = FastMCP("puppeteer-helpers")


# Tool name constants for registration
PUPPETEER_HELPER_TOOLS = [
    "mcp__puppeteer-helpers__browser_click_text",
    "mcp__puppeteer-helpers__browser_find_elements",
    "mcp__puppeteer-helpers__browser_wait_and_click",
    "mcp__puppeteer-helpers__browser_fill_by_label",
    "mcp__puppeteer-helpers__browser_get_text",
    "mcp__puppeteer-helpers__browser_table_data",
]


def _escape_js_string(text: str) -> str:
    """Escape a string for safe use in JavaScript."""
    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


@mcp.tool()
def browser_click_text(text: str, element_type: str = "button,a,[role='button']") -> dict:
    """
    Generate JavaScript to click an element containing specific text.

    Use this instead of 'button:has-text("Delete")' which is NOT supported.

    Args:
        text: The text content to search for (case-sensitive partial match)
        element_type: CSS selector for element types to search (default: "button,a,[role='button']")

    Returns:
        Dict with JavaScript code to execute via puppeteer_evaluate

    Example:
        result = browser_click_text("Delete")
        # Then call: puppeteer_evaluate(result["script"])
    """
    escaped_text = _escape_js_string(text)
    escaped_selector = _escape_js_string(element_type)

    script = f"""
(() => {{
    const elements = Array.from(document.querySelectorAll('{escaped_selector}'));
    const target = elements.find(el => el.textContent.includes('{escaped_text}'));
    if (target) {{
        target.click();
        return {{
            success: true,
            clicked: target.tagName,
            text: target.textContent.trim().substring(0, 100)
        }};
    }}
    return {{
        success: false,
        error: 'Element with text "{escaped_text}" not found',
        searched: elements.length + ' elements'
    }};
}})();
"""
    return {
        "script": script.strip(),
        "description": f"Click element containing '{text}'"
    }


@mcp.tool()
def browser_find_elements(selector: str, text_filter: str = None, limit: int = 20) -> dict:
    """
    Generate JavaScript to find elements matching selector and optional text filter.

    Use this to locate elements before clicking or interacting.

    Args:
        selector: CSS selector (e.g., "button", "a", ".class-name")
        text_filter: Optional text to filter elements by (partial match)
        limit: Maximum number of elements to return (default: 20)

    Returns:
        Dict with JavaScript code to execute via puppeteer_evaluate
    """
    escaped_selector = _escape_js_string(selector)

    if text_filter:
        escaped_filter = _escape_js_string(text_filter)
        script = f"""
(() => {{
    const elements = Array.from(document.querySelectorAll('{escaped_selector}'));
    const filtered = elements.filter(el => el.textContent.includes('{escaped_filter}'));
    return filtered.slice(0, {limit}).map((el, i) => ({{
        index: i,
        tag: el.tagName,
        text: el.textContent.trim().substring(0, 100),
        classes: el.className,
        id: el.id || null,
        href: el.href || null,
        type: el.type || null
    }}));
}})();
"""
    else:
        script = f"""
(() => {{
    const elements = Array.from(document.querySelectorAll('{escaped_selector}'));
    return elements.slice(0, {limit}).map((el, i) => ({{
        index: i,
        tag: el.tagName,
        text: el.textContent.trim().substring(0, 100),
        classes: el.className,
        id: el.id || null,
        href: el.href || null,
        type: el.type || null
    }}));
}})();
"""
    return {
        "script": script.strip(),
        "description": f"Find elements matching '{selector}'" + (f" with text '{text_filter}'" if text_filter else "")
    }


@mcp.tool()
def browser_wait_and_click(text: str, timeout_ms: int = 5000, element_type: str = "button,a,[role='button']") -> dict:
    """
    Generate JavaScript to wait for an element with text and click it.

    Useful for elements that appear after async operations.

    Args:
        text: Text to search for
        timeout_ms: Maximum time to wait in milliseconds (default: 5000)
        element_type: CSS selector for element types to search

    Returns:
        Dict with JavaScript code to execute via puppeteer_evaluate
    """
    escaped_text = _escape_js_string(text)
    escaped_selector = _escape_js_string(element_type)

    script = f"""
(async () => {{
    const startTime = Date.now();
    while (Date.now() - startTime < {timeout_ms}) {{
        const elements = Array.from(document.querySelectorAll('{escaped_selector}'));
        const target = elements.find(el => el.textContent.includes('{escaped_text}'));
        if (target) {{
            target.click();
            return {{
                success: true,
                waited: Date.now() - startTime,
                clicked: target.tagName
            }};
        }}
        await new Promise(r => setTimeout(r, 100));
    }}
    return {{
        success: false,
        error: 'Timeout waiting for element with text "{escaped_text}"',
        waited: {timeout_ms}
    }};
}})();
"""
    return {
        "script": script.strip(),
        "description": f"Wait for and click element containing '{text}'"
    }


@mcp.tool()
def browser_fill_by_label(label_text: str, value: str) -> dict:
    """
    Generate JavaScript to fill an input by its label text.

    Finds input associated with a label containing the text, then fills it.

    Args:
        label_text: The label text (or placeholder text) for the input
        value: The value to fill into the input

    Returns:
        Dict with JavaScript code to execute via puppeteer_evaluate
    """
    escaped_label = _escape_js_string(label_text)
    escaped_value = _escape_js_string(value)

    script = f"""
(() => {{
    // Try to find by label text
    const labels = Array.from(document.querySelectorAll('label'));
    const label = labels.find(l => l.textContent.includes('{escaped_label}'));

    let input = null;

    if (label) {{
        // Check for 'for' attribute
        if (label.htmlFor) {{
            input = document.getElementById(label.htmlFor);
        }}
        // Check for nested input
        if (!input) {{
            input = label.querySelector('input, textarea, select');
        }}
        // Check for adjacent input
        if (!input) {{
            input = label.nextElementSibling;
            if (input && !['INPUT', 'TEXTAREA', 'SELECT'].includes(input.tagName)) {{
                input = null;
            }}
        }}
    }}

    // Fallback: find by placeholder or name
    if (!input) {{
        input = document.querySelector(
            `input[placeholder*="{escaped_label}" i],` +
            `input[name*="{escaped_label}" i],` +
            `textarea[placeholder*="{escaped_label}" i],` +
            `textarea[name*="{escaped_label}" i]`
        );
    }}

    // Fallback: find by aria-label
    if (!input) {{
        input = document.querySelector(
            `input[aria-label*="{escaped_label}" i],` +
            `textarea[aria-label*="{escaped_label}" i]`
        );
    }}

    if (input) {{
        input.focus();
        input.value = '{escaped_value}';
        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return {{
            success: true,
            element: input.tagName,
            id: input.id || null,
            name: input.name || null
        }};
    }}

    return {{
        success: false,
        error: 'Input for "{escaped_label}" not found'
    }};
}})();
"""
    return {
        "script": script.strip(),
        "description": f"Fill input labeled '{label_text}' with value"
    }


@mcp.tool()
def browser_get_text(selector: str) -> dict:
    """
    Generate JavaScript to get text content from elements.

    Args:
        selector: CSS selector for elements

    Returns:
        Dict with JavaScript code to execute via puppeteer_evaluate
    """
    escaped_selector = _escape_js_string(selector)

    script = f"""
(() => {{
    const elements = Array.from(document.querySelectorAll('{escaped_selector}'));
    return {{
        count: elements.length,
        texts: elements.slice(0, 50).map(el => el.textContent.trim())
    }};
}})();
"""
    return {
        "script": script.strip(),
        "description": f"Get text content from '{selector}'"
    }


@mcp.tool()
def browser_table_data(table_selector: str = "table") -> dict:
    """
    Generate JavaScript to extract data from an HTML table.

    Useful for verifying table contents in tests.

    Args:
        table_selector: CSS selector for the table (default: "table")

    Returns:
        Dict with JavaScript code to extract table data
    """
    escaped_selector = _escape_js_string(table_selector)

    script = f"""
(() => {{
    const table = document.querySelector('{escaped_selector}');
    if (!table) {{
        return {{ success: false, error: 'Table not found' }};
    }}

    const headers = Array.from(table.querySelectorAll('th'))
        .map(th => th.textContent.trim());

    const rows = Array.from(table.querySelectorAll('tbody tr'))
        .map(tr => {{
            const cells = Array.from(tr.querySelectorAll('td'))
                .map(td => td.textContent.trim());
            return cells;
        }});

    return {{
        success: true,
        headers: headers,
        rows: rows,
        rowCount: rows.length
    }};
}})();
"""
    return {
        "script": script.strip(),
        "description": f"Extract data from table '{table_selector}'"
    }


def create_puppeteer_helpers_server(project_dir: Path) -> dict:
    """
    Create the puppeteer helpers MCP server configuration.

    Args:
        project_dir: Project directory path

    Returns:
        Server configuration dict for claude-code-sdk
    """
    return {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "arcadiaforge.puppeteer_helpers"],
        "cwd": str(project_dir),
    }


if __name__ == "__main__":
    mcp.run()
