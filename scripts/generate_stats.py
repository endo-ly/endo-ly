#!/usr/bin/env python3
"""Generate GitHub profile stats SVGs directly from the GitHub API.

No external services (Vercel, etc.) required — runs entirely in CI.
Produces: github-stats.svg, top-langs.svg, trophy.svg
"""

import json
import os
import sys
import urllib.error
import urllib.request

# ── Configuration ───────────────────────────────────────────────────────
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "endo-ava")
OUT   = os.environ.get("OUTPUT_DIR", "dist")
API   = "https://api.github.com"

# Tokyonight colour palette
C = {
    "bg":      "#1a1b27",
    "surface": "#24283b",
    "border":  "#414868",
    "text":    "#c0caf5",
    "sub":     "#565f89",
    "blue":    "#7aa2f7",
    "green":   "#9ece6a",
    "red":     "#f7768e",
    "yellow":  "#e0af68",
    "cyan":    "#73daca",
    "purple":  "#bb9af7",
    "orange":  "#ff9e64",
}

# Language → colour (GitHub official palette)
LANG_CLR = {
    "Python":           "#3572A5", "TypeScript":       "#3178C6",
    "JavaScript":       "#F7DF1E", "Go":               "#00ADD8",
    "Rust":             "#DEA584", "Java":             "#B07219",
    "HTML":             "#E34F26", "CSS":              "#563D7C",
    "Shell":            "#89E051", "Dart":             "#00B4AB",
    "Kotlin":           "#A97BFF", "Swift":            "#F05138",
    "C++":              "#F34B7D", "C":                "#555555",
    "Ruby":             "#CC342D", "PHP":              "#4F5D95",
    "Jupyter Notebook": "#DA5B0B", "Vue":              "#41B883",
    "Svelte":           "#FF3E00", "Lua":              "#000080",
    "Dockerfile":       "#384D54", "SCSS":             "#C6538C",
    "HCL":              "#844FBA", "Nix":              "#7E7EFF",
    "Makefile":         "#427819", "Perl":             "#0298C3",
    "R":                "#198CE7", "Scala":            "#DC322F",
    "Haskell":          "#5E5086", "Elixir":           "#6E4A7E",
}


# ── API helpers ─────────────────────────────────────────────────────────

def _get(path, extra_headers=None):
    hdrs = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    if extra_headers:
        hdrs.update(extra_headers)
    req = urllib.request.Request(f"{API}{path}", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as exc:
        print(f"  warn: {path} -> {exc}", file=sys.stderr)
        return None


def fetch_repos():
    repos, page = [], 1
    while True:
        batch = _get(
            f"/users/{OWNER}/repos"
            f"?per_page=100&page={page}&type=owner&sort=updated"
        )
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_languages(repos):
    totals = {}
    for repo in repos:
        if repo.get("fork"):
            continue
        data = _get(f'/repos/{OWNER}/{repo["name"]}/languages')
        if data:
            for lang, size in data.items():
                totals[lang] = totals.get(lang, 0) + size
    return totals


def _search_count(q):
    data = _get(f"/search/issues?q={q}&per_page=1")
    return data.get("total_count", 0) if data else 0


def _commit_count():
    data = _get(
        f"/search/commits?q=author:{OWNER}&per_page=1",
        extra_headers={"Accept": "application/vnd.github.cloak-preview+json"},
    )
    return data.get("total_count", 0) if data else 0


# ── Data gathering ──────────────────────────────────────────────────────

def gather():
    print("Fetching profile...")
    user = _get(f"/users/{OWNER}")

    print("Fetching repos...")
    repos = fetch_repos()
    print(f"  {len(repos)} repos")

    print("Fetching languages...")
    lang_bytes = fetch_languages(repos)

    total = sum(lang_bytes.values()) or 1
    langs = [
        {"name": n, "pct": round(s / total * 100, 1)}
        for n, s in sorted(lang_bytes.items(), key=lambda x: -x[1])[:8]
    ]
    # normalise to 100 %
    s = sum(l["pct"] for l in langs) or 1
    for l in langs:
        l["pct"] = round(l["pct"] / s * 100, 1)

    print("Fetching commit / PR / issue counts...")
    stats = {
        "commits":   _commit_count(),
        "prs":       _search_count(f"author:{OWNER}+type:pr"),
        "issues":    _search_count(f"author:{OWNER}+type:issue"),
        "stars":     sum(r["stargazers_count"] for r in repos),
        "repos":     user.get("public_repos", len(repos)) if user else len(repos),
        "followers": user.get("followers", 0) if user else 0,
    }
    return stats, langs


# ── Trophy calculator ───────────────────────────────────────────────────

def calc_trophies(st):
    def tier(val, th):
        for rank, lo in th:
            if val >= lo:
                return rank
        return None

    out = []
    for label, key, th in [
        ("Commits",      "commits",   [("S", 1000), ("A", 500), ("B", 100), ("C", 10)]),
        ("Stars",        "stars",     [("S", 100),  ("A", 50),  ("B", 20),  ("C", 5)]),
        ("Pull Requests","prs",       [("S", 200),  ("A", 100), ("B", 30),  ("C", 5)]),
        ("Issues",       "issues",    [("S", 100),  ("A", 50),  ("B", 20),  ("C", 5)]),
        ("Followers",    "followers", [("S", 100),  ("A", 50),  ("B", 20),  ("C", 5)]),
        ("Repositories", "repos",     [("S", 50),   ("A", 30),  ("B", 15),  ("C", 5)]),
    ]:
        r = tier(st[key], th)
        if r:
            out.append((label, r))
    return out


# ── SVG helpers ─────────────────────────────────────────────────────────

FF = "font-family='Segoe UI,Helvetica,Arial,sans-serif'"


def _wrap(w, h, body):
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' "
        f"width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
        f"<rect width='{w}' height='{h}' rx='6' fill='{C['bg']}'/>"
        f"<rect width='{w}' height='{h}' rx='6' fill='none' "
        f"stroke='{C['border']}' stroke-width='0.5'/>"
        f"{body}</svg>"
    )


