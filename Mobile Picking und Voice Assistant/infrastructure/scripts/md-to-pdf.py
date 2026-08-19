#!/usr/bin/env python3
"""Wandelt eine Markdown-Datei in ein druckfertiges PDF.

Warum ein eigenes Skript und kein pandoc: auf dieser Maschine gibt es weder
pandoc noch weasyprint noch ein Python-Markdown-Modul -- weder in WSL noch in
einem der Container. Was es gibt, ist Chrome unter Windows, und der druckt
zuverlaessig nach PDF. Dieses Skript uebersetzt deshalb den Markdown-Umfang,
den unsere Dokumente tatsaechlich benutzen, nach HTML und laesst Chrome den
Rest machen.

Bewusst KEIN vollstaendiger Markdown-Parser. Abgedeckt sind: Ueberschriften,
Absaetze, Aufzaehlungen (auch nummeriert), Tabellen, Zitatbloecke,
Code-Bloecke, Trennlinien sowie fett, kursiv, Code und Links im Fliesstext.
Alles andere geht als Text durch, statt still zu verschwinden -- ein Dokument,
das falsch aussieht, faellt auf; eines, dem eine Zeile fehlt, nicht.

Verwendung (aus dem Projektwurzelverzeichnis):

    python3 infrastructure/scripts/md-to-pdf.py docs/testing/handytest-leitfaden.md
    python3 infrastructure/scripts/md-to-pdf.py docs/*.md --output-dir /tmp/pdf

Das Ziel-PDF liegt standardmaessig neben der Quelldatei.
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME_CANDIDATES = (
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Users/{user}/AppData/Local/Google/Chrome/Application/chrome.exe",
)

CSS = """
@page { size: A4; margin: 18mm 16mm 16mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: 10.5pt; line-height: 1.5; color: #14181f; margin: 0;
}
h1 { font-size: 20pt; margin: 0 0 4mm; border-bottom: 2px solid #14181f; padding-bottom: 2mm; }
h2 { font-size: 14pt; margin: 8mm 0 2mm; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 5mm 0 1.5mm; page-break-after: avoid; }
p { margin: 0 0 3mm; }
ul, ol { margin: 0 0 3mm; padding-left: 6mm; }
li { margin: 0 0 1.2mm; }
hr { border: none; border-top: 1px solid #c8ced8; margin: 6mm 0; }
table { border-collapse: collapse; width: 100%; margin: 0 0 4mm; page-break-inside: avoid; }
th, td { border: 1px solid #c8ced8; padding: 1.6mm 2.2mm; text-align: left; vertical-align: top; }
th { background: #eef1f5; font-weight: 600; }
blockquote {
  margin: 0 0 4mm; padding: 2.5mm 3.5mm; border-left: 3px solid #3b6ea5;
  background: #f2f6fb; page-break-inside: avoid;
}
blockquote p:last-child { margin-bottom: 0; }
code { font-family: "Consolas", "Courier New", monospace; font-size: 9.5pt; background: #eef1f5; padding: 0.3mm 1mm; border-radius: 2px; }
pre { background: #f4f6f9; border: 1px solid #dfe4ec; padding: 2.5mm 3mm; margin: 0 0 4mm;
      white-space: pre-wrap; word-wrap: break-word; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 9pt; }
a { color: #1f4e79; }
strong { font-weight: 600; }
"""

INLINE_CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![\*\w])\*([^\*\n]+)\*(?!\*)")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def render_inline(text: str) -> str:
    """Fliesstext-Auszeichnung. Reihenfolge zaehlt: Code zuerst, damit
    Sternchen INNERHALB von Code nicht als Fettschrift gelesen werden."""
    placeholders: list[str] = []

    def stash(match: re.Match[str]) -> str:
        placeholders.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(placeholders) - 1}\x00"

    text = INLINE_CODE.sub(stash, text)
    text = html.escape(text)
    text = LINK.sub(r'<a href="\2">\1</a>', text)
    text = BOLD.sub(r"<strong>\1</strong>", text)
    text = ITALIC.sub(r"<em>\1</em>", text)
    for index, value in enumerate(placeholders):
        text = text.replace(f"\x00{index}\x00", value)
    return text


def render_table(rows: list[str]) -> str:
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]  # rows[1] ist die Trennzeile
    out = ["<table><thead><tr>"]
    out += [f"<th>{render_inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>" + "".join(f"<td>{render_inline(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def markdown_to_html(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            i += 1
            block: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(block)) + "</code></pre>")
            continue

        if not stripped:
            i += 1
            continue

        if re.fullmatch(r"-{3,}|_{3,}|\*{3,}", stripped):
            out.append("<hr>")
            i += 1
            continue

        heading = re.match(r"(#{1,6})\s+(.*)", stripped)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{render_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        # Tabelle: Kopfzeile plus Trennzeile aus Strichen und Pipes
        if (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and re.fullmatch(r"\|[\s:\-|]+\|", lines[i + 1].strip())
        ):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(render_table(rows))
            continue

        if stripped.startswith(">"):
            quote: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            paragraphs = "\n".join(quote).split("\n\n")
            inner = "".join(
                f"<p>{render_inline(p.replace(chr(10), ' ').strip())}</p>"
                for p in paragraphs
                if p.strip()
            )
            out.append(f"<blockquote>{inner}</blockquote>")
            continue

        list_match = re.match(r"([-*+]|\d+\.)\s+(.*)", stripped)
        if list_match:
            ordered = bool(re.fullmatch(r"\d+\.", list_match.group(1)))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while i < len(lines):
                candidate = lines[i].strip()
                match = re.match(r"([-*+]|\d+\.)\s+(.*)", candidate)
                if match:
                    items.append(render_inline(match.group(2)))
                    i += 1
                elif candidate and not candidate.startswith(("#", "|", ">", "```")) and items:
                    items[-1] += " " + render_inline(candidate)  # Fortsetzungszeile
                    i += 1
                else:
                    break
            out.append(f"<{tag}>" + "".join(f"<li>{it}</li>" for it in items) + f"</{tag}>")
            continue

        paragraph: list[str] = []
        while i < len(lines) and lines[i].strip() and not re.match(
            r"(#{1,6}\s|\||>|```|[-*+]\s|\d+\.\s)", lines[i].strip()
        ):
            paragraph.append(lines[i].strip())
            i += 1
        if paragraph:
            out.append(f"<p>{render_inline(' '.join(paragraph))}</p>")
        else:
            i += 1

    return "\n".join(out)


def find_chrome() -> str:
    import os

    user = os.environ.get("USER", "")
    for candidate in CHROME_CANDIDATES:
        path = Path(candidate.format(user=user))
        if path.exists():
            return str(path)
    raise SystemExit(
        "FEHLER: Chrome nicht gefunden. Dieses Skript druckt ueber Windows-Chrome; "
        "ohne ihn gibt es hier keinen PDF-Erzeuger."
    )


def to_windows_path(path: Path) -> str:
    resolved = str(path.resolve())
    if resolved.startswith("/mnt/"):
        drive = resolved[5]
        return f"{drive.upper()}:{resolved[6:]}".replace("/", "\\")
    raise SystemExit(
        f"FEHLER: {resolved} liegt ausserhalb von /mnt/<laufwerk>. Windows-Chrome "
        "kann nur auf Windows-Pfade zugreifen -- Quelle und Ziel muessen dort liegen."
    )


def convert(source: Path, target: Path, chrome: str) -> None:
    title = source.stem.replace("-", " ")
    body = markdown_to_html(source.read_text(encoding="utf-8"))
    document = (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
        f"<body>{body}</body></html>"
    )

    # Die HTML-Zwischendatei muss auf dem Windows-Dateisystem liegen, sonst
    # sieht Chrome sie nicht. Deshalb neben dem Ziel, nicht in /tmp.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", encoding="utf-8", dir=target.parent, delete=False
    ) as handle:
        handle.write(document)
        html_path = Path(handle.name)

    try:
        result = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={to_windows_path(target)}",
                "file:///" + to_windows_path(html_path).replace("\\", "/"),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        html_path.unlink(missing_ok=True)

    if not target.exists() or target.stat().st_size == 0:
        raise SystemExit(
            f"FEHLER: Chrome hat kein PDF erzeugt fuer {source}.\n{result.stderr[-800:]}"
        )
    print(f"OK  {source}  ->  {target}  ({target.stat().st_size // 1024} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Markdown-Dateien ueber Windows-Chrome nach PDF drucken."
    )
    parser.add_argument("sources", nargs="+", type=Path, help="Eine oder mehrere .md-Dateien")
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Zielverzeichnis (Standard: neben der Quelldatei)",
    )
    args = parser.parse_args()

    chrome = find_chrome()
    for source in args.sources:
        if not source.exists():
            print(f"uebersprungen (nicht gefunden): {source}", file=sys.stderr)
            continue
        directory = args.output_dir or source.parent
        directory.mkdir(parents=True, exist_ok=True)
        convert(source, directory / f"{source.stem}.pdf", chrome)


if __name__ == "__main__":
    main()
