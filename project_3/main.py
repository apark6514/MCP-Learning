"""
project_3: A file explorer MCP server.

WHAT THIS FILE IS
-----------------
This is an MCP *server* that gives an LLM safe, read-only access to the
`files/` folder that sits next to this script. That folder holds a mix of
PDFs, PNGs, .txt files and CSVs.

It exposes four TOOLS:

    list_files()             -> what files exist?
    read_file(path)          -> what is inside one file?
    search_files(query)      -> which files mention some text?
    get_file_metadata(path)  -> size, dates, page count, image size, etc.

plus one RESOURCE and two PROMPTS, so you can see all three MCP building
blocks side by side (read the big comment below for how they differ).

HOW TO RUN IT
-------------
    python -m venv .venv
    .venv/Scripts/python.exe -m pip install "mcp[cli]" pypdf pillow
    .venv/Scripts/python.exe main.py      # starts on stdio and just waits

Normally the host (Claude Code) launches it for you, using the "files"
entry in .mcp.json at the repo root.

Libraries used:
    - mcp     : the official MCP Python SDK (v2, which provides MCPServer)
    - pypdf   : pulls text, page counts and metadata out of PDFs
    - pillow  : reads image sizes / formats from PNGs
"""

# =============================================================================
# RESOURCES vs TOOLS vs PROMPTS
# =============================================================================
#
# An MCP server can offer three different kinds of things to a client. They
# look similar in code (each is just a decorated Python function), but they
# differ in WHO decides to use them and WHAT they are for.
#
# 1. TOOLS  (@mcp.tool)  -- "model-controlled" ACTIONS
#    ---------------------------------------------------
#    - A tool is a function the LLM can decide to call by itself while it is
#      working on a task. The host shows the model each tool's name,
#      description (the docstring) and input schema (built from the type
#      hints). The model then says "call read_file with path=weather.csv", the
#      host forwards that to this server, and our return value goes back to
#      the model.
#    - Tools take arguments and can do anything: compute, search, call an
#      API, write to a database. Because they can have side effects, hosts
#      usually ask the user for permission before running them.
#    - Protocol messages: "tools/list" and "tools/call".
#    - Think of tools as VERBS: "search", "read", "send", "calculate".
#
# 2. RESOURCES  (@mcp.resource)  -- "application-controlled" DATA
#    -------------------------------------------------------------
#    - A resource is a piece of read-only data identified by a URI, such as
#      "files://index" or "file:///home/me/notes.txt". It is like a GET
#      request: it returns content and should NOT change anything.
#    - The host application (or the user) decides when to load a resource
#      and put it into the model's context. For example, in Claude Code you
#      can type @ and pick a resource to attach it to your message. The model
#      does not "call" a resource the way it calls a tool.
#    - Resources can be fixed ("files://index") or templated with parameters
#      in the URI ("files://{name}"), which the client fills in.
#    - Protocol messages: "resources/list", "resources/templates/list" and
#      "resources/read". Clients may also subscribe to changes.
#    - Think of resources as NOUNS: "this document", "that database row".
#
# 3. PROMPTS  (@mcp.prompt)  -- "user-controlled" TEMPLATES
#    -------------------------------------------------------
#    - A prompt is a reusable, pre-written message (or conversation) that the
#      server offers to the USER. The user picks it explicitly, usually from a
#      menu or as a slash command (in Claude Code, MCP prompts show up as
#      /mcp__<server>__<prompt>).
#    - Prompts can take arguments (e.g. which file to summarize). The server
#      fills them into a template and returns a list of messages; the host
#      then sends those messages to the model as if the user had typed them.
#    - Prompts do not DO anything themselves. They package up "the best way
#      to ask for X" so users do not have to write it every time, and they
#      often tell the model which tools to use.
#    - Protocol messages: "prompts/list" and "prompts/get".
#    - Think of prompts as RECIPES or saved instructions.
#
# Quick summary:
#
#     |            | Who triggers it?      | Purpose                   | Side effects? |
#     |------------|-----------------------|---------------------------|---------------|
#     | Tool       | the model             | perform an action         | allowed       |
#     | Resource   | the app / the user    | provide context data      | no (read-only)|
#     | Prompt     | the user              | start a templated request | no            |
#
# In THIS server, all four file operations are tools because the user asked
# for them that way, and because it lets the model explore the folder on its
# own. The same data is ALSO exposed as resources so you can see the
# difference, and two prompts show how a user-facing template can steer the
# model toward using the tools.
# =============================================================================

