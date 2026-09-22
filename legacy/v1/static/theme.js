/* theme.js — load early (blocking) in <head> to apply theme before first paint */
(function () {
  var THEMES = {
    oudgeld: {
      '--bg': '#0e0c07', '--panel': '#16130a', '--panel2': '#1a1710',
      '--grid': '#3a3320', '--text': '#e8dfc0', '--muted': '#9e9070',
      '--accent': '#c9a84c', '--primary': '#8b6914',
      '--ok': '#7dab6e', '--danger': '#b34a3a', '--warn': '#c8873a',
      '--up': '#7dab6e', '--down': '#b34a3a',
      '--pill': '#2a2510', '--pillb': '#4a4020',
      '--input-bg': '#110f08', '--input-border': '#3a3020',
      '--header-top': '#18150c', '--header-bot': '#0e0c07',
      '--ticker-bg': '#110f08', '--news-bg': '#16130a',
      '--sma-line': '#c9a84c',
    },
    blauw: {
      '--bg': '#070b16', '--panel': '#0b1220', '--panel2': '#0e1628',
      '--grid': '#1a2744', '--text': '#e6edf3', '--muted': '#9aa7bd',
      '--accent': '#60a5fa', '--primary': '#2563eb',
      '--ok': '#10b981', '--danger': '#dc2626', '--warn': '#f59e0b',
      '--up': '#10b981', '--down': '#ef4444',
      '--pill': '#111827', '--pillb': '#374151',
      '--input-bg': '#091226', '--input-border': '#243253',
      '--header-top': '#0b1325', '--header-bot': '#090f1c',
      '--ticker-bg': '#0a1324', '--news-bg': '#0b1325',
      '--sma-line': '#fbbf24',
    },
    groen: {
      '--bg': '#020d0a', '--panel': '#051a10', '--panel2': '#071e12',
      '--grid': '#0d3320', '--text': '#d1fae5', '--muted': '#6ee7b7',
      '--accent': '#34d399', '--primary': '#059669',
      '--ok': '#10b981', '--danger': '#ef4444', '--warn': '#fbbf24',
      '--up': '#34d399', '--down': '#f87171',
      '--pill': '#052e16', '--pillb': '#14532d',
      '--input-bg': '#031a0c', '--input-border': '#166534',
      '--header-top': '#041810', '--header-bot': '#020f07',
      '--ticker-bg': '#031a0c', '--news-bg': '#041810',
      '--sma-line': '#fbbf24',
    },
    paars: {
      '--bg': '#0d0a1a', '--panel': '#12103a', '--panel2': '#0f0e2e',
      '--grid': '#2a2060', '--text': '#ede9fe', '--muted': '#a78bfa',
      '--accent': '#c084fc', '--primary': '#7c3aed',
      '--ok': '#10b981', '--danger': '#dc2626', '--warn': '#f59e0b',
      '--up': '#10b981', '--down': '#ef4444',
      '--pill': '#1e1b4b', '--pillb': '#4338ca',
      '--input-bg': '#0d0a1f', '--input-border': '#3730a3',
      '--header-top': '#12103a', '--header-bot': '#0a0820',
      '--ticker-bg': '#0d0a1f', '--news-bg': '#12103a',
      '--sma-line': '#fbbf24',
    },
    rood: {
      '--bg': '#0f0505', '--panel': '#1a0808', '--panel2': '#150606',
      '--grid': '#3d1515', '--text': '#fee2e2', '--muted': '#fca5a5',
      '--accent': '#f87171', '--primary': '#dc2626',
      '--ok': '#10b981', '--danger': '#ef4444', '--warn': '#f59e0b',
      '--up': '#10b981', '--down': '#ef4444',
      '--pill': '#450a0a', '--pillb': '#7f1d1d',
      '--input-bg': '#1a0505', '--input-border': '#7f1d1d',
      '--header-top': '#1a0808', '--header-bot': '#0f0505',
      '--ticker-bg': '#1a0505', '--news-bg': '#1a0808',
      '--sma-line': '#fbbf24',
    },
  };

  function _loadCustomVars() {
    try { var s = localStorage.getItem('theme-custom'); return s ? JSON.parse(s) : null; }
    catch(e) { return null; }
  }

  /* Swatch preview colors shown in the settings UI */
  window.THEME_META = {
    oudgeld: { label: 'Oud Geld', swatches: ['#0e0c07', '#16130a', '#c9a84c', '#7dab6e'] },
    blauw: { label: 'Blauw',  swatches: ['#070b16', '#0b1220', '#60a5fa', '#10b981'] },
    groen: { label: 'Groen',  swatches: ['#020d0a', '#051a10', '#34d399', '#10b981'] },
    paars: { label: 'Paars',  swatches: ['#0d0a1a', '#12103a', '#c084fc', '#10b981'] },
    rood:  { label: 'Rood',   swatches: ['#0f0505', '#1a0808', '#f87171', '#ef4444'] },
  };

  window.THEME_NAMES = Object.keys(THEMES);

  /* Register custom theme if one was previously saved */
  var _savedCustom = _loadCustomVars();
  if (_savedCustom) {
    window.THEME_META.custom = {
      label: 'Eigen',
      swatches: [_savedCustom['--bg']||'#070b16', _savedCustom['--panel']||'#0b1220',
                 _savedCustom['--accent']||'#60a5fa', _savedCustom['--ok']||'#10b981'],
    };
    window.THEME_NAMES.push('custom');
  }

  window.applyTheme = function (name) {
    var theme;
    if (name === 'custom') {
      theme = _loadCustomVars() || THEMES.blauw;
    } else {
      theme = THEMES[name] || THEMES.blauw;
    }
    var root = document.documentElement;
    for (var k in theme) root.style.setProperty(k, theme[k]);
    root.setAttribute('data-theme', name);
    localStorage.setItem('theme', name);
    window._currentTheme = name;

    /* Font override — inject EB Garamond for oudgeld, reset for others */
    var fontOverride = document.getElementById('theme-font-override');
    if (!fontOverride) {
      fontOverride = document.createElement('style');
      fontOverride.id = 'theme-font-override';
      document.head.appendChild(fontOverride);
    }
    if (name === 'oudgeld') {
      fontOverride.textContent = "body{font-family:'EB Garamond',Georgia,serif!important}";
      if (!document.getElementById('font-eb-garamond')) {
        var link = document.createElement('link');
        link.id = 'font-eb-garamond';
        link.rel = 'stylesheet';
        link.href = 'https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;500;600;700&display=swap';
        document.head.appendChild(link);
      }
    } else {
      fontOverride.textContent = '';
    }
  };

  /* Returns a full vars object for a given theme (used by custom editor) */
  window.getThemeVars = function (name) {
    if (name === 'custom') return _loadCustomVars() || THEMES.blauw;
    return THEMES[name] || THEMES.blauw;
  };

  /* Save a custom theme and make it selectable */
  window.saveCustomTheme = function (vars) {
    localStorage.setItem('theme-custom', JSON.stringify(vars));
    window.THEME_META.custom = {
      label: 'Eigen',
      swatches: [vars['--bg']||'#070b16', vars['--panel']||'#0b1220',
                 vars['--accent']||'#60a5fa', vars['--ok']||'#10b981'],
    };
    if (window.THEME_NAMES.indexOf('custom') === -1) window.THEME_NAMES.push('custom');
    window.applyTheme('custom');
  };

  /* Apply immediately on load — blocks first paint, so no flash */
  window.applyTheme(localStorage.getItem('theme') || 'blauw');

  // ---- Theme image overrides ----
  function _loadThemeImages() {
    try { var s = localStorage.getItem('theme-images'); return s ? JSON.parse(s) : {}; }
    catch(e) { return {}; }
  }

  function _applyLogo() {
    if (window._pendingLogoUrl) {
      document.querySelectorAll('img.logo').forEach(function(img) {
        img.src = window._pendingLogoUrl;
      });
    }
    /* Re-run promo tile wiring after DOM is ready */
    var saved = _loadThemeImages();
    var promoTile = document.getElementById('promo-tile');
    var promoImg  = document.getElementById('promo-img');
    var container = document.getElementById('mainContainer');
    if (promoTile && promoImg && container) {
      if (saved['--promo-image']) {
        promoImg.src = saved['--promo-image'];
        promoTile.classList.add('visible');
        container.classList.add('has-promo');
      } else {
        promoTile.classList.remove('visible');
        container.classList.remove('has-promo');
      }
    }
  }

  window.applyThemeImages = function(images) {
    var style = document.getElementById('theme-image-override');
    if (!style) {
      style = document.createElement('style');
      style.id = 'theme-image-override';
      document.head.appendChild(style);
    }
    var css = '';
    if (images['--bg-image']) {
      css += 'body::before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;'
           + 'background-image:url(' + images['--bg-image'] + ');background-size:cover;'
           + 'background-position:center;background-repeat:no-repeat;opacity:0.12;}';
    }
    if (images['--header-image']) {
      css += 'header{background-image:url(' + images['--header-image'] + ')!important;'
           + 'background-size:cover;background-position:center;background-repeat:no-repeat;}';
    }
    style.textContent = css;
    window._pendingLogoUrl = images['--logo-url'] || null;
    _applyLogo();

    /* Promo tile (koersbord) */
    var promoTile = document.getElementById('promo-tile');
    var promoImg  = document.getElementById('promo-img');
    var container = document.getElementById('mainContainer');
    if (promoTile && promoImg && container) {
      if (images['--promo-image']) {
        promoImg.src = images['--promo-image'];
        promoTile.classList.add('visible');
        container.classList.add('has-promo');
      } else {
        promoTile.classList.remove('visible');
        container.classList.remove('has-promo');
      }
    }
  };

  window.saveThemeImages = function(images) {
    localStorage.setItem('theme-images', JSON.stringify(images));
    window.applyThemeImages(images);
  };

  window.loadThemeImages = _loadThemeImages;

  document.addEventListener('DOMContentLoaded', _applyLogo);
  window.applyThemeImages(_loadThemeImages());
})();
