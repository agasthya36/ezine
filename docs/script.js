(() => {
  let lang = 'en';
  const toggle = document.getElementById('langToggle');

  function applyLang() {
    document.querySelectorAll('[data-en]').forEach(el => {
      const val = el.getAttribute(`data-${lang}`);
      if (val) el.innerHTML = val;
    });
    document.documentElement.lang = lang === 'kn' ? 'kn' : 'en';
    toggle.setAttribute('aria-pressed', lang === 'kn' ? 'true' : 'false');
  }

  toggle.addEventListener('click', () => {
    lang = lang === 'en' ? 'kn' : 'en';
    applyLang();
  });
})();
