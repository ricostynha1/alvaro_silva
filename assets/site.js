// Shared behaviour: theme toggle, mobile menu, scroll reveal.
(function () {
	const root = document.documentElement;

	function currentTheme() {
		return root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
	}

	const themeBtn = document.getElementById('theme-toggle');
	if (themeBtn) {
		themeBtn.addEventListener('click', () => {
			const next = currentTheme() === 'dark' ? 'light' : 'dark';
			root.setAttribute('data-theme', next);
			try { localStorage.setItem('theme', next); } catch (e) { /* storage unavailable */ }
		});
	}

	const nav = document.querySelector('.nav');
	const menuBtn = document.getElementById('menu-toggle');
	if (nav && menuBtn) {
		menuBtn.addEventListener('click', () => {
			const open = nav.getAttribute('data-open') === 'true';
			nav.setAttribute('data-open', String(!open));
			menuBtn.setAttribute('aria-expanded', String(!open));
		});
		nav.querySelectorAll('.nav-links a').forEach((link) => {
			link.addEventListener('click', () => nav.setAttribute('data-open', 'false'));
		});
	}

	const revealables = document.querySelectorAll('.reveal');
	if ('IntersectionObserver' in window) {
		const observer = new IntersectionObserver((entries) => {
			for (const entry of entries) {
				if (entry.isIntersecting) {
					entry.target.classList.add('in');
					observer.unobserve(entry.target);
				}
			}
		}, { rootMargin: '0px 0px -8% 0px' });
		revealables.forEach((el) => observer.observe(el));
	} else {
		revealables.forEach((el) => el.classList.add('in'));
	}

	const year = document.getElementById('year');
	if (year) year.textContent = new Date().getFullYear();
})();
