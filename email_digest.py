#!/usr/bin/env python3
"""Send PaperCatch paper digests by email."""

from __future__ import annotations

import argparse
import json
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from config import load_config


BASE_DIR = Path(__file__).resolve().parent
DB_JSON = BASE_DIR / "papers_database.json"
NEW_JSON = BASE_DIR / "new_papers.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Send PaperCatch email digest")
    parser.add_argument("--source", choices=["new", "database"], default="new")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config()["email"]
    papers = load_papers(args.source, args.limit)
    subject, text_body, html_body = build_digest(papers, args.source)

    if args.dry_run:
        print(subject)
        print()
        print(text_body)
        return

    if not config.get("enabled"):
        print("Email digest is disabled. Run python start.py --setup to enable it.")
        return
    validate_email_config(config)
    send_email(config, subject, text_body, html_body)
    print(f"Email digest sent to {config.get('smtp_to')}")


def load_papers(source: str, limit: int) -> list[dict]:
    path = NEW_JSON if source == "new" and NEW_JSON.exists() else DB_JSON
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    papers = data.get("new_papers") if source == "new" else data.get("papers")
    papers = papers or data.get("papers") or []
    papers = sorted(
        papers,
        key=lambda item: (
            item.get("quality_score") is not None,
            item.get("quality_score") or 0,
            item.get("published", ""),
        ),
        reverse=True,
    )
    return papers[: max(1, limit)]


def build_digest(papers: list[dict], source: str) -> tuple[str, str, str]:
    today = datetime.now().strftime("%Y-%m-%d")
    label = "新论文" if source == "new" else "精选论文"
    subject = f"PaperCatch {label}日报 {today} ({len(papers)} 篇)"
    if not papers:
        return subject, "今天没有可推送的论文。", "<p>今天没有可推送的论文。</p>"

    text_lines = [subject, ""]
    html_items = []
    for i, paper in enumerate(papers, 1):
        title = paper.get("title", "Untitled")
        authors = "; ".join((paper.get("authors") or [])[:6])
        score = paper.get("quality_score")
        score_text = f" | score {score}" if score is not None else ""
        abstract_cn = paper.get("abstract_cn") or paper.get("abstract") or ""
        abs_url = paper.get("abs_url") or ""
        pdf_url = paper.get("pdf_url") or ""

        text_lines.extend([
            f"{i}. {title}{score_text}",
            f"   Authors: {authors}",
            f"   Link: {abs_url}",
            f"   PDF: {pdf_url}",
            f"   Summary: {compact(abstract_cn, 520)}",
            "",
        ])
        html_items.append(
            "<li>"
            f"<h3>{escape_html(title)}{escape_html(score_text)}</h3>"
            f"<p><strong>Authors:</strong> {escape_html(authors)}</p>"
            f"<p>{escape_html(compact(abstract_cn, 700))}</p>"
            f"<p><a href='{escape_attr(abs_url)}'>arXiv</a> "
            f"<a href='{escape_attr(pdf_url)}'>PDF</a></p>"
            "</li>"
        )

    html_body = (
        "<!doctype html><html><body>"
        f"<h2>{escape_html(subject)}</h2>"
        "<ol>"
        + "".join(html_items)
        + "</ol></body></html>"
    )
    return subject, "\n".join(text_lines), html_body


def validate_email_config(config: dict) -> None:
    missing = [key for key in ("smtp_host", "smtp_to") if not config.get(key)]
    if missing:
        raise SystemExit(f"Missing email config: {', '.join(missing)}")


def send_email(config: dict, subject: str, text_body: str, html_body: str) -> None:
    sender = config.get("smtp_from") or config.get("smtp_user") or "papercatch@localhost"
    recipients = [item.strip() for item in str(config.get("smtp_to", "")).split(",") if item.strip()]
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    host = config.get("smtp_host")
    port = int(config.get("smtp_port") or 587)
    username = config.get("smtp_user") or ""
    password = config.get("smtp_password") or ""

    if config.get("use_tls", True):
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(message)


def compact(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def escape_html(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def escape_attr(value: str) -> str:
    return escape_html(value).replace("'", "&#39;").replace('"', "&quot;")


if __name__ == "__main__":
    main()
