// Enhances pages with Google Scholar data from data/scholar.js (refreshed twice a month by
// .github/workflows/refresh-data.yml). The curated HTML stays the source of truth; this
// adds citation metrics, per-paper "cited by" counts, and lists Scholar entries the
// site doesn't show yet.
(function () {
	// Scholar entries that are not mine or are duplicates; matched by title substring.
	const IGNORE = [
		'a prática de ensino supervisionada',
	];

	const normalize = (value) => value.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();

	function sameWork(a, b) {
		if (a === b) return true;
		const [short, long] = a.length < b.length ? [a, b] : [b, a];
		return short.length >= 24 && long.startsWith(short);
	}

	function escapeHtml(value) {
		return String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
	}

	function renderMetrics(el, data) {
		const m = data.metrics;
		const years = Object.entries(data.citations_per_year || {});
		const peak = Math.max(1, ...years.map(([, n]) => n));
		const bars = years.map(([year, n]) => `
			<div class="sch-bar" title="${n} citations in ${year}">
				<span style="height:${Math.max(4, Math.round((n / peak) * 100))}%"></span>
				<small>${year.slice(2)}</small>
			</div>`).join('');
		const updated = new Date(`${data.updated}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
		el.innerHTML = `
			<div class="sch-stat"><strong>${m.citations}</strong><span>citations</span></div>
			<div class="sch-stat"><strong>${m.h_index}</strong><span>h-index</span></div>
			<div class="sch-stat"><strong>${m.i10_index}</strong><span>i10-index</span></div>
			<div class="sch-bars" aria-label="Citations per year">${bars}</div>
			<a class="sch-source" href="${escapeHtml(data.profile_url)}" target="_blank" rel="noreferrer">Google Scholar · updated ${updated} ↗</a>`;
		el.hidden = false;
	}

	function annotatePubs(scholarPubs) {
		const matched = new Set();
		for (const pub of document.querySelectorAll('.pub')) {
			const heading = pub.querySelector('h3');
			if (!heading) continue;
			const title = normalize(heading.textContent);
			const hits = scholarPubs.filter((s) => sameWork(title, s.key));
			hits.forEach((s) => matched.add(s));
			if (!hits.length) continue;
			const best = hits.reduce((a, b) => (b.citations > a.citations ? b : a));
			const total = Math.max(...hits.map((s) => s.citations));
			if (total > 0) {
				const venue = pub.querySelector('.pub-venue');
				if (venue && !venue.querySelector('.sch-cited')) {
					venue.insertAdjacentHTML('beforeend', `<a class="sch-cited" href="${escapeHtml(best.url)}" target="_blank" rel="noreferrer">cited by ${total}</a>`);
				}
			}
		}
		return matched;
	}

	function renderUnlisted(el, pubs) {
		if (!pubs.length) return;
		el.innerHTML = `
			<section class="year-group">
				<h2 style="font-size:2rem">New on Scholar</h2>
				<ol class="pubs">
					${pubs.map((p) => `
						<li class="pub">
							<div class="pub-venue"><strong>${escapeHtml(p.year || '—')}</strong>via Scholar</div>
							<div>
								<h3><a href="${escapeHtml(p.url)}" target="_blank" rel="noreferrer">${escapeHtml(p.title)}</a></h3>
								<p class="authors">${escapeHtml(p.authors)}</p>
								${p.venue ? `<p class="summary">${escapeHtml(p.venue)}</p>` : ''}
							</div>
						</li>`).join('')}
				</ol>
			</section>`;
		el.hidden = false;
	}

	const data = window.SITE_DATA && window.SITE_DATA.scholar;
	if (!data) return; // static content already covers everything

	const scholarPubs = (data.publications || [])
		.map((p) => ({ ...p, key: normalize(p.title) }))
		.filter((p) => !IGNORE.some((fragment) => p.key.includes(normalize(fragment))));

	document.querySelectorAll('[data-scholar-metrics]').forEach((el) => renderMetrics(el, data));
	const matched = annotatePubs(scholarPubs);

	const unlistedEl = document.querySelector('[data-scholar-unlisted]');
	if (unlistedEl) {
		// Partial-title duplicates (e.g. "Can Large Language Models Help") count as listed.
		const unlisted = scholarPubs.filter((p) => !matched.has(p) && !scholarPubs.some((q) => q !== p && matched.has(q) && sameWork(p.key, q.key)));
		renderUnlisted(unlistedEl, unlisted);
	}
})();
