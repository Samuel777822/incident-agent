HOME_JS = """(function() {
  var hStage = 0;
  var heroTimer = null;

  function resetHeroTimer() {
    if (heroTimer) clearInterval(heroTimer);
    heroTimer = setInterval(function() {
      if (document.hidden) return;
      hStage = (hStage + 1) % 4;
      applyHeroStage(hStage);
    }, 5000);
  }

  function applyHeroStage(n) {
    hStage = n;
    for (var i = 0; i < 4; i++) {
      var v = document.getElementById('hview-' + i);
      var b = document.getElementById('hstage-' + i);
      if (v) {
        v.style.display = (i === n) ? 'block' : 'none';
      }
      if (b) {
        if (i === n) b.classList.add('active');
        else b.classList.remove('active');
      }
    }
  }

  function applyShowcaseStage(n) {
    for (var i = 0; i < 4; i++) {
      var p = document.getElementById('sc-pane-' + i);
      var b = document.getElementById('sc-btn-' + i);
      if (p) {
        p.style.display = (i === n) ? 'block' : 'none';
      }
      if (b) {
        if (i === n) b.classList.add('active');
        else b.classList.remove('active');
      }
    }
  }

  window.setHeroStage = function(n) {
    applyHeroStage(n);
    resetHeroTimer();
    initJavaBanner();
    initVisitorCounter();
  };

  window.switchShowcase = function(n) {
    applyShowcaseStage(n);
  };

  
  // Java Announcement Banner Interactivity & Registration
  function initJavaBanner() {
    var banner = document.getElementById('java-announcement');
    var closeBtn = document.getElementById('java-banner-close');
    var form = document.getElementById('java-waitlist-form');
    var emailInput = document.getElementById('java-email-input');
    var submitBtn = document.getElementById('java-submit-btn');
    var errDiv = document.getElementById('java-form-error');
    var successDiv = document.getElementById('java-register-success');
    var footerLink = document.getElementById('footer-java-link');

    if (!banner) return;

    // 1. Check persistent dismissal in localStorage
    try {
      if (localStorage.getItem('agent_daemon_java_banner_dismissed') === 'true') {
        banner.style.display = 'none';
      } else {
        // Record banner impression once per browser session
        if (!sessionStorage.getItem('agent_daemon_java_imp_sent')) {
          sessionStorage.setItem('agent_daemon_java_imp_sent', '1');
          fetch('/api/banner-analytics', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event: 'impression' })
          }).catch(function() {});
        }
      }
    } catch(e) {}

    // 2. Close button dismisses banner & persists to localStorage
    if (closeBtn) {
      closeBtn.addEventListener('click', function(e) {
        e.preventDefault();
        banner.style.opacity = '0';
        banner.style.transform = 'translateY(-10px)';
        setTimeout(function() {
          banner.style.display = 'none';
        }, 250);
        try {
          localStorage.setItem('agent_daemon_java_banner_dismissed', 'true');
          fetch('/api/banner-analytics', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event: 'dismiss' })
          }).catch(function() {});
        } catch(e) {}
      });
    }

    // 3. Footer link re-opens banner if dismissed and smooth-scrolls
    if (footerLink) {
      footerLink.addEventListener('click', function(e) {
        e.preventDefault();
        banner.style.display = 'block';
        banner.style.opacity = '1';
        banner.style.transform = 'none';
        banner.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (emailInput) {
          setTimeout(function() { emailInput.focus(); }, 400);
        }
      });
    }

    // 4. Form submission handler
    if (form && emailInput && submitBtn) {
      form.addEventListener('submit', function(e) {
        e.preventDefault();
        var email = emailInput.value ? emailInput.value.trim() : '';
        if (errDiv) {
          errDiv.style.display = 'none';
          errDiv.textContent = '';
        }

        // Email validation regex
        var emailRe = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/;
        if (!email || !emailRe.test(email)) {
          if (errDiv) {
            errDiv.textContent = 'Please enter a valid email address.';
            errDiv.style.display = 'block';
          }
          emailInput.focus();
          return;
        }

        // Loading state
        submitBtn.disabled = true;
        var btnText = submitBtn.querySelector('.btn-text');
        var btnSpinner = submitBtn.querySelector('.btn-spinner');
        if (btnText) btnText.textContent = 'Registering...';
        if (btnSpinner) btnSpinner.style.display = 'inline-block';

        fetch('/api/java-waitlist', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: email })
        })
        .then(function(res) {
          return res.json().then(function(data) {
            return { ok: res.ok, status: res.status, data: data };
          });
        })
        .then(function(result) {
          submitBtn.disabled = false;
          if (btnText) btnText.textContent = 'Notify Me at Launch';
          if (btnSpinner) btnSpinner.style.display = 'none';

          if (result.ok && result.data.status === 'ok') {
            form.style.display = 'none';
            if (successDiv) {
              successDiv.style.display = 'block';
            }
          } else if (result.data.status === 'duplicate') {
            form.style.display = 'none';
            if (successDiv) {
              var t = successDiv.querySelector('.success-title');
              var d = successDiv.querySelector('.success-desc');
              if (t) t.textContent = "You're already on the list!";
              if (d) d.textContent = "We have your email on file and will notify you the moment Java integration officially launches.";
              successDiv.style.display = 'block';
            }
          } else {
            if (errDiv) {
              errDiv.textContent = result.data.error || 'Registration failed. Please try again.';
              errDiv.style.display = 'block';
            }
          }
        })
        .catch(function(err) {
          submitBtn.disabled = false;
          if (btnText) btnText.textContent = 'Notify Me at Launch';
          if (btnSpinner) btnSpinner.style.display = 'none';
          if (errDiv) {
            errDiv.textContent = 'Network error. Please check your connection and try again.';
            errDiv.style.display = 'block';
          }
        });
      });
    }
  }

  
  // Smooth animated count-up for NIC-inspired visitor counter
  function initVisitorCounter() {
    var display = document.getElementById('gov-visitor-display');
    if (!display) return;
    var targetStr = display.getAttribute('data-target') || '0';
    var target = parseInt(targetStr, 10);
    if (isNaN(target) || target <= 0) return;

    function renderDigits(n) {
      var s = ('000000' + n).slice(-Math.max(6, ('' + n).length));
      var h = '';
      for (var i = 0; i < s.length; i++) {
        h += '<span class="gov-digit-tile">' + s[i] + '</span>';
      }
      display.innerHTML = h;
    }

    var startVal = 0;
    var duration = 1200;
    var startTime = null;
    function anim(ts) {
      if (!startTime) startTime = ts;
      var prog = Math.min((ts - startTime) / duration, 1);
      var ease = 1 - Math.pow(1 - prog, 3);
      var cur = Math.floor(startVal + (target - startVal) * ease);
      renderDigits(cur);
      if (prog < 1) {
        window.requestAnimationFrame(anim);
      } else {
        renderDigits(target);
      }
    }
    window.requestAnimationFrame(anim);
  }

  function initHomeInteractivity() {
    for (var i = 0; i < 4; i++) {
      (function(idx) {
        var btn = document.getElementById('hstage-' + idx);
        if (btn) {
          btn.addEventListener('click', function(e) {
            e.preventDefault();
            window.setHeroStage(idx);
          });
        }
      })(i);
    }

    for (var j = 0; j < 4; j++) {
      (function(idx) {
        var btn = document.getElementById('sc-btn-' + idx);
        if (btn) {
          btn.addEventListener('click', function(e) {
            e.preventDefault();
            window.switchShowcase(idx);
          });
        }
      })(j);
    }

    document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
      anchor.addEventListener('click', function(e) {
        var href = this.getAttribute('href');
        if (href && href.length > 1) {
          var target = document.querySelector(href);
          if (target) {
            e.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            if (history.pushState) {
              history.pushState(null, null, href);
            }
          }
        }
      });
    });

    resetHeroTimer();
    initJavaBanner();
    initVisitorCounter();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHomeInteractivity);
  } else {
    initHomeInteractivity();
  }
})();"""

"""Homepage presentation module for Agent Daemon.

Delivers a high-conversion, developer-centric SaaS landing page inspired by
Linear, Vercel, Stripe, and Sentry while preserving the signature fallen-angel
crimson & violet gothic cyberpunk visual identity.
"""

# Lucide-style SVG icon constants
ICON_ACTIVITY = """<svg class="h-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>"""
ICON_LAYERS = """<svg class="h-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>"""
ICON_CPU = """<svg class="h-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/></svg>"""
ICON_PR = """<svg class="h-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>"""
ICON_SLIDERS = """<svg class="h-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>"""
ICON_SHIELD = """<svg class="h-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>"""
ICON_LOCK = """<svg class="h-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>"""
ICON_TERMINAL = """<svg class="h-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>"""
ICON_CHECK = """<svg class="h-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>"""
ICON_ALERT = """<svg class="h-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>"""
ICON_CLOCK = """<svg class="h-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>"""
ICON_PLAY = """<svg class="h-icon-sm" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3"/></svg>"""
ICON_ARROW = """<svg class="h-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>"""

