"""MkDocs hook: point links that work on GitHub at their place on the docs site.

The README is the site's home page (docs/index.md includes it), and LICENSE and NOTICE live
outside docs/, so their relative links have no target on the site. The Markdown keeps the
GitHub form; this rewrites it at build time. mkdocs.yml loads it and excludes it from the site.
"""

import re

REPO = "https://github.com/toddcreasy/ehr-rwe-eln/blob/main/"


def on_page_markdown(markdown, page, config, files):
    depth = page.file.src_uri.count("/")
    home = "../" * depth + "index.md"
    markdown = re.sub(
        r"\]\((?:\.\./)+README\.md(#[^)]*)?\)", lambda m: f"]({home}{m.group(1) or ''})", markdown
    )
    return re.sub(r"\]\((?:\.\./)+(LICENSE|NOTICE)\)", lambda m: f"]({REPO}{m.group(1)})", markdown)
