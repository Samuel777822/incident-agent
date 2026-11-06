"""Client-side JavaScript for the Agent Daemon Floating Chat Widget."""

CHAT_JS = r"""
(function() {
  if (window.__daemon_chat_initialized) return;
  window.__daemon_chat_initialized = true;

  // Track visitor on page load
  try {
    fetch('/api/visitor/track', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: window.location.pathname, referrer: document.referrer})
    }).catch(function() {});
  } catch(e) {}

  // If in admin page, skip floating user widget
  if (window.location.pathname.indexOf('/admin') === 0) return;

  var style = document.createElement('style');
  style.textContent = `
    .daemon-chat-btn {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 54px;
      height: 54px;
      border-radius: 50%;
      background: linear-gradient(135deg, #e11d2a, #9a4dff);
      box-shadow: 0 8px 24px rgba(225, 29, 42, 0.4), 0 0 16px rgba(154, 77, 255, 0.3);
      border: 1px solid rgba(255, 255, 255, 0.25);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      z-index: 9999;
      transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.2s ease;
    }
    .daemon-chat-btn:hover {
      transform: scale(1.08);
      box-shadow: 0 10px 30px rgba(225, 29, 42, 0.6), 0 0 24px rgba(154, 77, 255, 0.5);
    }
    .daemon-chat-btn svg { width: 26px; height: 26px; fill: currentColor; }
    .daemon-chat-badge {
      position: absolute;
      top: -2px;
      right: -2px;
      width: 13px;
      height: 13px;
      border-radius: 50%;
      background: #55d6a1;
      border: 2px solid #07050b;
      box-shadow: 0 0 8px #55d6a1;
    }
    .daemon-chat-window {
      position: fixed;
      bottom: 90px;
      right: 24px;
      width: 360px;
      max-width: calc(100vw - 32px);
      height: 520px;
      max-height: calc(100vh - 120px);
      background: #0f0a17;
      border: 1px solid #3a2338;
      border-radius: 16px;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.8), 0 0 30px rgba(154, 77, 255, 0.15);
      z-index: 9999;
      display: none;
      flex-direction: column;
      overflow: hidden;
      font-family: "Instrument Sans", Inter, -apple-system, sans-serif;
      backdrop-filter: blur(12px);
    }
    .daemon-chat-window.open { display: flex; animation: chatPop 0.22s ease-out; }
    @keyframes chatPop {
      from { opacity: 0; transform: translateY(12px) scale(0.97); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    .daemon-chat-header {
      padding: 14px 16px;
      background: linear-gradient(135deg, rgba(225, 29, 42, 0.25), rgba(154, 77, 255, 0.25));
      border-bottom: 1px solid #3a2338;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .daemon-chat-title { display: flex; align-items: center; gap: 10px; }
    .daemon-chat-avatar {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: #271438;
      border: 1px solid #ff6655;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #ff8a7a;
      font-weight: 700;
      font-size: 13px;
    }
    .daemon-chat-info h4 { margin: 0; font-size: 14px; color: #f2edf7; font-weight: 650; }
    .daemon-chat-status { font-size: 11px; color: #6fe0b0; display: flex; align-items: center; gap: 5px; }
    .daemon-chat-status::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: #6fe0b0; box-shadow: 0 0 6px #6fe0b0; }
    .daemon-chat-close {
      background: none; border: none; color: #a99dbb; cursor: pointer; font-size: 18px; padding: 4px;
      line-height: 1; border-radius: 4px;
    }
    .daemon-chat-close:hover { color: #fff; background: rgba(255,255,255,0.08); }
    .daemon-chat-messages {
      flex: 1;
      padding: 16px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      background: rgba(7, 5, 11, 0.4);
    }
    .daemon-msg {
      max-width: 82%;
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 13.5px;
      line-height: 1.45;
      word-break: break-word;
    }
    .daemon-msg.bot {
      align-self: flex-start;
      background: #180f24;
      border: 1px solid #3d2448;
      color: #f0eaf7;
      border-bottom-left-radius: 3px;
    }
    .daemon-msg.admin {
      align-self: flex-start;
      background: #28112c;
      border: 1px solid #ff4a3a66;
      color: #fff;
      border-bottom-left-radius: 3px;
    }
    .daemon-msg.admin .tag {
      display: inline-block;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #ff8a7a;
      margin-bottom: 4px;
    }
    .daemon-msg.visitor {
      align-self: flex-end;
      background: linear-gradient(135deg, #a3162b, #5b1fa8);
      color: #fff;
      border-bottom-right-radius: 3px;
    }
    .daemon-chat-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 8px 14px;
      background: #0f0a17;
      border-top: 1px solid #28182f;
    }
    .daemon-chip {
      background: #1c112b;
      border: 1px solid #3a2338;
      color: #cfc2df;
      font-size: 11px;
      padding: 4px 9px;
      border-radius: 12px;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .daemon-chip:hover {
      background: #2a1640;
      border-color: #ff6655;
      color: #fff;
    }
    .daemon-chat-lead {
      padding: 10px 14px;
      background: #140d1f;
      border-top: 1px solid #28182f;
      display: flex;
      gap: 6px;
      align-items: center;
    }
    .daemon-chat-lead input {
      flex: 1;
      padding: 6px 10px;
      font-size: 12px;
      border-radius: 6px;
      border: 1px solid #3a2338;
      background: #09060d;
      color: #f2edf7;
    }
    .daemon-chat-lead button {
      padding: 6px 10px;
      font-size: 12px;
      border-radius: 6px;
      border: 1px solid #5b1fa8;
      background: #391459;
      color: #fff;
      cursor: pointer;
      white-space: nowrap;
    }
    .daemon-chat-inputbox {
      padding: 10px 12px;
      border-top: 1px solid #3a2338;
      background: #120a1b;
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .daemon-chat-inputbox input {
      flex: 1;
      padding: 9px 12px;
      font-size: 13px;
      border-radius: 8px;
      border: 1px solid #3a2338;
      background: #09060d;
      color: #f2edf7;
      outline: none;
    }
    .daemon-chat-inputbox input:focus {
      border-color: #ff6655;
    }
    .daemon-chat-inputbox button {
      padding: 8px 14px;
      font-size: 13px;
      font-weight: 600;
      border-radius: 8px;
      border: none;
      background: linear-gradient(135deg, #d1121f, #5b1fa8);
      color: #fff;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .daemon-chat-inputbox button:disabled { opacity: 0.5; cursor: default; }
  `;
  document.head.appendChild(style);

  // Widget Button
  var btn = document.createElement('div');
  btn.className = 'daemon-chat-btn';
  btn.title = 'Chat with Support & AI';
  btn.innerHTML = `
    <div class="daemon-chat-badge"></div>
    <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>
  `;

  // Window
  var win = document.createElement('div');
  win.className = 'daemon-chat-window';
  win.innerHTML = `
    <div class="daemon-chat-header">
      <div class="daemon-chat-title">
        <div class="daemon-chat-avatar">AD</div>
        <div class="daemon-chat-info">
          <h4>Agent Daemon Live</h4>
          <span class="daemon-chat-status">Engineers & AI Online</span>
        </div>
      </div>
      <button class="daemon-chat-close">&times;</button>
    </div>
    <div class="daemon-chat-messages" id="daemon-chat-msgs"></div>
    <div class="daemon-chat-chips">
      <span class="daemon-chip" data-q="How does Agent Daemon work?">How it works</span>
      <span class="daemon-chip" data-q="What are the pricing & plans?">Pricing & Plans</span>
      <span class="daemon-chip" data-q="Who built Agent Daemon?">Engineering Team</span>
    </div>
    <div class="daemon-chat-lead" id="daemon-lead-row" style="display:none;">
      <input type="text" id="daemon-lead-contact" placeholder="Your name or email (optional)">
      <button id="daemon-lead-btn">Save</button>
    </div>
    <div class="daemon-chat-inputbox">
      <input type="text" id="daemon-chat-input" placeholder="Ask a question or talk to us..." autocomplete="off">
      <button id="daemon-chat-send">Send</button>
    </div>
  `;

  document.body.appendChild(btn);
  document.body.appendChild(win);

  var msgBox = win.querySelector('#daemon-chat-msgs');
  var input = win.querySelector('#daemon-chat-input');
  var sendBtn = win.querySelector('#daemon-chat-send');
  var closeBtn = win.querySelector('.daemon-chat-close');
  var leadRow = win.querySelector('#daemon-lead-row');
  var leadInput = win.querySelector('#daemon-lead-contact');
  var leadBtn = win.querySelector('#daemon-lead-btn');

  var lastPollTime = '';
  var isOpen = false;

  function toggleChat() {
    isOpen = !isOpen;
    if (isOpen) {
      win.classList.add('open');
      input.focus();
      pollMessages();
      checkSavedLead();
    } else {
      win.classList.remove('open');
    }
  }

  btn.addEventListener('click', toggleChat);
  closeBtn.addEventListener('click', toggleChat);

  function checkSavedLead() {
    var saved = localStorage.getItem('agent_daemon_lead');
    if (!saved) {
      leadRow.style.display = 'flex';
    }
  }

  leadBtn.addEventListener('click', function() {
    var val = leadInput.value.trim();
    if (!val) return;
    localStorage.setItem('agent_daemon_lead', val);
    leadRow.style.display = 'none';
    fetch('/api/chat/save-contact', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({contact: val})
    }).catch(function(){});
    appendMessage({
      sender: 'bot',
      text: "Thanks! We've saved your contact info. The Agent Daemon team of engineers will follow up with you directly."
    });
  });

  function appendMessage(m) {
    var div = document.createElement('div');
    div.className = 'daemon-msg ' + (m.sender || 'bot');
    if (m.sender === 'admin') {
      var tag = document.createElement('div');
      tag.className = 'tag';
      tag.textContent = m.sender_name || 'Agent Daemon Engineer';
      div.appendChild(tag);
      var t = document.createElement('div');
      t.textContent = m.text;
      div.appendChild(t);
    } else {
      div.textContent = m.text;
    }
    msgBox.appendChild(div);
    msgBox.scrollTop = msgBox.scrollHeight;
  }

  // Welcome message if empty
  function showInitialWelcome() {
    if (msgBox.children.length === 0) {
      appendMessage({
        sender: 'bot',
        text: "👋 Hi! Welcome to Agent Daemon. I'm your AI incident assistant. The Agent Daemon team of engineers is also on live notifications. How can we help you today?"
      });
    }
  }

  function pollMessages() {
    fetch('/api/chat/messages' + (lastPollTime ? '?after=' + encodeURIComponent(lastPollTime) : ''))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data && data.messages && data.messages.length > 0) {
          data.messages.forEach(function(m) {
            appendMessage(m);
            lastPollTime = m.created_at;
          });
        } else if (!lastPollTime) {
          showInitialWelcome();
        }
      })
      .catch(function() {
        if (!lastPollTime) showInitialWelcome();
      });
  }

  function sendMessage(text) {
    if (!text) return;
    appendMessage({sender: 'visitor', text: text});
    input.value = '';
    sendBtn.disabled = true;

    var lead = localStorage.getItem('agent_daemon_lead') || '';

    fetch('/api/chat/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: text, contact: lead})
    })
    .then(function(r) { return r.json(); })
    .then(function(res) {
      sendBtn.disabled = false;
      if (res && res.reply) {
        appendMessage({sender: 'bot', text: res.reply});
        if (res.created_at) lastPollTime = res.created_at;
      }
    })
    .catch(function(err) {
      sendBtn.disabled = false;
      appendMessage({
        sender: 'bot',
        text: "Thanks for your message! The Agent Daemon team of engineers has been notified and will review it shortly."
      });
    });
  }

  sendBtn.addEventListener('click', function() {
    sendMessage(input.value.trim());
  });

  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
      sendMessage(input.value.trim());
    }
  });

  win.querySelectorAll('.daemon-chip').forEach(function(chip) {
    chip.addEventListener('click', function() {
      var q = chip.getAttribute('data-q');
      sendMessage(q);
    });
  });

  // Background polling every 5s when open
  setInterval(function() {
    if (isOpen) pollMessages();
  }, 4500);

})();
"""
