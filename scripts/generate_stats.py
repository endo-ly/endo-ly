#!/usr/bin/env python3
"""Generate GitHub profile stats SVGs directly from the GitHub API.

No external services (Vercel, etc.) required — runs entirely in CI.

Usage:
  # 本番データ（GitHub API から取得、GITHUB_TOKEN が必要）
  python3 scripts/generate_stats.py

  # モックデータ（API 不要、見た目の確認用）
  python3 scripts/generate_stats.py --mock

Output:
  dist/github-stats.svg  ... Commits / PRs / Issues / Stars / Repos
  dist/top-langs.svg     ... 言語使用率バー（最大7言語）
  dist/streak.svg        ... Current / Longest Streak + This Year
  dist/punch-card.svg    ... 曜日×時間帯のバブルチャート
  dist/trophy.svg        ... トロフィーランク（S/A/B/C）× 6カテゴリ

Notes:
  - 生成物は dist/ に出力され、.gitignore で除外済み
  - CI（.github/workflows/profile-assets.yml）が output ブランチに push する
  - 環境変数: GITHUB_TOKEN, GITHUB_REPOSITORY_OWNER, OUTPUT_DIR
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta


# ── Configuration ───────────────────────────────────────────────────────

TOKEN = os.environ.get("GITHUB_TOKEN", "")
OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "endo-ava")
OUT   = os.environ.get("OUTPUT_DIR", "dist")
API   = "https://api.github.com"
TZ_OFFSET = 9  # JST (UTC+9)

CARD_W, CARD_H = 470, 315
CARD_W, CARD_H = 470, 315

ACTIVITY_H = 260
PUNCH_W = 575
STREAK_W = 230

C = {
    "bg":      "#1a1b27",
    "surface": "#24283b",
    "border":  "#414868",
    "text":    "#c0caf5",
    "sub":     "#7982a9",
    "blue":    "#7aa2f7",
    "green":   "#9ece6a",
    "red":     "#f7768e",
    "yellow":  "#e0af68",
    "cyan":    "#73daca",
    "purple":  "#bb9af7",
    "orange":  "#ff9e64",
}

FS = {
    "title":  16,
    "hero":   48,
    "large":  26,
    "medium": 18,
    "body":   13,
    "small":  11,
    "badge":  14,
}

FF = "font-family='Segoe UI,Helvetica,Arial,sans-serif'"

# Language → colour (GitHub official palette)
LANG_CLR = {
    "1C Enterprise":    "#814CCC", "ABAP":             "#E8274B",
    "ActionScript":     "#882B0F", "Ada":              "#02F88C",
    "Agda":             "#315665", "Assembly":         "#6E4C13",
    "AutoHotkey":       "#6594B9", "Batchfile":        "#C1F12E",
    "C":                "#555555", "C#":               "#178600",
    "C++":              "#F34B7D", "Clojure":          "#DB5855",
    "CMake":            "#DA3434", "CoffeeScript":     "#244776",
    "Crystal":          "#000100", "CSS":              "#563D7C",
    "D":                "#BA595E", "Dart":             "#00B4AB",
    "Dockerfile":       "#384D54", "Elixir":           "#6E4A7E",
    "Elm":              "#60B5CC", "Emacs Lisp":       "#C065DB",
    "Erlang":           "#B83998", "F#":               "#B845FC",
    "Fortran":          "#4D41B1", "GLSL":             "#5586A4",
    "Go":               "#00ADD8", "Groovy":           "#4298B8",
    "HCL":              "#844FBA", "Haskell":          "#5E5086",
    "HTML":             "#E34F26", "Java":             "#B07219",
    "JavaScript":       "#F7DF1E", "Julia":            "#9558B2",
    "Jupyter Notebook": "#DA5B0B", "Kotlin":           "#A97BFF",
    "Less":             "#1D365D", "Lua":              "#000080",
    "Makefile":         "#427819", "Markdown":         "#083FA1",
    "Nix":              "#7E7EFF", "Objective-C":      "#438EFF",
    "OCaml":            "#3BE133", "Perl":             "#0298C3",
    "PHP":              "#4F5D95", "PowerShell":       "#012456",
    "Python":           "#3572A5", "R":                "#198CE7",
    "Ruby":             "#CC342D", "Rust":             "#DEA584",
    "Sass":             "#A53B70", "Scala":            "#DC322F",
    "SCSS":             "#C6538C", "Shell":            "#89E051",
    "Swift":            "#F05138", "Svelte":           "#FF3E00",
    "TSQL":             "#E38C00", "TypeScript":       "#3178C6",
    "V":                "#5D6D48", "Vim Script":       "#199F4B",
    "Vue":              "#41B883", "WebAssembly":      "#04133B",
    "Zig":              "#EC915C",
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


def _graphql(query):
    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        f"{API}/graphql", data=data,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as exc:
        print(f"  warn: graphql -> {exc}", file=sys.stderr)
        return None


# ── Data fetchers ───────────────────────────────────────────────────────

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


def fetch_commit_timestamps(repos):
    """Fetch commit timestamps from repos for punch card."""
    timestamps = []
    for repo in repos:
        if repo.get("fork"):
            continue
        commits = _get(f'/repos/{OWNER}/{repo["name"]}/commits?per_page=100')
        if not commits:
            continue
        for c in commits:
            if not isinstance(c, dict):
                continue
            author = c.get("author")
            if author and author.get("login") == OWNER:
                ts = c.get("commit", {}).get("author", {}).get("date", "")
                if ts:
                    timestamps.append(ts)
    print(f"  {len(timestamps)} commits found")
    return timestamps


def fetch_contribution_calendar():
    year = datetime.now().year
    query = (
        '{ user(login: "%s") { contributionsCollection('
        'from: "%d-01-01T00:00:00Z", to: "%d-12-31T23:59:59Z") {'
        " contributionCalendar { totalContributions weeks { contributionDays {"
        ' contributionCount date } } } } } }' % (OWNER, year, year)
    )
    result = _graphql(query)
    if not result:
        return None
    try:
        cal = result["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        days = []
        for week in cal["weeks"]:
            for day in week["contributionDays"]:
                days.append({"date": day["date"], "count": day["contributionCount"]})
        return {"total": cal["totalContributions"], "days": days}
    except (KeyError, TypeError):
        return None


def _search_count(q):
    data = _get(f"/search/issues?q={q}&per_page=1")
    return data.get("total_count", 0) if data else 0


def _commit_count():
    data = _get(
        f"/search/commits?q=author:{OWNER}&per_page=1",
        extra_headers={"Accept": "application/vnd.github.cloak-preview+json"},
    )
    return data.get("total_count", 0) if data else 0


# ── Data processing ─────────────────────────────────────────────────────

def gather():
    print("Fetching profile...")
    user = _get(f"/users/{OWNER}")

    print("Fetching repos...")
    repos = fetch_repos()
    print(f"  {len(repos)} repos")

    print("Fetching languages...")
    lang_bytes = fetch_languages(repos)
    for i, (n, s) in enumerate(sorted(lang_bytes.items(), key=lambda x: -x[1]), 1):
        print(f"    {i:2d}. {n:24s} {s:>12,} bytes")

    total = sum(lang_bytes.values()) or 1
    langs = [
        {"name": n, "pct": round(s / total * 100, 1)}
        for n, s in sorted(lang_bytes.items(), key=lambda x: -x[1])[:8]
    ]
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


def build_punch_card(timestamps):
    """Build a 7×24 matrix from commit timestamps."""
    matrix = [[0] * 24 for _ in range(7)]
    for ts in timestamps:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) + timedelta(hours=TZ_OFFSET)
            matrix[dt.weekday()][dt.hour] += 1
        except Exception:
            pass
    return matrix


def calc_streak(contrib_data):
    if not contrib_data or not contrib_data["days"]:
        return {"current": 0, "longest": 0, "total": 0}

    days = contrib_data["days"]
    total = contrib_data["total"]

    longest = streak = 0
    for day in days:
        if day["count"] > 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0

    current = 0
    for day in reversed(days):
        if day["count"] > 0:
            current += 1
        elif current == 0:
            continue
        else:
            break

    return {"current": current, "longest": longest, "total": total}


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


# ── SVG builder primitives ──────────────────────────────────────────────

def _svg_card(w, h, body):
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' "
        f"width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
        f"<rect width='{w}' height='{h}' rx='6' fill='{C['bg']}'/>"
        f"<rect width='{w}' height='{h}' rx='6' fill='none' "
        f"stroke='{C['border']}' stroke-width='0.5'/>"
        f"{body}</svg>"
    )


def _svg_title(txt, w, y=34):
    return (
        f"<text x='25' y='{y}' fill='{C['text']}' font-size='{FS['title']}' "
        f"font-weight='bold' {FF}>{txt}</text>"
        f"<line x1='25' y1='{y+12}' x2='{w-25}' y2='{y+12}' "
        f"stroke='{C['border']}' stroke-width='0.5'/>"
    )


def _svg_rect(x, y, w, h, fill, rx=6, stroke=None):
    s = (
        f"<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{h:.1f}' "
        f"rx='{rx}' fill='{fill}'/>"
    )
    if stroke:
        s += (
            f"<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{h:.1f}' "
            f"rx='{rx}' fill='none' stroke='{stroke}' stroke-width='0.5'/>"
        )
    return s


def _svg_circle(cx, cy, r, fill, opacity=1.0, stroke=None, stroke_w=1.0):
    s = f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='{r:.1f}' fill='{fill}'"
    if opacity < 1.0:
        s += f" opacity='{opacity:.2f}'"
    s += "/>"
    if stroke:
        s += (
            f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='{r:.1f}' "
            f"fill='none' stroke='{stroke}' stroke-width='{stroke_w:.1f}'/>"
        )
    return s


# ── SVG generators ──────────────────────────────────────────────────────

def gen_stats(st):
    W, H = CARD_W, CARD_H
    cells = [
        ("Total Commits", f'{st["commits"]:,}',  C["yellow"]),
        ("Total PRs",     f'{st["prs"]:,}',      C["green"]),
        ("Total Issues",  f'{st["issues"]:,}',   C["cyan"]),
        ("Earned Stars",  f'{st["stars"]:,}',    C["orange"]),
        ("Repositories",  f'{st["repos"]:,}',    C["purple"]),
        ("Followers",     f'{st["followers"]:,}', C["red"]),
    ]
    body = _svg_title("GitHub Stats", W, y=32)

    COLS, ROWS = 2, 3
    PAD, GAP = 20, 10
    HDR = 55
    cell_w = (W - PAD * 2 - GAP * (COLS - 1)) / COLS
    cell_h = (H - HDR - PAD - GAP * (ROWS - 1)) / ROWS

    for i, (label, val, clr) in enumerate(cells):
        col, row = i % COLS, i // COLS
        cx = PAD + col * (cell_w + GAP)
        cy = HDR + row * (cell_h + GAP)
        body += _svg_rect(cx, cy, cell_w, cell_h, C["surface"])
        vcx = cx + cell_w / 2
        vcy = cy + cell_h / 2 - 4
        body += (
            f"<text x='{vcx}' y='{vcy}' fill='{clr}' "
            f"font-size='24' font-weight='bold' text-anchor='middle' {FF}>"
            f"{val}</text>"
        )
        body += (
            f"<text x='{vcx}' y='{vcy+20}' fill='{C['sub']}' "
            f"font-size='10' text-anchor='middle' {FF}>{label}</text>"
        )
    return _svg_card(W, H, body)


def gen_langs(langs):
    if not langs:
        return None
    top = langs[:7]
    W, H = CARD_W, CARD_H
    HDR = 58
    BAR_H = 10
    item_h = (H - HDR - 15) / len(top)
    body = _svg_title("Most Used Languages", W)
    bw = W - 50

    for i, lg in enumerate(top):
        clr = LANG_CLR.get(lg["name"], C["blue"])
        y = HDR + i * item_h
        fill_w = bw * lg["pct"] / 100

        body += (
            f"<text x='25' y='{y:.1f}' fill='{C['text']}' "
            f"font-size='{FS['body']}' {FF}>{lg['name']}</text>"
            f"<text x='{W-25}' y='{y:.1f}' fill='{clr}' "
            f"font-size='{FS['body']}' text-anchor='end' {FF}>{lg['pct']}%</text>"
        )
        body += _svg_rect(25, y + 8, bw, BAR_H, C["surface"], rx=4)
        body += _svg_rect(25, y + 8, fill_w, BAR_H, clr, rx=4)

    return _svg_card(W, H, body)


def gen_streak(streak):
    W, H = STREAK_W, ACTIVITY_H  
    
    body = _svg_title("Streak Stats", W, y=32)
    cur = streak["current"]

    body += (
        f"<text x='{W/2}' y='105' fill='{C['green']}' "
        f"font-size='46' font-weight='bold' text-anchor='middle' {FF}>"
        f"{cur}</text>"
        f"<text x='{W/2}' y='130' fill='{C['sub']}' "
        f"font-size='12' text-anchor='middle' {FF}>"
        f"day{'s' if cur != 1 else ''} current streak</text>"
    )

    col_w = (W - 20) / 2
    y = 195
    lx, rx = 10 + col_w / 2, 10 + col_w + col_w / 2
    
    body += (
        f"<text x='{lx}' y='{y}' fill='{C['yellow']}' "
        f"font-size='24' font-weight='bold' text-anchor='middle' {FF}>"
        f"{streak['longest']}</text>"
        f"<text x='{lx}' y='{y+20}' fill='{C['sub']}' "
        f"font-size='10' text-anchor='middle' {FF}>Longest</text>" # 幅に収まるよう文字を短縮
        f"<text x='{rx}' y='{y}' fill='{C['cyan']}' "
        f"font-size='24' font-weight='bold' text-anchor='middle' {FF}>"
        f"{streak['total']:,}</text>"
        f"<text x='{rx}' y='{y+20}' fill='{C['sub']}' "
        f"font-size='10' text-anchor='middle' {FF}>This Year</text>"
    )
    return _svg_card(W, H, body)


def gen_punch_card(matrix):
    LM, TM = 48, 58
    GAP_R, GAP_B = 20, 20

    cell_w = (PUNCH_W - LM - GAP_R) / 24
    cell_h = (ACTIVITY_H - TM - GAP_B) / 7
    max_val = max(max(row) for row in matrix) or 1

    body = _svg_title("Punch Card", PUNCH_W)

    for h in range(0, 24, 3):
        x = LM + h * cell_w + cell_w / 2
        body += (
            f"<text x='{x:.1f}' y='{TM-10}' fill='{C['sub']}' "
            f"font-size='{FS['small']}' text-anchor='middle' {FF}>{h}</text>"
        )

    for d, day in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        y = TM + d * cell_h + cell_h / 2
        body += (
            f"<text x='{LM-8}' y='{y+4:.1f}' fill='{C['sub']}' "
            f"font-size='{FS['small']}' text-anchor='end' {FF}>{day}</text>"
        )

    for d in range(7):
        for h in range(24):
            cx = LM + h * cell_w + cell_w / 2
            cy = TM + d * cell_h + cell_h / 2
            val = matrix[d][h]
            if val == 0:
                body += _svg_circle(cx, cy, 1.5, C["border"])
            else:
                ratio = val / max_val
                max_r = min(cell_w, cell_h) / 2 * 0.7
                r = 2 + ratio * max_r
                opacity = 0.4 + ratio * 0.6
                clr = C["green"] if ratio > 0.7 else C["blue"] if ratio > 0.4 else C["cyan"]
                body += _svg_circle(cx, cy, r, clr, opacity=opacity)

    return _svg_card(PUNCH_W, ACTIVITY_H, body)


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
        badge_y = PAD + 30

        body += _svg_rect(x, PAD, CW, CH, C["surface"], stroke=C["border"])
        body += _svg_circle(cx, badge_y, 18, rc, opacity=0.15, stroke=rc, stroke_w=1.5)
        body += (
            f"<text x='{cx}' y='{badge_y+6:.1f}' fill='{rc}' "
            f"font-size='{FS['badge']}' font-weight='bold' text-anchor='middle' {FF}>"
            f"{rank}</text>"
        )
        body += (
            f"<text x='{cx}' y='{PAD+72}' fill='{C['sub']}' "
            f"font-size='{FS['body']}' text-anchor='middle' {FF}>{label}</text>"
        )
        x += CW + GAP
    return _svg_card(W, H, body)


# ── Mock data ───────────────────────────────────────────────────────────

MOCK_STATS = {
    "commits":   1_234,
    "prs":       87,
    "issues":    42,
    "stars":     56,
    "repos":     23,
    "followers": 18,
}

MOCK_LANGS = [
    {"name": "Python",     "pct": 35.2},
    {"name": "TypeScript", "pct": 24.8},
    {"name": "Go",         "pct": 15.3},
    {"name": "Shell",      "pct": 10.1},
    {"name": "HCL",        "pct":  7.6},
    {"name": "Dockerfile", "pct":  4.2},
    {"name": "HTML",       "pct":  2.8},
]

MOCK_PUNCH = [
    [0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 3, 5, 6, 7, 8, 6, 4, 3, 1, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 5, 6, 4, 7, 8, 6, 5, 7, 5, 3, 2, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 1, 3, 4, 3, 5, 6, 5, 4, 6, 5, 3, 2, 1, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 7, 6, 8, 9, 7, 6, 5, 4, 3, 2, 1, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 4, 5, 4, 3, 4, 3, 2, 1, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 3, 4, 3, 2, 3, 2, 1, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 2, 3, 2, 1, 2, 1, 0, 0, 0, 0, 0, 0],
]

MOCK_STREAK = {"current": 42, "longest": 128, "total": 1_234}


# ── Main ────────────────────────────────────────────────────────────────

def main():
    mock = "--mock" in sys.argv
    os.makedirs(OUT, exist_ok=True)

    if mock:
        print("Running with mock data...")
        stats, langs = MOCK_STATS, MOCK_LANGS
        punch, streak = MOCK_PUNCH, MOCK_STREAK
    else:
        stats, langs = gather()
        print("Fetching commit timestamps...")
        punch = build_punch_card(fetch_commit_timestamps(fetch_repos()))
        print("Fetching contribution calendar...")
        streak = calc_streak(fetch_contribution_calendar())

    trophies = calc_trophies(stats)

    svgs = {
        "github-stats.svg": gen_stats(stats),
        "top-langs.svg":    gen_langs(langs),
        "streak.svg":       gen_streak(streak),
        "punch-card.svg":   gen_punch_card(punch),
        "trophy.svg":       gen_trophy(trophies),
    }
    for name, svg in svgs.items():
        if svg:
            with open(os.path.join(OUT, name), "w") as f:
                f.write(svg)
            print(f"  ok  {name}")

    if "--preview" in sys.argv:
        _gen_preview(svgs)

    print("Done.")


def _gen_preview(svgs, md=""): # mdが引き継がれる想定
    import base64
    import os

    def b64(name):
        svg = svgs.get(name)
        if not svg:
            return None
        encoded = base64.b64encode(svg.encode()).decode()
        return f"data:image/svg+xml;base64,{encoded}"

    stats_src = b64("github-stats.svg")
    langs_src = b64("top-langs.svg")
    punch_src = b64("punch-card.svg")
    streak_src = b64("streak.svg")

    md += "### GitHub Stats\n\n"
    md += '<div align="center">\n  '
    
    stats_imgs = []
    if stats_src:
        stats_imgs.append(f'<img width="49%" align="top" src="{stats_src}"/>')
    if langs_src:
        stats_imgs.append(f'<img width="49%" align="top" src="{langs_src}"/>')
    
    md += "".join(stats_imgs)
    md += "\n</div>\n\n"
    
    md += "---\n\n"
    
    # --- Activity ---
    md += "### Activity\n\n"
    md += '<div align="center">\n  '
    
    activity_imgs = []
    if punch_src:
        activity_imgs.append(f'<img width="70%" align="top" src="{punch_src}"/>')
    if streak_src:
        activity_imgs.append(f'<img width="28%" align="top" src="{streak_src}"/>')
        
    md += "".join(activity_imgs)
    md += "\n</div>\n"

    path = os.path.join(OUT, "preview.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"  ok  preview.md -> {path}")


if __name__ == "__main__":
    main()
