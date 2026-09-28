#!/usr/bin/env python3
"""Regenerate assets/activity.svg and the merged-PR table in README.md.

Ported from a one-off draft generator to run unattended (see
.github/workflows/update-profile.yml). Talks to the GitHub GraphQL API using
only the standard library and the ambient GITHUB_TOKEN. The visual design of
the SVG and the README layout are intentionally unchanged from the committed
version -- only the underlying numbers/dates/rows are data-driven.

"Today" is deliberately never taken from the local clock: it is always the
last day present in the fetched contribution calendar, so a re-run against
the same snapshot of GitHub data is a no-op (idempotent).
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
ACTIVITY_SVG = ROOT / "assets" / "activity.svg"

MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
SANS = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"

GITHUB_USER = "tahakotil"
API_URL = "https://api.github.com/graphql"


def _token() -> str:
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok:
        raise SystemExit("GITHUB_TOKEN environment variable is required")
    return tok


def graphql(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "User-Agent": "tahakotil-profile-updater",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if "errors" in payload:
        raise SystemExit(f"GitHub API error: {payload['errors']}")
    return payload["data"]


CALENDAR_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch_calendar() -> tuple[list[tuple[str, int]], int]:
    data = graphql(CALENDAR_QUERY, {"login": GITHUB_USER})
    cal = data["user"]["contributionsCollection"]["contributionCalendar"]
    days = [
        (d["date"], d["contributionCount"])
        for w in cal["weeks"]
        for d in w["contributionDays"]
    ]
    return days, cal["totalContributions"]


MERGED_PRS_QUERY = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number
        title
        mergedAt
        repository { nameWithOwner }
      }
    }
  }
}
"""


def fetch_merged_prs() -> list[tuple[str, int, str, str]]:
    """Merged PRs authored by GITHUB_USER in repos NOT owned by GITHUB_USER."""
    q = f"is:pr is:merged author:{GITHUB_USER} -user:{GITHUB_USER}"
    prs: list[tuple[str, int, str, str]] = []
    after = None
    while True:
        data = graphql(MERGED_PRS_QUERY, {"q": q, "after": after})
        search = data["search"]
        for node in search["nodes"]:
            prs.append(
                (
                    node["repository"]["nameWithOwner"],
                    node["number"],
                    node["title"],
                    node["mergedAt"],
                )
            )
        if not search["pageInfo"]["hasNextPage"]:
            break
        after = search["pageInfo"]["endCursor"]
    prs.sort(key=lambda p: p[3], reverse=True)
    return prs


def pr_url(repo: str, n: int) -> str:
    return f"https://github.com/{repo}/pull/{n}"