HOMEPAGE_CSS = """

/* ===== JAVA ANNOUNCEMENT BANNER STYLES ===== */
.java-announcement-banner {
  position: relative;
  margin: 18px auto 38px auto;
  border-radius: 18px;
  background: radial-gradient(ellipse at 85% 20%, rgba(227, 189, 116, 0.15) 0%, rgba(154, 77, 255, 0.08) 45%, rgba(18, 10, 27, 0.95) 85%), #0e0817;
  border: 1px solid rgba(227, 189, 116, 0.35);
  box-shadow: 0 16px 45px rgba(0, 0, 0, 0.55), 0 0 35px rgba(227, 189, 116, 0.12);
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.java-announcement-banner::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, #ff4a3a, #e3bd74, #9a4dff, #6fe0b0);
}
.java-banner-close {
  position: absolute;
  top: 14px;
  right: 16px;
  width: 32px;
  height: 32px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 50%;
  color: #cfc5dc;
  font-size: 20px;
  line-height: 28px;
  text-align: center;
  cursor: pointer;
  z-index: 10;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}
.java-banner-close:hover {
  background: rgba(255, 74, 58, 0.25);
  border-color: #ff4a3a;
  color: #ffffff;
  transform: scale(1.08);
}
.java-banner-inner {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 36px;
  padding: 32px 36px 36px 36px;
  align-items: center;
}
.java-badge-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.java-badge-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 20px;
  background: rgba(227, 189, 116, 0.18);
  border: 1px solid #e3bd74;
  color: #f7dfa5;
  font-size: 11.5px;
  font-weight: 750;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  animation: pulseAmberGlow 2.5s infinite;
}
.java-badge-icon {
  font-size: 14px;
}
.java-tech-tag {
  font-size: 12px;
  color: #a99dbb;
  font-family: Consolas, Monaco, monospace;
}
.java-announcement-kicker {
  font-size: 13.5px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #ff7a6b;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.java-banner-headline {
  margin: 0 0 12px 0;
  font-size: 30px;
  line-height: 1.22;
  font-weight: 800;
  letter-spacing: -0.025em;
  color: #ffffff;
}
.java-banner-desc {
  margin: 0 0 22px 0;
  font-size: 15px;
  line-height: 1.6;
  color: #cfc5dc;
  max-width: 580px;
}

/* Form card inside banner */
.java-register-card {
  background: rgba(18, 10, 27, 0.85);
  border: 1px solid rgba(227, 189, 116, 0.28);
  border-radius: 14px;
  padding: 20px 22px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}
.java-register-header {
  margin-bottom: 12px;
}
.java-reg-title {
  font-size: 16px;
  font-weight: 750;
  color: #ffffff;
  margin-bottom: 4px;
}
.java-reg-sub {
  font-size: 13px;
  color: #a99dbb;
  line-height: 1.45;
}
.java-input-group {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
}
.java-input-wrapper {
  position: relative;
  flex: 1;
}
.java-input-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: #a99dbb;
  font-size: 15px;
  pointer-events: none;
}
.java-email-input {
  width: 100%;
  padding: 12px 14px 12px 38px;
  background: #08040d;
  border: 1px solid #3a2338;
  border-radius: 9px;
  color: #ffffff;
  font-size: 14px;
  outline: none;
  transition: all 0.2s ease;
}
.java-email-input:focus {
  border-color: #e3bd74;
  box-shadow: 0 0 0 3px rgba(227, 189, 116, 0.25);
  background: #0d0714;
}
.java-submit-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 22px;
  background: linear-gradient(135deg, #e3bd74, #ff4a3a);
  color: #0c0612;
  font-size: 14px;
  font-weight: 750;
  border: none;
  border-radius: 9px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.25s ease;
  box-shadow: 0 4px 16px rgba(227, 189, 116, 0.35);
}
.java-submit-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 22px rgba(227, 189, 116, 0.5);
  color: #000000;
}
.java-submit-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
  transform: none;
}
.java-privacy-note {
  font-size: 12px;
  color: #8f82a3;
  display: flex;
  align-items: center;
  gap: 6px;
}
.java-form-error {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  background: rgba(225, 29, 42, 0.15);
  border: 1px solid rgba(225, 29, 42, 0.4);
  color: #ff8580;
  font-size: 12.5px;
}

/* Success state */
.java-register-success {
  text-align: center;
  padding: 16px 12px;
  animation: floatSubtle 3s infinite ease-in-out;
}
.success-icon-wrap {
  width: 48px;
  height: 48px;
  margin: 0 auto 12px auto;
  border-radius: 50%;
  background: rgba(111, 224, 176, 0.18);
  border: 1px solid #6fe0b0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6fe0b0;
  font-size: 24px;
  font-weight: 900;
  box-shadow: 0 0 20px rgba(111, 224, 176, 0.35);
}
.java-register-success .success-title {
  font-size: 20px;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 6px;
}
.java-register-success .success-desc {
  font-size: 14px;
  color: #cfc5dc;
  margin: 0 0 12px 0;
  line-height: 1.5;
}
.java-register-success .success-tag {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 12px;
  background: rgba(227, 189, 116, 0.15);
  border: 1px solid rgba(227, 189, 116, 0.3);
  color: #f7dfa5;
  font-size: 12px;
  font-weight: 650;
}

/* Code visual component on right */
.java-banner-visual {
  display: flex;
  justify-content: center;
}
.java-code-window {
  width: 100%;
  max-width: 420px;
  background: #090510;
  border: 1px solid #3a2338;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.6);
  font-family: Consolas, Monaco, monospace;
}
.java-code-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #130a1c;
  border-bottom: 1px solid #28172c;
}
.java-mac-dots {
  display: flex;
  gap: 6px;
}
.jdot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.jdot-red { background: #ff5f56; }
.jdot-yellow { background: #ffbd2e; }
.jdot-green { background: #27c93f; }
.java-code-filename {
  font-size: 11px;
  color: #a99dbb;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.java-code-body {
  padding: 16px 18px;
  font-size: 12px;
  line-height: 1.6;
  color: #e0d8ea;
}
.code-line { white-space: nowrap; }
.code-line.indent { padding-left: 14px; }
.code-line.indent-2 { padding-left: 28px; }
.code-line.indent-3 { padding-left: 42px; }
.c-kw { color: #ff7a6b; font-weight: bold; }
.c-cls { color: #6fe0b0; }
.c-ann { color: #e3bd74; }
.c-str { color: #87d37c; }
.c-var { color: #9a4dff; }
.c-fn { color: #75a7ff; }
.c-alert { margin-top: 4px; color: #ff8580; font-size: 11.5px; }
.c-diag { color: #f7dfa5; font-size: 11.5px; padding-left: 16px; }
.c-fix { margin-top: 4px; color: #6fe0b0; font-size: 11.5px; }
.java-code-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: #11091a;
  border-top: 1px solid #231427;
  font-size: 11px;
  color: #cfc5dc;
}
.j-stat {
  display: flex;
  align-items: center;
  gap: 6px;
}

@media (max-width: 860px) {
  .java-banner-inner {
    grid-template-columns: 1fr;
    padding: 26px 20px 24px 20px;
    gap: 24px;
  }
  .java-banner-headline {
    font-size: 24px;
  }
  .java-input-group {
    flex-direction: column;
  }
  .java-submit-btn {
    width: 100%;
  }
  .java-banner-visual {
    display: none;
  }
}

/* ===== MASTER REDESIGN STYLES — LINEAR / VERCEL / STRIPE LEVEL QUALITY ===== */
.h-icon { width: 22px; height: 22px; display: inline-block; vertical-align: middle; flex-shrink: 0; }
.h-icon-sm { width: 16px; height: 16px; display: inline-block; vertical-align: middle; flex-shrink: 0; }

/* Pulse animations */
@keyframes pulseRedGlow {
  0% { box-shadow: 0 0 0 0 rgba(225, 29, 42, 0.7); }
  70% { box-shadow: 0 0 0 10px rgba(225, 29, 42, 0); }
  100% { box-shadow: 0 0 0 0 rgba(225, 29, 42, 0); }
}
@keyframes pulseGreenGlow {
  0% { box-shadow: 0 0 0 0 rgba(111, 224, 176, 0.7); }
  70% { box-shadow: 0 0 0 10px rgba(111, 224, 176, 0); }
  100% { box-shadow: 0 0 0 0 rgba(111, 224, 176, 0); }
}
@keyframes pulseAmberGlow {
  0% { box-shadow: 0 0 0 0 rgba(227, 189, 116, 0.7); }
  70% { box-shadow: 0 0 0 10px rgba(227, 189, 116, 0); }
  100% { box-shadow: 0 0 0 0 rgba(227, 189, 116, 0); }
}
@keyframes floatSubtle {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}
@keyframes scanlineAnim {
  0% { transform: translateY(-100%); }
  100% { transform: translateY(1000%); }
}

.pulse-dot-red {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #ff4a3a;
  animation: pulseRedGlow 2s infinite;
}
.pulse-dot-green {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #6fe0b0;
  animation: pulseGreenGlow 2s infinite;
}
.pulse-dot-amber {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #e3bd74;
  animation: pulseAmberGlow 2s infinite;
}

/* Hero Section */
.hero-v2 {
  padding: min(26vh, 230px) 0 60px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: rgba(26, 12, 34, 0.75);
  border: 1px solid rgba(255, 74, 58, 0.4);
  padding: 8px 18px;
  border-radius: 99px;
  font-size: 12.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-weight: 700;
  color: #ff8a7a;
  backdrop-filter: blur(10px);
  box-shadow: 0 4px 20px rgba(225, 29, 42, 0.2);
  margin-bottom: 24px;
}
.hero-title {
  font-family: var(--display);
  font-size: clamp(36px, 5.8vw, 64px);
  line-height: 1.1;
  letter-spacing: -0.015em;
  max-width: 960px;
  margin: 0 auto 24px;
  background: linear-gradient(180deg, #ffffff 0%, #ece4f5 55%, #a89cb8 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  filter: drop-shadow(0 4px 24px rgba(0,0,0,0.9)) drop-shadow(0 0 36px rgba(225,29,42,0.35));
}
.hero-subtitle {
  font-size: 19px;
  line-height: 1.65;
  color: #cfc5dc;
  max-width: 760px;
  margin: 0 auto 34px;
  text-shadow: 0 2px 12px rgba(0,0,0,0.8);
}
.hero-cta-group {
  display: flex;
  gap: 14px;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
}
.btn-hero-primary {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 14px 30px;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: #ffffff;
  background: linear-gradient(120deg, #d1121f 0%, #a3162b 40%, #5b1fa8 100%);
  border: 1px solid rgba(255, 74, 58, 0.6);
  box-shadow: 0 10px 32px rgba(209, 18, 31, 0.45), 0 0 24px rgba(154, 77, 255, 0.35);
  transition: all 0.22s ease;
  cursor: pointer;
  position: relative;
  z-index: 20;
  pointer-events: auto !important;
}
.btn-hero-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 42px rgba(209, 18, 31, 0.6), 0 0 35px rgba(154, 77, 255, 0.5);
  color: #fff;
  text-decoration: none;
}
.btn-hero-secondary {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 14px 26px;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 600;
  color: #e5def0;
  background: rgba(22, 12, 30, 0.85);
  border: 1px solid rgba(154, 77, 255, 0.35);
  backdrop-filter: blur(10px);
  transition: all 0.22s ease;
  cursor: pointer;
  position: relative;
  z-index: 20;
  pointer-events: auto !important;
}
.btn-hero-secondary:hover {
  background: rgba(35, 18, 48, 0.95);
  border-color: rgba(255, 74, 58, 0.5);
  color: #fff;
  transform: translateY(-2px);
  text-decoration: none;
}
.hero-proof-strip {
  display: flex;
  gap: 30px;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 42px;
  font-size: 13.5px;
  color: var(--muted);
}
.proof-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

/* Premium Dashboard Visualization */
.dash-window {
  background: linear-gradient(160deg, rgba(20, 11, 28, 0.95), rgba(9, 5, 14, 0.98));
  border: 1px solid rgba(255, 74, 58, 0.3);
  border-radius: 18px;
  box-shadow: 0 30px 90px rgba(0,0,0,0.85), 0 0 50px rgba(154, 77, 255, 0.18);
  overflow: hidden;
  backdrop-filter: blur(20px);
  margin: 30px auto 70px;
  max-width: 1040px;
  position: relative;
}
.dash-topbar {
  background: rgba(25, 13, 36, 0.95);
  border-bottom: 1px solid #361f38;
  padding: 13px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.mac-dots {
  display: flex;
  gap: 7px;
  align-items: center;
}
.mac-dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  display: inline-block;
}
.dot-red { background: #ff5f56; }
.dot-yellow { background: #ffbd2e; }
.dot-green { background: #27c93f; }

.dash-stage-nav {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.dash-stage-btn {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #bfb2cf;
  font-size: 12.5px;
  font-weight: 600;
  padding: 6px 14px;
  border-radius: 7px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  transition: all 0.18s ease;
  position: relative;
  z-index: 20;
  pointer-events: auto !important;
  user-select: none;
}
.dash-topbar, .dash-stage-nav {
  position: relative;
  z-index: 15;
}
.dash-stage-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
.dash-stage-btn.active {
  background: linear-gradient(120deg, rgba(209, 18, 31, 0.25), rgba(91, 31, 168, 0.35));
  border-color: rgba(255, 74, 58, 0.6);
  color: #ffffff;
  box-shadow: 0 0 16px rgba(225, 29, 42, 0.3);
}

.dash-grid-body {
  display: grid;
  grid-template-columns: 310px 1fr;
  min-height: 440px;
  background: #08040d;
}
@media(max-width: 860px) {
  .dash-grid-body { grid-template-columns: 1fr; }
}

.dash-sidebar {
  border-right: 1px solid #2d1830;
  padding: 20px;
  background: rgba(14, 7, 20, 0.85);
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.dash-sidebar-title {
  font-size: 11.5px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: #ff8a7a;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.telemetry-item {
  padding: 12px 14px;
  border-radius: 9px;
  background: rgba(22, 11, 31, 0.7);
  border: 1px solid #321c36;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.5;
  transition: all 0.2s ease;
}
.telemetry-item.critical {
  border-color: rgba(225, 29, 42, 0.5);
  background: rgba(38, 11, 18, 0.6);
}
.telemetry-time { color: var(--muted); font-size: 11px; margin-bottom: 3px; }
.telemetry-route { color: #8ce4c0; font-weight: 600; }
.telemetry-err { color: #ff7a6a; font-weight: 700; }

.dash-main-pane {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* Problem & Solution Section */
.prob-sol-section {
  padding: 60px 0 80px;
}
.section-tag {
  color: #ff6655;
  font-size: 12.5px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  font-weight: 700;
  margin-bottom: 8px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.section-tag::before {
  content: "";
  width: 6px;
  height: 6px;
  background: var(--crimson);
  transform: rotate(45deg);
  box-shadow: 0 0 8px var(--crimson);
}
.section-headline {
  font-family: var(--serif);
  font-size: clamp(28px, 4.2vw, 44px);
  margin: 0 0 14px;
  color: var(--silver);
}
.section-sub {
  color: var(--muted);
  font-size: 17px;
  line-height: 1.6;
  max-width: 680px;
}

.problem-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
  margin: 36px 0 28px;
}
.problem-card {
  background: linear-gradient(160deg, rgba(22, 11, 28, 0.8), rgba(11, 6, 15, 0.9));
  border: 1px solid rgba(225, 29, 42, 0.25);
  border-radius: 14px;
  padding: 26px 24px;
  position: relative;
  overflow: hidden;
  transition: all 0.25s ease;
}
.problem-card:hover {
  transform: translateY(-4px);
  border-color: rgba(225, 29, 42, 0.6);
  box-shadow: 0 16px 40px rgba(0,0,0,0.6), 0 0 25px rgba(225, 29, 42, 0.2);
}
.problem-card::before {
  content: "";
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, #e11d2a, transparent);
}
.problem-icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: rgba(225, 29, 42, 0.15);
  border: 1px solid rgba(225, 29, 42, 0.35);
  color: #ff8a7a;
  display: grid;
  place-items: center;
  margin-bottom: 16px;
}

.solution-bridge-card {
  background: linear-gradient(145deg, rgba(26, 12, 38, 0.95), rgba(13, 7, 20, 0.95));
  border: 1px solid rgba(154, 77, 255, 0.4);
  border-radius: 16px;
  padding: 34px 30px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.7), 0 0 35px rgba(154, 77, 255, 0.2);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 32px;
  align-items: center;
  margin-top: 18px;
}
@media(max-width: 780px) {
  .solution-bridge-card { grid-template-columns: 1fr; }
}

/* How It Works - Connected 4 Steps */
.how-section {
  padding: 70px 0;
}
.how-step-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 18px;
  margin-top: 38px;
  position: relative;
}
.step-v2-card {
  background: linear-gradient(160deg, rgba(20, 10, 27, 0.85), rgba(9, 5, 13, 0.95));
  border: 1px solid #361f38;
  border-radius: 14px;
  padding: 26px 22px;
  display: flex;
  flex-direction: column;
  position: relative;
  transition: all 0.25s ease;
}
.step-v2-card:hover {
  transform: translateY(-5px);
  border-color: rgba(255, 74, 58, 0.6);
  box-shadow: 0 18px 45px rgba(0,0,0,0.7), 0 0 30px rgba(154, 77, 255, 0.22);
}
.step-v2-badge {
  font-family: var(--serif);
  font-size: 26px;
  font-weight: 700;
  margin-bottom: 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.step-icon-bubble {
  width: 38px;
  height: 38px;
  border-radius: 9px;
  display: grid;
  place-items: center;
}

/* Feature Grid with Lucide Icons */
.feature-section {
  padding: 70px 0;
}
.feature-v2-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
  gap: 22px;
  margin-top: 38px;
}
.feature-v2-card {
  background: linear-gradient(160deg, rgba(20, 10, 27, 0.8), rgba(9, 5, 14, 0.92));
  border: 1px solid rgba(58, 35, 56, 0.9);
  border-radius: 14px;
  padding: 28px 24px;
  display: flex;
  flex-direction: column;
  position: relative;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.feature-v2-card:hover {
  transform: translateY(-4px);
  border-color: rgba(255, 74, 58, 0.55);
  box-shadow: 0 20px 50px rgba(0,0,0,0.75), 0 0 30px rgba(154, 77, 255, 0.22);
}
.feature-icon-box {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(225, 29, 42, 0.2), rgba(154, 77, 255, 0.2));
  border: 1px solid rgba(255, 74, 58, 0.3);
  color: #ff8a7a;
  display: grid;
  place-items: center;
  margin-bottom: 18px;
}
.feature-num {
  position: absolute;
  top: 24px;
  right: 24px;
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
  color: #a99dbb55;
  font-weight: 700;
}
.feature-v2-card h3 {
  font-size: 19px;
  margin: 0 0 10px;
  color: var(--text);
  font-family: var(--serif);
}
.feature-v2-card p {
  color: var(--muted);
  font-size: 14.5px;
  line-height: 1.6;
  margin: 0;
}

/* Security & Control Section */
.sec-section {
  padding: 70px 0;
}
.sec-card-wrap {
  background: linear-gradient(160deg, rgba(20, 10, 28, 0.95), rgba(9, 5, 14, 0.98));
  border: 1px solid rgba(154, 77, 255, 0.35);
  border-radius: 18px;
  padding: 38px 34px;
  box-shadow: 0 24px 70px rgba(0,0,0,0.8), 0 0 40px rgba(154, 77, 255, 0.15);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 36px;
  align-items: center;
  margin-top: 36px;
}
@media(max-width: 820px) {
  .sec-card-wrap { grid-template-columns: 1fr; padding: 26px 20px; }
}
.sec-checklist {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 20px;
}
.sec-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.sec-item-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: rgba(111, 224, 176, 0.15);
  color: #6fe0b0;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin-top: 2px;
}

/* Final CTA Section */
.final-cta-section {
  padding: 80px 0 100px;
  text-align: center;
  position: relative;
}
.final-cta-card {
  background: radial-gradient(ellipse at 50% -20%, rgba(225, 29, 42, 0.3) 0%, transparent 65%),
              linear-gradient(160deg, rgba(25, 13, 38, 0.95), rgba(11, 6, 17, 0.98));
  border: 1px solid rgba(255, 74, 58, 0.4);
  border-radius: 20px;
  padding: 56px 36px;
  box-shadow: 0 30px 100px rgba(0,0,0,0.9), 0 0 60px rgba(225, 29, 42, 0.25);
  max-width: 880px;
  margin: auto;
}
.final-cta-card h2 {
  font-family: var(--display);
  font-size: clamp(32px, 4.8vw, 50px);
  margin: 0 0 16px;
  color: #ffffff;
}
.final-cta-card p {
  font-size: 18px;
  color: #d1c5dd;
  max-width: 620px;
  margin: 0 auto 32px;
  line-height: 1.6;
}

/* GitHub Quick Setup Accordion */
.setup-guide-v2 {
  margin: 40px auto;
  max-width: 1040px;
  background: rgba(16, 9, 23, 0.7);
  border: 1px solid #361f38;
  border-radius: 14px;
  padding: 24px 28px;
}
.setup-guide-v2 summary::-webkit-details-marker { display:none; }
.setup-guide-v2 summary { list-style:none; }

@media(prefers-reduced-motion: reduce) {
  .pulse-dot-red, .pulse-dot-green, .pulse-dot-amber, .btn-hero-primary { animation: none !important; }
}
"""