import csv                       # parse CSV files to count rows/columns
import mimetypes                 # guess a MIME type from a file extension
from datetime import datetime, timezone
from pathlib import Path         # object-oriented, cross-platform file paths

from PIL import Image as PILImage   # Pillow: renamed so it doesn't clash with MCP's Image
from pypdf import PdfReader         # read text/metadata from PDFs

# MCPServer is the high-level server class in MCP SDK v2 (v1 called it FastMCP).
# `Image` is MCP's helper for returning a picture to the model as image content.
from mcp.server.mcpserver import Image, MCPServer

# ToolError / ResourceError are how we report a PROBLEM THE CALLER CAN FIX
# (bad path, unsupported file type, ...). Their message is sent to the model.
# Any OTHER exception is treated as a server crash: the model only sees a
# generic "Error executing tool X" and the details stay in the server's log.
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

# Create the server. "files" is the name the host shows for this server.
mcp = MCPServer("files")

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

# The folder we expose. Path(__file__).parent is the folder containing main.py,
# so this works no matter which directory the host starts us from.
FILES_DIR = (Path(__file__).parent / "files").resolve()

# The file types this server understands, grouped by how we read them.
TEXT_EXTENSIONS = {".txt", ".csv"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | IMAGE_EXTENSIONS

# Safety limit so one huge file can't flood the model's context window.
MAX_TEXT_CHARS = 50_000


# -----------------------------------------------------------------------------
# HELPER FUNCTIONS (not exposed over MCP, just used by the tools below)
# -----------------------------------------------------------------------------


def _resolve_safe_path(path: str) -> Path:
    """Turn a user/model supplied path into an absolute path inside FILES_DIR.

    SECURITY: the model chooses the `path` argument, so we must not trust it.
    Something like "../../Windows/system.ini" or an absolute path would
    otherwise let it read any file on the computer. We resolve the full path
    (which collapses any ".." parts) and then check that it is still inside
    FILES_DIR. This check is called "path traversal protection".
    """
    candidate = (FILES_DIR / path).resolve()

    # is_relative_to() is True only if candidate lives somewhere under FILES_DIR.
    if not candidate.is_relative_to(FILES_DIR):
        raise ToolError(f"Access denied: '{path}' is outside the files folder.")
    if not candidate.exists():
        raise ToolError(f"No such file: '{path}'. Use list_files() to see what exists.")
    if not candidate.is_file():
        raise ToolError(f"'{path}' is a directory, not a file.")
    return candidate


def _relative(path: Path) -> str:
    """Return a path relative to FILES_DIR with forward slashes (e.g. 'sub/a.txt').

    We always show the model relative paths, so it can pass them straight
    back into read_file() / get_file_metadata().
    """
    return path.relative_to(FILES_DIR).as_posix()


def _iter_files() -> list[Path]:
    """Return every supported file under FILES_DIR (including subfolders), sorted."""
    # rglob("*") walks the folder recursively. We keep only real files whose
    # extension we know how to handle, and skip hidden files like ".DS_Store".
    return sorted(
        p
        for p in FILES_DIR.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and not p.name.startswith(".")
    )


def _read_text(path: Path) -> str:
    """Read a .txt or .csv file as text.

    errors="replace" means any bytes that are not valid UTF-8 become a
    placeholder character instead of raising an error.
    """
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf_text(path: Path) -> str:
    """Extract the text from every page of a PDF.

    PDFs store positioned glyphs, not plain text, so extraction is a
    best-effort guess. Scanned PDFs (pictures of pages) have no text layer
    at all and will come back empty.
    """
    reader = PdfReader(path)
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        # extract_text() can return None for empty pages, so fall back to "".
        text = page.extract_text() or ""
        pages.append(f"--- Page {number} ---\n{text.strip()}")
    return "\n\n".join(pages)


def _searchable_text(path: Path) -> str | None:
    """Return the text content of a file for searching, or None for images."""
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return _read_text(path)
    if suffix in PDF_EXTENSIONS:
        return _read_pdf_text(path)
    return None  # PNGs have no text we can search (no OCR here)


def _truncate(text: str) -> str:
    """Cut text down to MAX_TEXT_CHARS and say so, so the model knows it's partial."""
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS] + f"\n\n[... truncated, showing first {MAX_TEXT_CHARS} characters ...]"


