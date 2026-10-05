#!/usr/bin/env python3
"""Refresh the site's data snapshots so the website itself stays fully static.

Writes:
  data/scholar.json  citation metrics and publication list from Google Scholar
  data/github.json   contribution calendar and recently active repositories
  data/gitlab.json   contribution calendar and recently active projects

plus a data/<name>.js twin of each, which the pages load via <script> tags.

Runs on a schedule in .github/workflows/refresh-data.yml and can also be run by
hand:  python3 scripts/update_data.py [scholar] [github] [gitlab]

Each source is independent: if one is blocked or fails, its previous JSON is
kept and the others still update. Uses only the Python standard library.
Set GITHUB_TOKEN to use the GitHub GraphQL API (complete calendar plus every
repository contributed to); without it, public pages and the REST API are used.
"""

import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHOLAR_ID = "24BoIRsAAAAJ"
GITHUB_USER = "ricostynha1"
GITLAB_USER = "ricostynha"

DATA = Path(__file__).resolve().parent.parent / "data"
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
NOW = datetime.now(timezone.utc)
YEAR_AGO = NOW - timedelta(days=365)


# ---------------------------------------------------------------- helpers

def http(url, headers=None, data=None):
	request = urllib.request.Request(url, data=data, headers={"User-Agent": BROWSER_UA, **(headers or {})})
	with urllib.request.urlopen(request, timeout=30) as response:
		return response.read().decode("utf-8", "replace"), response.headers


def http_json(url, headers=None, data=None):
	body, response_headers = http(url, {"Accept": "application/json", **(headers or {})}, data)
	return json.loads(body), response_headers


def text(fragment):
	return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def save(name, data):
	"""Write data/<name>.json and data/<name>.js unless only the 'updated' stamp would change."""
	path = DATA / f"{name}.json"
	if path.exists() and (DATA / f"{name}.js").exists():
		previous = json.loads(path.read_text(encoding="utf-8"))
		if {**previous, "updated": None} == {**data, "updated": None}:
			print(f"{name}: unchanged")
			return
	DATA.mkdir(parents=True, exist_ok=True)
	payload = json.dumps(data, ensure_ascii=False, indent="\t")
	path.write_text(payload + "\n", encoding="utf-8")
	# Same data as a script, so pages can load it with <script src> (works on file:// too).
	(DATA / f"{name}.js").write_text(
		f"window.SITE_DATA = window.SITE_DATA || {{}};\nwindow.SITE_DATA[{json.dumps(name)}] = {payload};\n",
		encoding="utf-8",
	)
	print(f"{name}: updated")


def last_year(calendar):
	cutoff = YEAR_AGO.date().isoformat()
	return {day: count for day, count in sorted(calendar.items()) if day >= cutoff}


# ---------------------------------------------------------------- Google Scholar

