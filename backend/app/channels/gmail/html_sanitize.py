"""HTML detection, plain-text conversion, and allowlist sanitization for inbound emails."""

import html
import re
from html.parser import HTMLParser

from inscriptis import get_text

from app.channels.text_clean import clean_text

MAX_HTML_CHARS = 200_000

_HTML_DOC_HINT = re.compile(
    r"^\s*(?:<!doctype\s+html\b|<html\b|<head\b|<body\b|<style\b|<table\b|<div\b|<p\b[^>]*>)",
    re.IGNORECASE,
)
_HTML_TAG_COUNT = re.compile(r"</?(?:html|head|body|style|table|tr|td|div|span|p|br|img|font|strong)\b", re.IGNORECASE)

_DROP_WITH_CONTENT = frozenset(
    {"script", "iframe", "object", "embed", "applet", "form", "input", "button", "textarea", "select", "svg", "math"}
)
_SKIP_TAGS_ONLY = frozenset({"html", "head", "body", "meta", "link", "base", "title"})
_VOID_TAGS = frozenset({"br", "hr", "img", "wbr"})
_ALLOWED_TAGS = frozenset(
    {
        "a",
        "abbr",
        "b",
        "blockquote",
        "br",
        "caption",
        "center",
        "code",
        "col",
        "colgroup",
        "dd",
        "del",
        "div",
        "dl",
        "dt",
        "em",
        "font",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "ins",
        "li",
        "ol",
        "p",
        "pre",
        "q",
        "s",
        "small",
        "span",
        "strong",
        "style",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
        "wbr",
    }
)
_ALLOWED_ATTRS = frozenset(
    {
        "align",
        "alt",
        "bgcolor",
        "border",
        "cellpadding",
        "cellspacing",
        "class",
        "color",
        "colspan",
        "dir",
        "face",
        "height",
        "href",
        "id",
        "lang",
        "rowspan",
        "size",
        "src",
        "style",
        "title",
        "valign",
        "width",
    }
)
_SAFE_LINK_SCHEME = re.compile(r"^(?:https?://|mailto:|tel:|#)", re.IGNORECASE)
_SAFE_IMG_SRC = re.compile(
    r"^(?:https?://|data:image/(?:png|jpeg|jpg|gif|webp);base64,[a-z0-9+/=\s]+$)",
    re.IGNORECASE,
)
_DANGEROUS_CSS = re.compile(
    r"(?:expression\s*\(|javascript\s*:|vbscript\s*:|@import\b|behavior\s*:|-moz-binding)", re.I
)
_CSS_COMMENT = re.compile(r"<!--|-->")


def looks_like_html(text: str) -> bool:
    """True when text appears to be raw HTML markup (including emails that wrap HTML inside text/plain)."""
    if not text or "<" not in text:
        return False
    if _HTML_DOC_HINT.match(text):
        return True
    return len(_HTML_TAG_COUNT.findall(text[:4000])) >= 4


def html_to_clean_text(raw_html: str) -> str:
    """Extract clean Postgres-safe plain text from HTML."""
    plain = get_text(raw_html)
    return "\n".join(line.rstrip() for line in clean_text(plain).split("\n")).strip()


def _clean_css(css: str) -> str:
    stripped = _CSS_COMMENT.sub("", clean_text(css))
    return _DANGEROUS_CSS.sub("/* blocked */", stripped)


class _EmailHtmlSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self._drop_depth = 0
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._drop_depth > 0:
            if tag not in _VOID_TAGS:
                self._drop_depth += 1
            return
        if tag in _DROP_WITH_CONTENT:
            if tag not in _VOID_TAGS:
                self._drop_depth = 1
            return
        if tag in _SKIP_TAGS_ONLY or tag not in _ALLOWED_TAGS:
            return
        if tag == "style":
            self._in_style = True
            self.parts.append("<style>")
            return

        rendered_attrs: list[str] = []
        has_href = False
        for raw_name, raw_val in attrs:
            name = raw_name.lower().strip()
            if not name or name.startswith("on") or name not in _ALLOWED_ATTRS:
                continue
            val = clean_text(raw_val or "").strip()
            if name == "href":
                if not _SAFE_LINK_SCHEME.match(val):
                    continue
                has_href = True
            elif name == "src":
                if not _SAFE_IMG_SRC.match(val):
                    continue
            elif name == "style":
                if _DANGEROUS_CSS.search(val):
                    continue
            rendered_attrs.append(f'{name}="{html.escape(val, quote=True)}"')

        if tag == "a" and has_href:
            rendered_attrs.extend(['target="_blank"', 'rel="noopener noreferrer"'])
        if tag == "img" and not any(a.startswith("src=") for a in rendered_attrs):
            return
        attr_str = (" " + " ".join(rendered_attrs)) if rendered_attrs else ""
        self.parts.append(f"<{tag}{attr_str}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._drop_depth > 0:
            if tag not in _VOID_TAGS:
                self._drop_depth -= 1
            return
        if tag == "style":
            if self._in_style:
                self._in_style = False
                self.parts.append("</style>")
            return
        if tag in _SKIP_TAGS_ONLY or tag in _VOID_TAGS or tag not in _ALLOWED_TAGS:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._drop_depth > 0:
            return
        if self._in_style:
            self.parts.append(_clean_css(data))
        else:
            self.parts.append(html.escape(clean_text(data), quote=False))

    def handle_entityref(self, name: str) -> None:
        if self._drop_depth == 0 and not self._in_style:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._drop_depth == 0 and not self._in_style:
            self.parts.append(f"&#{name};")


def sanitize_email_html(raw_html: str | None) -> str | None:
    """Return bounded, sanitized HTML safe for rendering in a sandboxed email frame, or None."""
    if not raw_html or not raw_html.strip():
        return None
    capped = clean_text(raw_html)[:MAX_HTML_CHARS]
    parser = _EmailHtmlSanitizer()
    try:
        parser.feed(capped)
        parser.close()
    except Exception:
        return None
    out = "".join(parser.parts).strip()
    return out or None