def _title(txt, y=32):
    return (
        f"<text x='25' y='{y}' fill='{C['text']}' font-size='15' "
        f"font-weight='bold' {FF}>{txt}</text>"
        f"<line x1='25' y1='{y+10}' x2='445' y2='{y+10}' "
        f"stroke='{C['border']}' stroke-width='0.5'/>"
    )


# ── SVG generators ──────────────────────────────────────────────────────

def gen_stats(st):
    W, H = 470, 200
    rows = [
        ("Total Commits", f'{st["commits"]:,}',  C["yellow"]),
        ("Total PRs",     f'{st["prs"]:,}',      C["green"]),
        ("Total Issues",  f'{st["issues"]:,}',   C["cyan"]),
        ("Earned Stars",  f'{st["stars"]:,}',    C["orange"]),
        ("Repositories",  f'{st["repos"]:,}',    C["purple"]),
    ]
    body = _title("GitHub Stats")
    y = 60
    for label, val, clr in rows:
        body += (
            f"<circle cx='35' cy='{y}' r='4' fill='{clr}'/>"
            f"<text x='48' y='{y+4}' fill='{C['text']}' "
            f"font-size='13' {FF}>{label}</text>"
            f"<text x='445' y='{y+4}' fill='{clr}' "
            f"font-size='13' font-weight='bold' text-anchor='end' {FF}>"
            f"{val}</text>"
        )
        y += 28
    return _wrap(W, H, body)


def gen_langs(langs):
    if not langs:
        return None
    top = langs[:7]
    W, BAR_H, ITEM_H, HDR = 470, 8, 35, 55
    H = HDR + len(top) * ITEM_H + 15
    body = _title("Most Used Languages")
    y, bw = HDR, W - 50
    for lg in top:
        clr  = LANG_CLR.get(lg["name"], C["blue"])
        fill = bw * lg["pct"] / 100
        body += (
            f"<text x='25' y='{y}' fill='{C['text']}' "
            f"font-size='12' {FF}>{lg['name']}</text>"
            f"<text x='445' y='{y}' fill='{clr}' "
            f"font-size='12' text-anchor='end' {FF}>{lg['pct']}%</text>"
            f"<rect x='25' y='{y+6}' width='{bw}' height='{BAR_H}' "
            f"rx='4' fill='{C['surface']}'/>"
            f"<rect x='25' y='{y+6}' width='{fill:.1f}' height='{BAR_H}' "
            f"rx='4' fill='{clr}'/>"
        )
        y += ITEM_H
    return _wrap(W, H, body)


def gen_trophy(trophies):
    if not trophies:
        return None
    CW, CH, PAD, GAP = 120, 100, 15, 12
    W = len(trophies) * (CW + GAP) - GAP + PAD * 2
    H = CH + PAD * 2
    RC = {"S": C["yellow"], "A": C["green"], "B": C["blue"], "C": C["sub"]}

    body, x = "", PAD
    for label, rank in trophies:
        rc = RC.get(rank, C["sub"])
        cx = x + CW / 2
        body += (
            # card bg
            f"<rect x='{x}' y='{PAD}' width='{CW}' height='{CH}' "
            f"rx='6' fill='{C['surface']}'/>"
            f"<rect x='{x}' y='{PAD}' width='{CW}' height='{CH}' "
            f"rx='6' fill='none' stroke='{C['border']}' stroke-width='0.5'/>"
            # rank circle
            f"<circle cx='{cx}' cy='{PAD+30}' r='18' "
            f"fill='{rc}' opacity='0.15'/>"
            f"<circle cx='{cx}' cy='{PAD+30}' r='18' "
            f"fill='none' stroke='{rc}' stroke-width='1.5'/>"
            # rank letter
            f"<text x='{cx}' y='{PAD+36}' fill='{rc}' "
            f"font-size='18' font-weight='bold' text-anchor='middle' {FF}>"
            f"{rank}</text>"
            # label
            f"<text x='{cx}' y='{PAD+70}' fill='{C['sub']}' "
            f"font-size='9' text-anchor='middle' {FF}>{label}</text>"
        )
        x += CW + GAP
    return _wrap(W, H, body)


# ── Main ────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUT, exist_ok=True)

    stats, langs = gather()
    trophies = calc_trophies(stats)

    svgs = {
        "github-stats.svg": gen_stats(stats),
        "top-langs.svg":    gen_langs(langs),
        "trophy.svg":       gen_trophy(trophies),
    }
    for name, svg in svgs.items():
        if svg:
            with open(os.path.join(OUT, name), "w") as f:
                f.write(svg)
            print(f"  ok  {name}")

    print("Done.")


if __name__ == "__main__":
    main()