def _mime_type(path: Path) -> str:
    """Return the file's MIME type, e.g. "application/pdf" or "image/png"."""
    # mimetypes asks the operating system, and Windows maps .csv to
    # "application/vnd.ms-excel" (because Excel opens CSVs). Use the
    # standard "text/csv" instead so the answer is the same on every OS.
    if path.suffix.lower() == ".csv":
        return "text/csv"
    # guess_type returns (mime, encoding); we only need the MIME type.
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _iso(timestamp: float) -> str:
    """Convert a Unix timestamp (seconds since 1970) to a readable ISO 8601 string."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")


# -----------------------------------------------------------------------------
# TOOLS
# -----------------------------------------------------------------------------
# Reminder of how @mcp.tool() works:
#   - function name -> tool name
#   - docstring     -> tool description (the model reads this to decide WHEN
#                      and HOW to use the tool, so it should be specific)
#   - type hints    -> JSON input schema
#   - return value  -> sent back to the model (str, dict, list, Image, ...)
#   - exceptions    -> caught by MCPServer and returned as a tool error
#                      (isError: true) instead of crashing the server.
#                      Raise ToolError for errors the model should read.


@mcp.tool()
def list_files() -> list[dict]:
    """List every file in the files folder.

    Returns one entry per file with its relative path (use this path with
    the other tools), its type (txt, csv, pdf or png) and its size in bytes.
    Call this first if you don't know what files are available.
    """
    # Returning a list of dicts gives the model neatly labeled, structured
    # data instead of a blob of text it has to parse.
    return [
        {
            "path": _relative(p),
            "type": p.suffix.lower().lstrip("."),
            "size_bytes": p.stat().st_size,
        }
        for p in _iter_files()
    ]


# structured_output=False: this tool can return EITHER text or an image.
# MCPServer normally tries to build an output schema from the return type
# hint; turning that off lets us return different content types freely.
@mcp.tool(structured_output=False)
def read_file(path: str) -> str | Image:
    """Read the contents of one file from the files folder.

    - .txt and .csv files are returned as plain text.
    - .pdf files are returned as extracted text, split by page.
    - .png files are returned as an image so you can look at them.

    Args:
        path: The file's path relative to the files folder, exactly as shown
              by list_files() (for example "weather.csv").
    """
    file_path = _resolve_safe_path(path)
    suffix = file_path.suffix.lower()

    if suffix in TEXT_EXTENSIONS:
        return _truncate(_read_text(file_path))

    if suffix in PDF_EXTENSIONS:
        text = _read_pdf_text(file_path)
        return _truncate(text) if text.strip() else "(This PDF has no extractable text.)"

    if suffix in IMAGE_EXTENSIONS:
        # MCP's Image helper reads the bytes, base64-encodes them and sends
        # them as an "image" content block with the right MIME type. Models
        # that support vision can then actually see the picture.
        return Image(path=file_path)

    raise ToolError(f"Unsupported file type '{suffix}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}")


@mcp.tool()
def search_files(query: str) -> list[dict]:
    """Search all files for a piece of text (case-insensitive).

    Matches against both file NAMES and file CONTENTS. Contents are searched
    for .txt, .csv and .pdf files; .png files are only matched by name since
    their contents are pixels, not text.

    Returns each matching file with the lines that contain the query
    (up to 5 per file), so you can decide which file to read in full.

    Args:
        query: The text to look for, e.g. "engineering" or "invoice".
    """
    needle = query.strip().lower()
    if not needle:
        raise ToolError("Query must not be empty.")

    MAX_LINES_PER_FILE = 5
    results = []

    for p in _iter_files():
        name_match = needle in p.name.lower()
        matching_lines = []

        # Look inside the file if it has text we can search.
        text = _searchable_text(p)
        if text is not None:
            # enumerate(..., start=1) gives human-friendly line numbers.
            for line_no, line in enumerate(text.splitlines(), start=1):
                if needle in line.lower():
                    matching_lines.append({"line": line_no, "text": line.strip()})

        # Only include files that matched by name or by content.
        if name_match or matching_lines:
            results.append(
                {
                    "path": _relative(p),
                    "name_match": name_match,
                    "match_count": len(matching_lines),
                    # Only send a few lines to keep the response small.
                    "matches": matching_lines[:MAX_LINES_PER_FILE],
                }
            )

    return results


@mcp.tool()
def get_file_metadata(path: str) -> dict:
    """Get details about a file without reading all of its contents.

    Always includes: name, path, type, MIME type, size, and created/modified
    times. Also includes type-specific details:
      - .txt : line, word and character counts
      - .csv : column names and number of data rows
      - .pdf : page count and document info (title, author, ...)
      - .png : width, height and color mode

    Args:
        path: The file's path relative to the files folder (see list_files()).
    """
    file_path = _resolve_safe_path(path)
    stat = file_path.stat()  # OS-level info: size, timestamps, etc.
    suffix = file_path.suffix.lower()

    # Fields every file gets.
    metadata = {
        "name": file_path.name,
        "path": _relative(file_path),
        "type": suffix.lstrip("."),
        "mime_type": _mime_type(file_path),
        "size_bytes": stat.st_size,
        # Note: on Windows st_ctime is the creation time; on Linux/macOS it
        # is the last metadata change time.
        "created": _iso(stat.st_ctime),
        "modified": _iso(stat.st_mtime),
    }

    # Extra fields depending on the kind of file.
    if suffix == ".txt":
        text = _read_text(file_path)
        metadata.update(
            lines=len(text.splitlines()),
            words=len(text.split()),
            characters=len(text),
        )

    elif suffix == ".csv":
        # newline="" is what the csv module expects when opening files.
        with file_path.open(newline="", encoding="utf-8", errors="replace") as f:
            rows = list(csv.reader(f))
        header = rows[0] if rows else []
        metadata.update(columns=header, row_count=max(len(rows) - 1, 0))  # minus header row

    elif suffix == ".pdf":
        reader = PdfReader(file_path)
        info = reader.metadata or {}
        metadata.update(
            page_count=len(reader.pages),
            # PDF metadata keys look like "/Title"; strip the slash and make
            # sure every value is a plain string so it is valid JSON.
            document_info={key.lstrip("/"): str(value) for key, value in info.items()},
        )

    elif suffix == ".png":
        # Opening with Pillow only reads the header, so this is cheap.
        with PILImage.open(file_path) as img:
            metadata.update(width=img.width, height=img.height, color_mode=img.mode)

    return metadata


# -----------------------------------------------------------------------------
# RESOURCES
# -----------------------------------------------------------------------------
# These expose the same data as read-only resources. The host/user attaches
# them to the conversation; the model does not call them like tools.


@mcp.resource("files://index", mime_type="text/plain")
def files_index() -> str:
    """A plain-text index of every file in the files folder."""
    return "\n".join(_relative(p) for p in _iter_files())


# A resource TEMPLATE: "{name}" is a parameter the client fills in, so
# "files://weather.csv" returns the text of weather.csv. We limit this to
# text-based files to keep the example simple.
@mcp.resource("files://{name}", mime_type="text/plain")
def file_text(name: str) -> str:
    """The text content of a .txt, .csv or .pdf file in the files folder."""
    # _resolve_safe_path raises ToolError; resources report problems with
    # ResourceError instead, so convert it.
    try:
        file_path = _resolve_safe_path(name)
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc
    text = _searchable_text(file_path)
    if text is None:
        raise ResourceError("Only .txt, .csv and .pdf files are available as text resources.")
    return _truncate(text)


# -----------------------------------------------------------------------------
# PROMPTS
# -----------------------------------------------------------------------------
# @mcp.prompt() registers a user-selectable template. The function's
# arguments become the prompt's arguments, and whatever string it returns is
# sent to the model as a user message. In Claude Code these appear as
# slash commands: /mcp__files__summarize_file and /mcp__files__find_and_explain.


@mcp.prompt()
def summarize_file(path: str) -> str:
    """Summarize a single file from the files folder."""
    # Note the prompt tells the model WHICH TOOLS to use. That is a common
    # pattern: the prompt is the user-facing recipe, the tools do the work.
    return (
        f"Please summarize the file '{path}' from the files folder.\n\n"
        f"1. Call get_file_metadata('{path}') to learn what kind of file it is.\n"
        f"2. Call read_file('{path}') to see its contents.\n"
        "3. Write a short summary tailored to the file type:\n"
        "   - text/PDF: the main points in 3-5 bullets\n"
        "   - CSV: what each column means, the number of rows, and any notable trends\n"
        "   - image: what the image shows\n"
        "Finish with one sentence on what this file is probably used for."
    )


@mcp.prompt()
def find_and_explain(topic: str) -> str:
    """Find every file related to a topic and explain what each one says about it."""
    return (
        f"I want to know everything the files folder says about '{topic}'.\n\n"
        f"Use search_files('{topic}') to find relevant files (try a couple of "
        "related keywords too if the first search finds little). Read the most "
        "relevant matches with read_file, then give me a combined answer that "
        "cites which file each fact came from."
    )


# -----------------------------------------------------------------------------
# ENTRY POINT
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # stdio transport: the host talks to us over stdin/stdout.
    # Never print() to stdout in a stdio server; it would corrupt the
    # JSON-RPC messages. Use stderr for any debug output.
    mcp.run(transport="stdio")