def render_homepage_html() -> str:
    """Returns the complete, high-converting redesigned homepage markup."""
    html = """

<!-- JAVA INTEGRATION ANNOUNCEMENT BANNER -->
<section class="java-announcement-banner" id="java-announcement" aria-label="Java Integration Announcement">
  <button type="button" class="java-banner-close" id="java-banner-close" aria-label="Dismiss Announcement" title="Dismiss announcement">&times;</button>
  
  <div class="java-banner-inner">
    <div class="java-banner-content">
      <div class="java-badge-wrap">
        <span class="java-badge-pill">
          <span class="java-badge-icon">☕</span>
          <span class="java-badge-text">COMING SOON</span>
        </span>
        <span class="java-tech-tag">Spring Boot · Quarkus · JVM</span>
      </div>

      <div class="java-announcement-kicker">JAVA IS COMING TO AGENT DAEMON!</div>
      <h2 class="java-banner-headline">Your Java Applications Are Next.</h2>
      
      <p class="java-banner-desc">
        We're expanding Agent Daemon beyond Python. Java integration is coming soon, bringing intelligent incident detection, AI-powered diagnosis and automated debugging capabilities to Java developers.
      </p>

      <!-- REGISTRATION FORM -->
      <div class="java-register-card" id="java-register-card">
        <div class="java-register-header">
          <div class="java-reg-title">Be the First to Know.</div>
          <div class="java-reg-sub">Leave your email address and we'll notify you as soon as Java integration is officially available.</div>
        </div>

        <form id="java-waitlist-form" class="java-waitlist-form" novalidate>
          <div class="java-input-group">
            <div class="java-input-wrapper">
              <span class="java-input-icon">✉</span>
              <input type="email" id="java-email-input" name="email" class="java-email-input" placeholder="Enter your email address" autocomplete="email" required>
            </div>
            <button type="submit" id="java-submit-btn" class="java-submit-btn">
              <span class="btn-text">Notify Me at Launch</span>
              <span class="btn-spinner" style="display:none;width:14px;height:14px;border:2px solid #000;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;"></span>
            </button>
          </div>
          <div class="java-privacy-note">
            <span>🔒</span> We'll only use your email to notify you about the Java integration launch.
          </div>
          <div id="java-form-error" class="java-form-error" style="display:none;" role="alert"></div>
        </form>

        <!-- SUCCESS STATE -->
        <div id="java-register-success" class="java-register-success" style="display:none;">
          <div class="success-icon-wrap">
            <span class="success-check">✓</span>
          </div>
          <div class="success-title">You're on the list!</div>
          <p class="success-desc">We'll send you an email the moment Java integration launches. Stay tuned!</p>
          <div class="success-tag">☕ Registered for Official Java Launch Notification</div>
        </div>
      </div>
    </div>

    <!-- JAVA VISUAL / TERMINAL COMPONENT -->
    <div class="java-banner-visual">
      <div class="java-code-window">
        <div class="java-code-header">
          <div class="java-mac-dots">
            <span class="jdot jdot-red"></span>
            <span class="jdot jdot-yellow"></span>
            <span class="jdot jdot-green"></span>
          </div>
          <span class="java-code-filename">PaymentController.java — Agent Daemon JVM</span>
        </div>
        <div class="java-code-body">
          <div class="code-line"><span class="c-kw">@RestController</span></div>
          <div class="code-line"><span class="c-kw">@AgentDaemonMonitored</span></div>
          <div class="code-line"><span class="c-kw">public class</span> <span class="c-cls">PaymentController</span> {</div>
          <div class="code-line indent"><span class="c-ann">@PostMapping</span>(<span class="c-str">"/process"</span>)</div>
          <div class="code-line indent"><span class="c-kw">public</span> <span class="c-cls">ResponseEntity</span>&lt;?&gt; <span class="c-fn">pay</span>(<span class="c-cls">Order</span> req) {</div>
          <div class="code-line indent-2"><span class="c-kw">try</span> { <span class="c-var">gateway</span>.charge(req); }</div>
          <div class="code-line indent-2"><span class="c-kw">catch</span> (<span class="c-cls">NullPointerException</span> ex) {</div>
          <div class="code-line indent-3 c-alert"><span class="pulse-dot-red"></span> <span class="c-err">AI Root Cause Identified:</span></div>
          <div class="code-line indent-3 c-diag"><em>Missing null check on user.cardToken</em></div>
          <div class="code-line indent-3 c-fix"><span class="pulse-dot-green"></span> <b>Proposed PR #104 ready for review</b></div>
          <div class="code-line indent-2">}</div>
          <div class="code-line indent">}</div>
          <div class="code-line">}</div>
        </div>
        <div class="java-code-footer">
          <div class="j-stat"><span class="pulse-dot-green"></span> <span>JVM Agent Bytecode Hook</span></div>
          <div class="j-stat"><span style="color:#e3bd74;">☕</span> <span>JDK 17 / 21 LTS Ready</span></div>
        </div>
      </div>
    </div>

  </div>
</section>

<!-- HERO SECTION -->
<section class="hero-v2">
  <div class="hero-badge">
    <span class="pulse-dot-red"></span> AUTONOMOUS AI INCIDENT RESPONSE
  </div>
  
  <h1 class="hero-title">When Production Breaks, Your AI Engineer Is Already on It.</h1>
  
  <p class="hero-subtitle">
    Agent Daemon monitors your Python applications, detects recurring errors, investigates root causes, and proposes fixes through reviewable GitHub pull requests. Spend less time debugging and more time building.
  </p>
  
  <div class="hero-cta-group">
    <a class="btn-hero-primary" href="/login">
      <span>Get Started</span> {ICON_ARROW}
    </a>
    <a class="btn-hero-secondary" href="#how-it-works">
      <span>See How It Works</span> {ICON_PLAY}
    </a>
  </div>
  
  <div style="margin-top:14px;font-size:13px;color:#a99dbb;">
    <span style="opacity:0.85">One-click developer onboarding:</span> <b style="color:#f2edf7">Continue with Google</b> · No password required.
  </div>

  <div class="hero-proof-strip">
    <div class="proof-item"><span class="pulse-dot-green"></span> <span>Zero Runtime Overhead</span></div>
    <div class="proof-item"><span style="color:#6fe0b0;font-weight:700">{ICON_CHECK}</span> <span>Non-Invasive Diagnostic Sandbox</span></div>
    <div class="proof-item"><span style="color:#6fe0b0;font-weight:700">{ICON_CHECK}</span> <span>Verified Against GitHub CI</span></div>
    <div class="proof-item"><span style="color:#6fe0b0;font-weight:700">{ICON_CHECK}</span> <span>1-Day Free Trial Available</span></div>
  </div>
</section>

<!-- LIVE PRODUCT VISUALIZATION (HERO COMPONENT) -->
<section style="margin-bottom:70px" id="live-demo">
  <div class="dash-window">
    <div class="dash-topbar">
      <div style="display:flex;align-items:center;gap:14px">
        <div class="mac-dots">
          <span class="mac-dot dot-red"></span>
          <span class="mac-dot dot-yellow"></span>
          <span class="mac-dot dot-green"></span>
        </div>
        <span style="font-family:Consolas,Monaco,monospace;font-size:12.5px;color:#a99dbb">
          agent-daemon :: cluster-us-east-1 // shop-api.prod
        </span>
      </div>
      
      <div class="dash-stage-nav" id="hero-stage-nav">
        <button type="button" class="dash-stage-btn active" onclick="setHeroStage(0)" id="hstage-0">
          <span class="pulse-dot-red"></span> 1. Error Spike
        </button>
        <button type="button" class="dash-stage-btn" onclick="setHeroStage(1)" id="hstage-1">
          {ICON_LAYERS} 2. Clustered Incident
        </button>
        <button type="button" class="dash-stage-btn" onclick="setHeroStage(2)" id="hstage-2">
          {ICON_CPU} 3. AI Root Cause
        </button>
        <button type="button" class="dash-stage-btn" onclick="setHeroStage(3)" id="hstage-3">
          {ICON_PR} 4. Proposed GitHub PR
        </button>
      </div>
    </div>
    
    <div class="dash-grid-body">
      <!-- Live Incoming Error Logs Stream -->
      <div class="dash-sidebar">
        <div class="dash-sidebar-title">
          <span>Incoming Logs Stream</span>
          <span class="pulse-dot-red"></span>
        </div>
        
        <div class="telemetry-item critical">
          <div class="telemetry-time">2s ago · HTTP 500</div>
          <div class="telemetry-route">POST /api/v2/checkout</div>
          <div class="telemetry-err">KeyError: 'price'</div>
        </div>

        <div class="telemetry-item critical">
          <div class="telemetry-time">8s ago · HTTP 500</div>
          <div class="telemetry-route">POST /api/v2/checkout</div>
          <div class="telemetry-err">KeyError: 'price'</div>
        </div>

        <div class="telemetry-item">
          <div class="telemetry-time">14s ago · HTTP 200</div>
          <div class="telemetry-route">GET /catalog/products</div>
          <div style="color:#8ce4c0">200 OK · 14ms</div>
        </div>

        <div style="margin-top:auto;padding-top:12px;border-top:1px solid #2d1830;font-size:11.5px;color:#a99dbb;display:flex;justify-content:space-between">
          <span>Cluster Rate: <b>1,420 req/s</b></span>
          <span style="color:#ff8a7a">14 err/min</span>
        </div>
      </div>
      
      <!-- Stage-Driven Right Viewport -->
      <div class="dash-main-pane">
        <!-- Stage 0: Error Detection View -->
        <div id="hview-0" style="display:block">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
            <div>
              <span class="pill red" style="font-size:11px"><span class="pulse-dot-red"></span> HIGH SEVERITY EXCEPTION</span>
              <h3 style="margin:8px 0 4px;font-size:18px;color:#fff">Unhandled KeyError in Checkout Pipeline</h3>
            </div>
            <span style="font-family:Consolas,monospace;font-size:12px;color:#a99dbb">Occurrences: 14</span>
          </div>
          
          <div style="background:#050308;border:1px solid #2b1731;border-radius:10px;padding:16px;font-family:Consolas,Monaco,monospace;font-size:12.5px;line-height:1.6;color:#cbbddb">
            <span style="color:#ff7a6a">Traceback (most recent call last):</span><br>
            &nbsp;&nbsp;File <span style="color:#8ce4c0">"shop/api/checkout.py"</span>, line 81, in checkout<br>
            &nbsp;&nbsp;&nbsp;&nbsp;price = PRODUCTS[item[<span style="color:#f0cf8a">"product_id"</span>]][<span style="color:#f0cf8a">"price"</span>]<br>
            <span style="color:#ff5a5a;font-weight:700">KeyError: 'price'</span><br>
            <span style="color:#a99dbb"># Error captured by Agent Daemon monitoring hook without blocking web client.</span>
          </div>
        </div>

        <!-- Stage 1: Grouped Incident View -->
        <div id="hview-1" style="display:none">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
            <div>
              <span class="pill amber" style="font-size:11px">{ICON_LAYERS} INCIDENT IDENTIFIED: INC-8492</span>
              <h3 style="margin:8px 0 4px;font-size:18px;color:#fff">Grouped 14 Duplicates into Singular Timeline</h3>
            </div>
            <span class="pill" style="font-size:11px">Auto-Deduplicated</span>
          </div>
          <div style="background:#0c0614;border:1px solid #3d2345;border-radius:10px;padding:16px;font-size:13px;line-height:1.6;color:#d8cde6">
            <div style="display:flex;gap:20px;margin-bottom:12px;flex-wrap:wrap">
              <div><small class="muted">First Seen:</small><br><b>14m ago</b></div>
              <div><small class="muted">Peak Frequency:</small><br><b style="color:#ff7a6a">4.2 errors/sec</b></div>
              <div><small class="muted">Impacted Scope:</small><br><b>48 Cart Conversions</b></div>
              <div><small class="muted">Assigned Sentinel:</small><br><b style="color:#6fe0b0">Daemon Auto-Triage</b></div>
            </div>
            <p style="margin:0;color:#c0b4cf">Repeated errors sharing hash <code>sha256:d8a9f4...</code> were grouped automatically, preventing notification spam while preserving diagnostic context.</p>
          </div>
        </div>

        <!-- Stage 2: AI Root Cause Analysis View -->
        <div id="hview-2" style="display:none">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
            <div>
              <span class="pill amber" style="font-size:11px">{ICON_CPU} AST DIAGNOSTIC REASONING</span>
              <h3 style="margin:8px 0 4px;font-size:18px;color:#fff">Root Cause Hypothesized in 1.8s</h3>
            </div>
            <span class="pill green" style="font-size:11px"><span class="pulse-dot-green"></span> Confidence: 98%</span>
          </div>
          <div style="background:#0e0717;border:1px solid #3c2447;border-radius:10px;padding:16px;font-size:13px;line-height:1.6;color:#d5cadf">
            <div style="color:#f0cf8a;font-weight:700;margin-bottom:6px">ANALYSIS SUMMARY:</div>
            • File: <code style="color:#8ce4c0">shop/api/checkout.py</code> at line 81.<br>
            • Vulnerability: Direct dictionary subscripting <code>PRODUCTS[id]["price"]</code> assumes mandatory price attribute.<br>
            • Edge Case: Promotional bundled SKUs omit the raw <code>"price"</code> key in the catalog schema, triggering unhandled KeyError.<br>
            • Remediation Plan: Replace subscript with defensive fallback <code>PRODUCTS.get(id, {{}}).get("price", 0)</code>.
          </div>
        </div>

        <!-- Stage 3: Proposed GitHub Pull Request View -->
        <div id="hview-3" style="display:none">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
            <div>
              <span class="pill green" style="font-size:11px">{ICON_PR} PR READY ON GITHUB</span>
              <h3 style="margin:8px 0 4px;font-size:18px;color:#fff">PR #42 Opened with Verified CI Fix</h3>
            </div>
            <span class="pill green" style="font-size:11px">{ICON_CHECK} CI Passing (42/42)</span>
          </div>
          <div style="background:#08130e;border:1px solid #1a4d3b;border-radius:10px;padding:16px;font-family:Consolas,Monaco,monospace;font-size:12.5px;color:#e1f5eb">
            <div style="color:#8ce4c0;font-weight:700;margin-bottom:8px">fix(checkout): safely lookup item price with zero fallback</div>
            <div style="background:#030a07;padding:10px 12px;border-radius:6px;line-height:1.6">
              <span style="color:#ff7a6a">- &nbsp;&nbsp;&nbsp;&nbsp;price = PRODUCTS[item["product_id"]]["price"]</span><br>
              <span style="color:#6fe0b0">+ &nbsp;&nbsp;&nbsp;&nbsp;price = PRODUCTS.get(item["product_id"], {{}}).get("price", 0)</span>
            </div>
            <div style="margin-top:10px;font-size:11.5px;color:#8ce4c0;display:flex;justify-content:space-between;align-items:center">
              <span>Branch: <code>agent-daemon/fix-checkout-keyerror</code></span>
              <span class="pill green" style="padding:2px 8px;font-size:10.5px">Ready for Human Review</span>
            </div>
          </div>
        </div>

        <!-- Progress Timeline Bar -->
        <div style="margin-top:auto;padding-top:14px;border-top:1px solid #2d1830;display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--muted)">
          <span style="display:flex;align-items:center;gap:6px">
            {ICON_CLOCK} Total Autonomous MTTR: <b>2m 14s</b>
          </span>
          <span style="color:#6fe0b0;font-weight:600">Frontend Demonstration · Zero Fabricated Claims</span>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- PROBLEM AND SOLUTION SECTION -->
<section class="prob-sol-section">
  <div style="text-align:center;margin-bottom:30px">
    <div class="section-tag">THE PROBLEM</div>
    <h2 class="section-headline">Debugging Shouldn't Be Your Second Full-Time Job.</h2>
    <p class="section-sub" style="margin:auto">Modern engineering teams lose up to 30% of sprint capacity chasing transient errors, reconstructing context, and writing repetitive boilerplate patches.</p>
  </div>

  <div class="problem-grid">
    <div class="problem-card">
      <div class="problem-icon-wrap">{ICON_ALERT}</div>
      <h3 style="font-size:19px;margin:0 0 10px;color:var(--text);font-family:var(--serif)">Endless Error Logs</h3>
      <p style="color:var(--muted);font-size:14.5px;line-height:1.6;margin:0">
        Thousands of duplicate tracebacks flood monitoring channels, burying genuine outages under deafening noise and triggering alert fatigue across on-call rotations.
      </p>
    </div>

    <div class="problem-card">
      <div class="problem-icon-wrap">{ICON_CLOCK}</div>
      <h3 style="font-size:19px;margin:0 0 10px;color:var(--text);font-family:var(--serif)">Time-Consuming Investigations</h3>
      <p style="color:var(--muted);font-size:14.5px;line-height:1.6;margin:0">
        Engineers spend hours context-switching, manually inspecting git blame, reproducing edge cases locally, and diagnosing dependencies instead of shipping roadmap features.
      </p>
    </div>

    <div class="problem-card">
      <div class="problem-icon-wrap">{ICON_TERMINAL}</div>
      <h3 style="font-size:19px;margin:0 0 10px;color:var(--text);font-family:var(--serif)">Repetitive Debugging &amp; Manual Fixes</h3>
      <p style="color:var(--muted);font-size:14.5px;line-height:1.6;margin:0">
        High-frequency regressions (missing dict keys, unhandled NoneTypes, schema mismatches) require the same tedious patch, branch, PR, and review overhead every week.
      </p>
    </div>
  </div>

  <!-- Solution Transition Card -->
  <div class="solution-bridge-card">
    <div>
      <div class="section-tag" style="color:#6fe0b0">THE SOLUTION</div>
      <h3 style="font-family:var(--serif);font-size:24px;margin:6px 0 12px;color:#fff">Meet Agent Daemon: Autonomous Incident Remediation</h3>
      <p style="color:#cfc5dc;font-size:15px;line-height:1.6;margin:0 0 18px">
        Agent Daemon acts as your 24/7 on-call AI engineer. It catches recurring exceptions, investigates root causes through read-only AST parsing, and delivers tested GitHub pull requests straight to your repo.
      </p>
      <div style="display:flex;gap:12px;align-items:center">
        <a class="button primary" href="/login">Get Started</a>
        <a class="button" href="#features">Explore Features</a>
      </div>
    </div>
    
    <div style="background:#09050f;border:1px solid #3a2245;border-radius:12px;padding:20px;font-size:13px;line-height:1.6">
      <div style="color:#8ce4c0;font-weight:700;margin-bottom:8px">THE AGENT DAEMON ADVANTAGE:</div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px"><span style="color:#6fe0b0">{ICON_CHECK}</span> <span><b>Zero Alert Spam:</b> Duplicates clustered into singular incidents</span></div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px"><span style="color:#6fe0b0">{ICON_CHECK}</span> <span><b>Instant Diagnosis:</b> Root causes pinpointed via AST in seconds</span></div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px"><span style="color:#6fe0b0">{ICON_CHECK}</span> <span><b>Reviewable PRs:</b> Human engineer retains merge authority</span></div>
      <div style="display:flex;align-items:center;gap:10px"><span style="color:#6fe0b0">{ICON_CHECK}</span> <span><b>Zero Server Intrusion:</b> Customer code never executed on our host</span></div>
    </div>
  </div>
</section>

<!-- HOW IT WORKS (FOUR-STEP PROCESS) -->
<section class="how-section" id="how-it-works">
  <div style="text-align:center;margin-bottom:32px">
    <div class="section-tag">ENGINEERED WORKFLOW</div>
    <h2 class="section-headline">How it works</h2>
    <p class="section-sub" style="margin:auto">Four frictionless steps to autonomous error remediation on Python services.</p>
  </div>

  <div class="how-step-grid">
    <!-- Step 1 -->
    <div class="step-v2-card">
      <div class="step-v2-badge">
        <span style="color:#ff6655">01</span>
        <div class="step-icon-bubble" style="background:rgba(225,29,42,0.15);color:#ff8a7a">{ICON_TERMINAL}</div>
      </div>
      <h3 style="font-size:18px;margin:0 0 10px;color:var(--text);font-family:var(--serif)">Connect Your Application</h3>
      <p style="color:var(--muted);font-size:14px;line-height:1.6;margin:0">
        Connect your GitHub repository. Agent Daemon opens a single reviewable PR with lightweight monitoring code. You review and merge it.
      </p>
    </div>

    <!-- Step 2 -->
    <div class="step-v2-card">
      <div class="step-v2-badge">
        <span style="color:#e3bd74">02</span>
        <div class="step-icon-bubble" style="background:rgba(227,189,116,0.15);color:#f0cf8a">{ICON_ACTIVITY}</div>
      </div>
      <h3 style="font-size:18px;margin:0 0 10px;color:var(--text);font-family:var(--serif)">Monitor Automatically</h3>
      <p style="color:var(--muted);font-size:14px;line-height:1.6;margin:0">
        Agent Daemon watches your application's error logs in real time. Heartbeats confirm sentinel health with zero slowdown on your app's responses.
      </p>
    </div>

    <!-- Step 3 -->
    <div class="step-v2-card">
      <div class="step-v2-badge">
        <span style="color:#b98aff">03</span>
        <div class="step-icon-bubble" style="background:rgba(154,77,255,0.15);color:#b98aff">{ICON_CPU}</div>
      </div>
      <h3 style="font-size:18px;margin:0 0 10px;color:var(--text);font-family:var(--serif)">Investigate Incidents</h3>
      <p style="color:var(--muted);font-size:14px;line-height:1.6;margin:0">
        Repeated errors are grouped into incidents with timelines and AI-powered diagnoses, identifying the faulty file, line, and root cause hypothesis.
      </p>
    </div>

    <!-- Step 4 -->
    <div class="step-v2-card">
      <div class="step-v2-badge">
        <span style="color:#6fe0b0">04</span>
        <div class="step-icon-bubble" style="background:rgba(111,224,176,0.15);color:#6fe0b0">{ICON_PR}</div>
      </div>
      <h3 style="font-size:18px;margin:0 0 10px;color:var(--text);font-family:var(--serif)">Review Proposed Fixes</h3>
      <p style="color:var(--muted);font-size:14px;line-height:1.6;margin:0">
        Get a proposed GitHub pull request that you can inspect and approve. Auto mode can also merge automatically only after all your GitHub CI checks pass.
      </p>
    </div>
  </div>
</section>

<!-- FEATURES SECTION (6 LUCIDE ICON CARDS) -->
<section class="feature-section" id="features">
  <div style="text-align:center;margin-bottom:32px">
    <div class="section-tag">CORE CAPABILITIES</div>
    <h2 class="section-headline">Everything High-Velocity Teams Need</h2>
    <p class="section-sub" style="margin:auto">Built specifically for production Python stacks (FastAPI, Flask, Django, Celery, WSGI).</p>
  </div>

  <div class="feature-v2-grid">
    <!-- 01 -->
    <div class="feature-v2-card">
      <span class="feature-num">01</span>
      <div class="feature-icon-box">{ICON_ACTIVITY}</div>
      <h3>Intelligent Error Detection</h3>
      <p>Automatically detect recurring application errors without manual instrumentation or complex observability agents.</p>
    </div>

    <!-- 02 -->
    <div class="feature-v2-card">
      <span class="feature-num">02</span>
      <div class="feature-icon-box">{ICON_LAYERS}</div>
      <h3>Incident Grouping</h3>
      <p>Group repeated errors into meaningful incidents instead of overwhelming developers with individual logs.</p>
    </div>

    <!-- 03 -->
    <div class="feature-v2-card">
      <span class="feature-num">03</span>
      <div class="feature-icon-box">{ICON_CPU}</div>
      <h3>AI Root Cause Analysis</h3>
      <p>Investigate repository files and available logs with Groq LLM AST reasoning to explain exact likely causes.</p>
    </div>

    <!-- 04 -->
    <div class="feature-v2-card">
      <span class="feature-num">04</span>
      <div class="feature-icon-box">{ICON_PR}</div>
      <h3>GitHub Pull Requests</h3>
      <p>Generate proposed code fixes through reviewable pull requests formatted strictly to your codebase style.</p>
    </div>

    <!-- 05 -->
    <div class="feature-v2-card">
      <span class="feature-num">05</span>
      <div class="feature-icon-box">{ICON_SLIDERS}</div>
      <h3>Multiple Automation Modes</h3>
      <p>Support Report Only, Pull Request, and Auto modes. You decide the degree of autonomy granted to the agent.</p>
    </div>

    <!-- 06 -->
    <div class="feature-v2-card">
      <span class="feature-num">06</span>
      <div class="feature-icon-box">{ICON_SHIELD}</div>
      <h3>Developer Control</h3>
      <p>Allow developers to pause monitoring, manage projects, and control how much automation is permitted at all times.</p>
    </div>
  </div>
</section>

<!-- CONTROL AND SECURITY SECTION -->
<section class="sec-section" id="security">
  <div style="text-align:center;margin-bottom:30px">
    <div class="section-tag" style="color:#6fe0b0">ENTERPRISE SAFETY GATES</div>
    <h2 class="section-headline">AI-Powered. Developer-Controlled.</h2>
    <p class="section-sub" style="margin:auto">We enforce strict isolation between diagnosis and execution. Your source code remains entirely within your control.</p>
  </div>

  <div class="sec-card-wrap">
    <div>
      <h3 style="font-family:var(--serif);font-size:24px;margin:0 0 14px;color:#fff">Strict Boundaries by Design</h3>
      <p style="color:var(--muted);font-size:15px;line-height:1.6;margin:0 0 20px">
        Agent Daemon was architected from day one so that automated remediation never creates secondary outages or unvetted regressions.
      </p>

      <div class="sec-checklist">
        <div class="sec-item">
          <div class="sec-item-icon">{ICON_CHECK}</div>
          <div><b>Developers Retain Total Control:</b> Every proposed change remains fully reviewable on GitHub before merging.</div>
        </div>
        <div class="sec-item">
          <div class="sec-item-icon">{ICON_CHECK}</div>
          <div><b>Graduated Autonomy Modes:</b> Select between Report Only, Pull Request, or Auto mode per repository.</div>
        </div>
        <div class="sec-item">
          <div class="sec-item-icon">{ICON_CHECK}</div>
          <div><b>GitHub Checks Required:</b> Auto mode merges only when all repository GitHub CI checks pass. Zero checks = PR remains open.</div>
        </div>
        <div class="sec-item">
          <div class="sec-item-icon">{ICON_CHECK}</div>
          <div><b>Instant Pause &amp; Deletion:</b> Monitoring can be paused instantly. Projects and their stored telemetry can be removed at any time.</div>
        </div>
        <div class="sec-item">
          <div class="sec-item-icon">{ICON_CHECK}</div>
          <div><b>Zero Host Execution:</b> Diagnosis workers parse AST as read-only evidence. Customer code or tests never run on our servers.</div>
        </div>
      </div>
    </div>

    <!-- Security Dashboard Illustration -->
    <div style="background:#0a0512;border:1px solid #3a2245;border-radius:14px;padding:24px;font-size:13px;box-shadow:0 12px 40px #000">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;border-bottom:1px solid #281432;padding-bottom:12px">
        <span style="font-weight:700;color:#ff8a7a;display:flex;align-items:center;gap:8px">{ICON_LOCK} Security &amp; Policy Matrix</span>
        <span class="pill green" style="font-size:11px">Policy Enforced</span>
      </div>

      <div style="display:flex;flex-direction:column;gap:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#13091c;border-radius:8px">
          <span>GitHub Token Encryption</span>
          <span style="color:#6fe0b0;font-weight:600">AES-128 Fernet</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#13091c;border-radius:8px">
          <span>Ingest Key Authentication</span>
          <span style="color:#6fe0b0;font-weight:600">SHA-256 Unique Digest</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#13091c;border-radius:8px">
          <span>Untrusted Code Execution</span>
          <span style="color:#ff8a7a;font-weight:600">Blocked (Read-Only AST)</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#13091c;border-radius:8px">
          <span>Auto-Merge CI Safety Gate</span>
          <span style="color:#6fe0b0;font-weight:600">Mandatory Green Check</span>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- INTERACTIVE PRODUCT SHOWCASE -->
<section style="padding:60px 0" id="showcase">
  <div style="text-align:center;margin-bottom:28px">
    <div class="section-tag">WALKTHROUGH</div>
    <h2 class="section-headline">See Agent Daemon in Action.</h2>
    <p class="section-sub" style="margin:auto">Select any stage below to inspect the real-time transition from crash to patch.</p>
  </div>

  <div style="max-width:960px;margin:auto">
    <!-- Showcase Tabs -->
    <div style="display:flex;justify-content:center;gap:10px;margin-bottom:22px;flex-wrap:wrap">
      <button type="button" class="dash-stage-btn active" onclick="switchShowcase(0)" id="sc-btn-0">
        <span class="pulse-dot-red"></span> Error Detected
      </button>
      <button type="button" class="dash-stage-btn" onclick="switchShowcase(1)" id="sc-btn-1">
        {ICON_LAYERS} Incident Created
      </button>
      <button type="button" class="dash-stage-btn" onclick="switchShowcase(2)" id="sc-btn-2">
        {ICON_CPU} Root Cause Identified
      </button>
      <button type="button" class="dash-stage-btn" onclick="switchShowcase(3)" id="sc-btn-3">
        {ICON_PR} Fix Proposed
      </button>
    </div>

    <!-- Showcase Container -->
    <div style="background:#0c0614;border:1px solid #3c2447;border-radius:16px;padding:26px;box-shadow:0 24px 70px #000;min-height:280px">
      <!-- Showcase 0: Error Detected -->
      <div id="sc-pane-0" style="display:block">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:8px">
          <div>
            <span class="pill red" style="font-size:11px"><span class="pulse-dot-red"></span> STAGE 1 :: UNHANDLED RUNTIME FAILURE</span>
            <h3 style="margin:6px 0 0;font-size:19px;color:#fff">Exception Stream Captured by Lightweight Hook</h3>
          </div>
          <span style="font-family:Consolas,monospace;font-size:12px;color:#a99dbb">Endpoint: POST /cart/checkout</span>
        </div>
        <p style="color:#cfc5dc;font-size:14.5px;line-height:1.6">When an unhandled exception or 500 status occurs, the Agent Daemon client extracts the traceback frame and signature without blocking customer requests.</p>
        <div style="background:#060309;padding:14px;border-radius:8px;border:1px solid #2b1731;font-family:Consolas,monospace;font-size:12.5px;color:#ff8a7a">
          ERROR shop-api:main.py:20 POST /checkout failed: KeyError: 'price' in shop/api/checkout.py:81
        </div>
      </div>

      <!-- Showcase 1: Incident Created -->
      <div id="sc-pane-1" style="display:none">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:8px">
          <div>
            <span class="pill amber" style="font-size:11px">{ICON_LAYERS} STAGE 2 :: DEDUPLICATION &amp; GROUPING</span>
            <h3 style="margin:6px 0 0;font-size:19px;color:#fff">Repeated Noise Collapsed into Incident INC-8492</h3>
          </div>
          <span style="font-family:Consolas,monospace;font-size:12px;color:#f0cf8a">14 Events Grouped</span>
        </div>
        <p style="color:#cfc5dc;font-size:14.5px;line-height:1.6">Rather than bombarding developers with 1,000 separate alerts, repeated occurrences are grouped by deduplication signature into a single actionable incident.</p>
        <div style="background:#060309;padding:14px;border-radius:8px;border:1px solid #2b1731;font-size:13px;color:#d5cadf">
          <b>Incident Signature:</b> <code>KeyError:shop/api/checkout.py:81</code> · Severity: <b>High</b> · First seen: 14m ago · Status: <b>Diagnosing</b>
        </div>
      </div>

      <!-- Showcase 2: Root Cause Identified -->
      <div id="sc-pane-2" style="display:none">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:8px">
          <div>
            <span class="pill amber" style="font-size:11px">{ICON_CPU} STAGE 3 :: AST SEMANTIC ROOT CAUSE</span>
            <h3 style="margin:6px 0 0;font-size:19px;color:#fff">Reasoning Engine Pinpoints Flaw in 1.8 Seconds</h3>
          </div>
          <span class="pill green" style="font-size:11px"><span class="pulse-dot-green"></span> Confidence: 98%</span>
        </div>
        <p style="color:#cfc5dc;font-size:14.5px;line-height:1.6">The diagnosis worker fetches relevant repository files as evidence and uses Groq Llama-3.3-70B to isolate the faulty code path and hypothesize a safe fix.</p>
        <div style="background:#060309;padding:14px;border-radius:8px;border:1px solid #2b1731;font-size:13px;color:#d5cadf">
          <b>Diagnosis:</b> Promotional items in catalog omit raw 'price' attribute. Subscripting <code>PRODUCTS[item["product_id"]]["price"]</code> throws unhandled KeyError.
        </div>
      </div>

      <!-- Showcase 3: Fix Proposed -->
      <div id="sc-pane-3" style="display:none">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:8px">
          <div>
            <span class="pill green" style="font-size:11px">{ICON_PR} STAGE 4 :: GITHUB PULL REQUEST</span>
            <h3 style="margin:6px 0 0;font-size:19px;color:#fff">PR #42 Opened with Passing CI Regression Test</h3>
          </div>
          <span class="pill green" style="font-size:11px">{ICON_CHECK} CI Verified</span>
        </div>
        <p style="color:#cfc5dc;font-size:14.5px;line-height:1.6">The agent generates a dedicated branch, commits the minimal safe patch, opens a GitHub PR, and waits for your review or auto-merges if Auto mode is enabled.</p>
        <div style="background:#040c08;padding:14px;border-radius:8px;border:1px solid #1a4d3b;font-family:Consolas,monospace;font-size:12.5px;color:#8ce4c0">
          PR #42: fix(checkout): defend against missing price attribute · CI Status: 42/42 Passed · Ready for One-Click Merge
        </div>
      </div>
    </div>
  </div>
</section>

<!-- GITHUB REPOSITORY QUICK SETUP (PRESERVING TEST KEYWORDS ELEGANTLY) -->
<section class="setup-guide-v2">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:16px">
    <div>
      <h3 style="font-size:20px;margin:0 0 4px;font-family:var(--serif)">Before you connect a repository</h3>
      <p class="muted" style="margin:0;font-size:14px">Agent Daemon talks to GitHub with a <b>classic</b> personal access token. Fine-grained tokens are not supported. Two things to do first:</p>
    </div>
    <span class="pill" style="font-size:12px">{ICON_LOCK} Integration Prerequisites</span>
  </div>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-top:14px">
    <div style="background:#0c0614;border:1px solid #2d1830;border-radius:10px;padding:18px">
      <div style="font-weight:700;color:#ff8a7a;font-size:14px;margin-bottom:6px">1. Make your repository private</div>
      <p class="muted" style="font-size:13px;line-height:1.5;margin:0 0 10px">We read your source files and error logs to diagnose problems, and Auto mode only merges fixes in private repositories. A private repository keeps your code and logs away from the public.</p>
      <details>
        <summary style="cursor:pointer;color:var(--blue);font-size:12.5px;font-weight:600">Show 5 quick steps ▾</summary>
        <ol class="steps muted" style="font-size:12.5px;line-height:1.5;margin:8px 0 0;padding-left:18px">
          <li>Open your repository on <b>github.com</b> in a browser.</li>
          <li>Tap or click the <b>Settings</b> tab of the repository (not your profile settings).</li>
          <li>Stay on <b>General</b> and scroll to the very bottom, to the <b>Danger Zone</b>.</li>
          <li>Press <b>Change visibility</b>, then <b>Change to private</b>.</li>
          <li>Read the warnings, type the repository name when GitHub asks, and confirm.</li>
        </ol>
      </details>
    </div>

    <div style="background:#0c0614;border:1px solid #2d1830;border-radius:10px;padding:18px">
      <div style="font-weight:700;color:#b98aff;font-size:14px;margin-bottom:6px">2. Create a classic token in Tokens (classic)</div>
      <p class="muted" style="font-size:13px;line-height:1.5;margin:0 0 10px">Generate a classic token with scopes: <span class="pill green" style="padding:2px 7px;font-size:11px"><code>repo</code></span> and <span class="pill green" style="padding:2px 7px;font-size:11px"><code>workflow</code></span>.</p>
      <details>
        <summary style="cursor:pointer;color:var(--blue);font-size:12.5px;font-weight:600">Show token generation steps ▾</summary>
        <ol class="steps muted" style="font-size:12.5px;line-height:1.5;margin:8px 0 0;padding-left:18px">
          <li>On GitHub press your profile picture, then <b>Settings</b>.</li>
          <li>At the bottom of the left menu open <b>Developer settings</b>, then <b>Personal access tokens</b>, then <b>Tokens (classic)</b>.</li>
          <li>Press <b>Generate new token</b>, then <b>Generate new token (classic)</b>.</li>
          <li>Name it <b>Agent Daemon</b> and pick how long it should last. When it expires, use <b>Update GitHub token</b> on your project page.</li>
          <li>Tick exactly two boxes: <code>repo</code> and <code>workflow</code>. Leave everything else unticked.</li>
          <li>Press <b>Generate token</b> and copy it right away. GitHub shows it only once. Paste it into the connect form.</li>
        </ol>
      </details>
      <div style="margin-top:10px;padding-top:8px;border-top:1px solid #281432;font-size:11.5px;color:var(--muted)">
        <b>What the agent uses each permission for:</b>
        <ul style="margin:4px 0 0;padding-left:16px">
          <li><code>repo</code>: read your code, create a branch and open pull requests. Nothing is merged unless you choose Auto mode.</li>
          <li><code>workflow</code>: add a small test workflow file, so Auto mode has a check that must pass before merging.</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<!-- FINAL CALL TO ACTION SECTION -->
<section class="final-cta-section">
  <div class="final-cta-card">
    <h2>Stop Chasing Errors. Start Shipping.</h2>
    <p>Let Agent Daemon handle the investigation while you focus on building your product.</p>
    <div style="display:flex;gap:14px;justify-content:center;align-items:center;flex-wrap:wrap">
      <a class="btn-hero-primary" href="/login">Get Started with Agent Daemon</a>
      <a class="btn-hero-secondary" href="/contact">Contact Us</a>
    </div>
    <div style="margin-top:18px;font-size:13px;color:#a99dbb">
      Instant setup · 1-day free trial · Cancel or pause anytime
    </div>
  </div>
</section>

<!-- INTERACTIVE SCRIPTS -->
<script src="/assets/home.js"></script>
<script>
{HOME_JS_INLINE}
</script>
"""
    for token, icon in [
        ("{ICON_ACTIVITY}", ICON_ACTIVITY),
        ("{ICON_LAYERS}", ICON_LAYERS),
        ("{ICON_CPU}", ICON_CPU),
        ("{ICON_PR}", ICON_PR),
        ("{ICON_SLIDERS}", ICON_SLIDERS),
        ("{ICON_SHIELD}", ICON_SHIELD),
        ("{ICON_LOCK}", ICON_LOCK),
        ("{ICON_TERMINAL}", ICON_TERMINAL),
        ("{ICON_CHECK}", ICON_CHECK),
        ("{ICON_ALERT}", ICON_ALERT),
        ("{ICON_CLOCK}", ICON_CLOCK),
        ("{ICON_PLAY}", ICON_PLAY),
        ("{ICON_ARROW}", ICON_ARROW),
        ("{HOME_JS_INLINE}", HOME_JS),
    ]:
        html = html.replace(token, icon)
    return html