def render_activity_svg(days: list[tuple[str, int]], year_total: int) -> str:
    win = days[-56:]
    counts = [c for _, c in win]
    total, active, peak = sum(counts), sum(1 for c in counts if c), max(counts) or 1
    W, H = 1200, 360
    L, R, T, B = 60, 1156, 150, 300
    step = (R - L) / (len(win) - 1)
    pts = [(L + i * step, B - (c / peak) * (B - T)) for i, c in enumerate(counts)]

    def smooth(points: list[tuple[float, float]]) -> str:
        d = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            mx = (x0 + x1) / 2
            d += f" C{mx:.1f} {y0:.1f} {mx:.1f} {y1:.1f} {x1:.1f} {y1:.1f}"
        return d

    line = smooth(pts)
    area = f"{line} L{R} {B} L{L} {B} Z"
    s = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">',
        "<title id=\"t\">Taha Kotil — GitHub activity, last 8 weeks</title>",
        f'<desc id="d">{total} contributions over the last 8 weeks, {active} of 56 days active, {year_total} in the last year.</desc>',
        "<defs>",
        '<linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f59e0b" stop-opacity=".35"/><stop offset="1" stop-color="#f59e0b" stop-opacity="0"/></linearGradient>',
        "</defs>",
        "<style>",
        f"text{{font-family:{MONO}}}",
        "@keyframes draw{to{stroke-dashoffset:0}}.ln{stroke-dasharray:1;stroke-dashoffset:1;animation:draw 2.2s .3s ease-out forwards}",
        "@keyframes fade{to{opacity:1}}.ar{opacity:0;animation:fade 1s 1.4s forwards}",
        "@media (prefers-reduced-motion:reduce){.ln{animation:none;stroke-dashoffset:0}.ar{animation:none;opacity:1}}",
        "</style>",
        f'<rect width="{W}" height="{H}" rx="16" fill="#0d1117"/>',
        f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="15.5" fill="none" stroke="#30363d"/>',
        f'<path d="M0 16a16 16 0 0 1 16-16h{W - 32}a16 16 0 0 1 16 16v28H0z" fill="#161b22"/>',
        f'<path d="M0 44H{W}" stroke="#30363d"/>',
        '<circle cx="26" cy="22" r="6.5" fill="#ff5f57"/><circle cx="48" cy="22" r="6.5" fill="#febc2e"/><circle cx="70" cy="22" r="6.5" fill="#28c840"/>',
        f'<text x="{W / 2}" y="28" text-anchor="middle" style="font-size:14px;fill:#7d8590">activity — last 8 weeks</text>',
    ]
    stats = [(f"{total:,}", "contributions · 8 weeks"), (f"{active}/56", "active days"), (f"{year_total:,}", "contributions · 12 months")]
    colw = (R - L) / 3
    for i, (big, lab) in enumerate(stats):
        x = L + i * colw
        s.append(f'<text x="{x}" y="94" style="font:700 30px {SANS};fill:#f0f6fc;letter-spacing:-.5px">{big}</text>')
        s.append(f'<text x="{x + 2}" y="118" style="font-size:13px;letter-spacing:1px;fill:#7d8590">{lab.upper()}</text>')
    for frac in (0, .5, 1):
        y = B - frac * (B - T)
        s.append(f'<path d="M{L} {y:.1f}H{R}" stroke="#21262d" stroke-dasharray="{"0" if frac == 0 else "3 6"}"/>')
    s.append(f'<text x="{L - 10}" y="{T + 4}" text-anchor="end" style="font-size:12px;fill:#7d8590">{peak}</text>')
    s.append(f'<text x="{L - 10}" y="{B + 4}" text-anchor="end" style="font-size:12px;fill:#7d8590">0</text>')
    s.append(f'<path d="{area}" fill="url(#fill)" class="ar"/>')
    s.append(f'<path d="{line}" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linejoin="round" pathLength="1" class="ln"/>')
    for i in range(0, len(win), 14):
        x = L + i * step
        label = date.fromisoformat(win[i][0]).strftime("%b %d").upper()
        s.append(f'<text x="{x:.1f}" y="{B + 28}" text-anchor="{"start" if i == 0 else "middle"}" style="font-size:12px;fill:#7d8590">{label}</text>')
    lx, ly = pts[-1]
    s.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="5" fill="#f59e0b" class="ar"/>')
    s.append(f'<text x="{R}" y="{B + 28}" text-anchor="end" style="font-size:12px;fill:#7d8590">TODAY</text>')
    s.append("</svg>")
    return "\n".join(s)


def render_pr_rows(prs: list[tuple[str, int, str, str]]) -> str:
    return "\n".join(
        f"| [`{repo}`](https://github.com/{repo}) | [#{n}]({pr_url(repo, n)}) | {html.escape(title)} |"
        for repo, n, title, _ in prs
    )


PR_BLOCK_RE = re.compile(
    r"(<summary><b>Open source</b> · )\d+( merged pull requests upstream</summary>\n\n"
    r"\| Repository \| PR \| Change \|\n\| --- \| --- \| --- \|\n)"
    r"(?:.*?\n)*?(?=\n</details>)",
    re.DOTALL,
)


def update_readme(prs: list[tuple[str, int, str, str]]) -> None:
    text = README.read_text(encoding="utf-8")
    rows = render_pr_rows(prs)

    def repl(m: re.Match) -> str:
        return f"{m.group(1)}{len(prs)}{m.group(2)}{rows}\n"

    new_text, n = PR_BLOCK_RE.subn(repl, text)
    if n != 1:
        raise SystemExit("Could not locate PR table block in README.md (expected exactly one match)")
    README.write_text(new_text, encoding="utf-8")


def main() -> None:
    days, year_total = fetch_calendar()
    if not days:
        raise SystemExit("No contribution calendar data returned")
    ACTIVITY_SVG.write_text(render_activity_svg(days, year_total), encoding="utf-8")

    prs = fetch_merged_prs()
    update_readme(prs)


if __name__ == "__main__":
    main()