def fetch_scholar():
	profile = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en"
	page, _ = http(f"{profile}&sortby=pubdate&pagesize=100", {"Accept-Language": "en-US,en;q=0.9"})

	stats = re.findall(r'<td class="gsc_rsb_std">(\d*)</td>', page)
	if len(stats) < 6:
		raise ValueError("citation table not found (blocked or layout changed)")

	# The per-year bar chart: bars are ordered by z-index, most recent year = 1.
	years = re.findall(r'<span class="gsc_g_t"[^>]*>(\d{4})</span>', page)
	per_year = {year: 0 for year in years}
	for z_index, count in re.findall(r'class="gsc_g_a"[^>]*z-index:(\d+)[^>]*><span class="gsc_g_al">(\d+)</span>', page):
		position = len(years) - int(z_index)
		if 0 <= position < len(years):
			per_year[years[position]] = int(count)

	publications = []
	for row in re.findall(r'<tr class="gsc_a_tr">(.*?)</tr>', page, re.S):
		title = re.search(r'<a href="([^"]*)" class="gsc_a_at">(.*?)</a>', row, re.S)
		if not title:
			continue
		grays = re.findall(r'<div class="gs_gray">(.*?)</div>', row, re.S)
		venue = re.sub(r'<span class="gs_oph">.*?</span>', "", grays[1]) if len(grays) > 1 else ""
		cited = re.search(r'class="gsc_a_ac gs_ibl"[^>]*>(\d*)</a>', row)
		year = re.search(r'class="gsc_a_h gsc_a_hc gs_ibl">(\d*)</span>', row)
		publications.append({
			"title": text(title.group(2)),
			"authors": text(grays[0]) if grays else "",
			"venue": text(venue),
			"year": int(year.group(1)) if year and year.group(1) else None,
			"citations": int(cited.group(1)) if cited and cited.group(1) else 0,
			"url": "https://scholar.google.com" + html.unescape(title.group(1)),
		})
	if not publications:
		raise ValueError("no publications parsed")

	return {
		"profile_url": profile,
		"updated": NOW.strftime("%Y-%m-%d"),
		"metrics": {
			"citations": int(stats[0] or 0),
			"citations_recent": int(stats[1] or 0),
			"h_index": int(stats[2] or 0),
			"h_index_recent": int(stats[3] or 0),
			"i10_index": int(stats[4] or 0),
			"i10_index_recent": int(stats[5] or 0),
		},
		"citations_per_year": per_year,
		"publications": publications,
	}


# ---------------------------------------------------------------- GitHub

GITHUB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
      commitContributionsByRepository(maxRepositories: 50) { contributions { totalCount } repository { ...repo } }
      pullRequestContributionsByRepository(maxRepositories: 50) { contributions { totalCount } repository { ...repo } }
      issueContributionsByRepository(maxRepositories: 50) { contributions { totalCount } repository { ...repo } }
    }
    repositories(first: 50, orderBy: {field: PUSHED_AT, direction: DESC}, privacy: PUBLIC) { nodes { ...repo } }
  }
}
fragment repo on Repository {
  nameWithOwner url description stargazerCount isFork isPrivate pushedAt
  primaryLanguage { name color }
}
"""


def github_repo(node, contributions=0):
	return {
		"name": node["nameWithOwner"],
		"url": node["url"],
		"description": node.get("description") or "",
		"language": (node.get("primaryLanguage") or {}).get("name"),
		"color": (node.get("primaryLanguage") or {}).get("color"),
		"stars": node.get("stargazerCount", 0),
		"fork": node.get("isFork", False),
		"contributions": contributions,
		"last_activity": node.get("pushedAt"),
	}


def fetch_github_graphql(token):
	payload = json.dumps({
		"query": GITHUB_QUERY,
		"variables": {"login": GITHUB_USER, "from": YEAR_AGO.isoformat(), "to": NOW.isoformat()},
	}).encode()
	result, _ = http_json("https://api.github.com/graphql", {"Authorization": f"bearer {token}", "Content-Type": "application/json"}, payload)
	if result.get("errors"):
		raise ValueError(result["errors"][0].get("message", "GraphQL error"))
	user = result["data"]["user"]
	collection = user["contributionsCollection"]

	calendar = {
		day["date"]: day["contributionCount"]
		for week in collection["contributionCalendar"]["weeks"]
		for day in week["contributionDays"]
	}

	repos = {}
	for key in ("commitContributionsByRepository", "pullRequestContributionsByRepository", "issueContributionsByRepository"):
		for entry in collection[key]:
			node = entry["repository"]
			if node.get("isPrivate"):
				continue
			repo = repos.setdefault(node["nameWithOwner"], github_repo(node))
			repo["contributions"] += entry["contributions"]["totalCount"]
	# Forks don't earn contribution credit, so also include own repos pushed this year.
	for node in user["repositories"]["nodes"]:
		if node["pushedAt"] and node["pushedAt"] >= YEAR_AGO.isoformat():
			repos.setdefault(node["nameWithOwner"], github_repo(node))
	return calendar, list(repos.values())


def fetch_github_public():
	page, _ = http(f"https://github.com/users/{GITHUB_USER}/contributions")
	dates = dict(re.findall(r'data-date="(\d{4}-\d{2}-\d{2})" id="([^"]+)"', page))
	ids_to_dates = {cell_id: day for day, cell_id in dates.items()}
	calendar = {day: 0 for day in dates}
	for cell_id, label in re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)</tool-tip>', page):
		match = re.match(r"(\d+) contribution", label)
		if cell_id in ids_to_dates and match:
			calendar[ids_to_dates[cell_id]] = int(match.group(1))
	if not calendar:
		raise ValueError("contribution calendar not found")

	nodes, _ = http_json(f"https://api.github.com/users/{GITHUB_USER}/repos?per_page=100&sort=pushed")
	repos = {}
	for node in nodes:
		if node["pushed_at"] >= YEAR_AGO.isoformat():
			repos[node["full_name"]] = {
				"name": node["full_name"], "url": node["html_url"], "description": node.get("description") or "",
				"language": node.get("language"), "color": None, "stars": node.get("stargazers_count", 0),
				"fork": node.get("fork", False), "contributions": 0, "last_activity": node["pushed_at"],
			}
	return calendar, list(repos.values())


def fetch_github():
	token = os.environ.get("GITHUB_TOKEN")
	try:
		if not token:
			raise ValueError("GITHUB_TOKEN not set")
		calendar, repos = fetch_github_graphql(token)
	except Exception as error:
		print(f"github: GraphQL unavailable ({error}); using public pages", file=sys.stderr)
		calendar, repos = fetch_github_public()
	return {
		"platform": "GitHub",
		"handle": GITHUB_USER,
		"profile_url": f"https://github.com/{GITHUB_USER}",
		"updated": NOW.strftime("%Y-%m-%d"),
		"calendar": last_year(calendar),
		"repos": sorted(repos, key=lambda r: r["last_activity"] or "", reverse=True),
	}


# ---------------------------------------------------------------- GitLab

def fetch_gitlab():
	calendar, _ = http_json(f"https://gitlab.com/users/{GITLAB_USER}/calendar.json")

	# Public events from the last year -> which projects were active and how much.
	after = (YEAR_AGO - timedelta(days=1)).date().isoformat()
	activity = {}
	page = "1"
	while page:
		events, headers = http_json(f"https://gitlab.com/api/v4/users/{GITLAB_USER}/events?per_page=100&after={after}&page={page}")
		for event in events:
			project_id = event.get("project_id")
			if not project_id:
				continue
			entry = activity.setdefault(project_id, {"count": 0, "last": event["created_at"]})
			entry["count"] += 1
			entry["last"] = max(entry["last"], event["created_at"])
		page = headers.get("X-Next-Page")

	repos = []
	for project_id, entry in activity.items():
		try:
			project, _ = http_json(f"https://gitlab.com/api/v4/projects/{project_id}")
		except Exception:
			continue  # private or deleted project: skip rather than leak a placeholder
		repos.append({
			"name": project.get("name_with_namespace") or project.get("path_with_namespace"),
			"url": project.get("web_url"),
			"description": project.get("description") or "",
			"language": None,
			"color": None,
			"stars": project.get("star_count", 0),
			"fork": bool(project.get("forked_from_project")),
			"contributions": entry["count"],
			"last_activity": entry["last"],
		})

	return {
		"platform": "GitLab",
		"handle": GITLAB_USER,
		"profile_url": f"https://gitlab.com/{GITLAB_USER}",
		"updated": NOW.strftime("%Y-%m-%d"),
		"calendar": last_year(calendar),
		"repos": sorted(repos, key=lambda r: r["last_activity"] or "", reverse=True),
	}


# ---------------------------------------------------------------- main

SOURCES = {"scholar": fetch_scholar, "github": fetch_github, "gitlab": fetch_gitlab}


def main(argv):
	selected = argv or list(SOURCES)
	for name in selected:
		try:
			save(name, SOURCES[name]())
		except Exception as error:
			print(f"warning: {name} skipped ({error}); keeping previous data/{name}.json", file=sys.stderr)
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
