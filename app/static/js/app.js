/* ============================================
   MBBS Study Assistant — Main Application JS
   ============================================ */

const App = {};
window.App = App;

/* ============================================
   UTILITY HELPERS
   ============================================ */
App.Utils = {
  /** Show a toast notification */
  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <span class="toast-icon">${icons[type] || icons.info}</span>
      <span class="toast-message">${App.Utils.escapeHtml(message)}</span>
      <button class="toast-close" onclick="App.Utils.dismissToast(this)">✕</button>
    `;
    container.appendChild(toast);

    // Auto-dismiss after 4 seconds
    setTimeout(() => {
      App.Utils.dismissToast(toast.querySelector('.toast-close'));
    }, 4000);
  },

  /** Dismiss a toast */
  dismissToast(btnOrEl) {
    const toast = btnOrEl.closest('.toast');
    if (!toast) return;
    toast.classList.add('toast-exit');
    setTimeout(() => toast.remove(), 300);
  },

  /** Escape HTML to prevent XSS */
  escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },

  /** Simple Markdown-like rendering (bold, italic, code, list items, headings, line breaks) */
  renderContent(text) {
    if (!text) return '';
    let html = App.Utils.escapeHtml(text);
    
    // 1. Extract code blocks ```...```
    const codeBlocks = [];
    html = html.replace(/```([\s\S]*?)```/g, (match, code) => {
      const id = `__CODE_BLOCK_${codeBlocks.length}__`;
      codeBlocks.push(code);
      return id;
    });
    
    // 2. Extract inline code `...`
    const inlineCodes = [];
    html = html.replace(/`([^`]+)`/g, (match, code) => {
      const id = `__INLINE_CODE_${inlineCodes.length}__`;
      inlineCodes.push(code);
      return id;
    });

    // 3. Headings (###, ##, #)
    html = html.replace(/^### (.*$)/gim, '<h3 style="margin-top: 1rem; margin-bottom: 0.5rem; font-weight: 600; color: var(--text-primary); font-size: 1.1rem;">$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2 style="margin-top: 1.25rem; margin-bottom: 0.5rem; font-weight: 600; color: var(--text-primary); font-size: 1.25rem;">$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1 style="margin-top: 1.5rem; margin-bottom: 0.75rem; font-weight: 700; color: var(--text-primary); font-size: 1.4rem;">$1</h1>');

    // 4. Bold **...**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    
    // 5. Italic *...* (avoid matching bullet points)
    html = html.replace(/\*(?!\s)([^*]+?)(?<!\s)\*/g, '<em>$1</em>');

    // 6. Lists (unordered * / - and ordered 1. 2. )
    const lines = html.split('\n');
    let inList = false;
    let listType = null; // 'ul' or 'ol'
    const processedLines = [];

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      
      const bulletMatch = line.match(/^(\s*)[*+-]\s+(.+)$/);
      const orderedMatch = line.match(/^(\s*)\d+\.\s+(.+)$/);

      if (bulletMatch) {
        if (!inList || listType !== 'ul') {
          if (inList) {
            processedLines.push(`</${listType}>`);
          }
          processedLines.push('<ul style="margin: 0.5rem 0; padding-left: 1.25rem; list-style-type: disc;">');
          inList = true;
          listType = 'ul';
        }
        processedLines.push(`<li style="margin-bottom: 0.25rem; color: var(--text-primary);">${bulletMatch[2]}</li>`);
      } else if (orderedMatch) {
        if (!inList || listType !== 'ol') {
          if (inList) {
            processedLines.push(`</${listType}>`);
          }
          processedLines.push('<ol style="margin: 0.5rem 0; padding-left: 1.25rem; list-style-type: decimal;">');
          inList = true;
          listType = 'ol';
        }
        processedLines.push(`<li style="margin-bottom: 0.25rem; color: var(--text-primary);">${orderedMatch[2]}</li>`);
      } else {
        if (inList) {
          processedLines.push(`</${listType}>`);
          inList = false;
          listType = null;
        }
        processedLines.push(line);
      }
    }
    if (inList) {
      processedLines.push(`</${listType}>`);
    }

    html = processedLines.join('\n');

    // 7. Line breaks (preserve newlines as br, but avoid double spacing around block elements)
    const linesForBreaks = html.split('\n');
    const finalLines = [];
    for (let i = 0; i < linesForBreaks.length; i++) {
      const current = linesForBreaks[i];
      const next = linesForBreaks[i + 1];
      
      if (current.trim() === '') {
        finalLines.push('<div style="height: 0.5rem;"></div>');
        continue;
      }
      
      const isCurrentBlock = /^\s*<\/?(ul|ol|li|h\d|pre|div)/i.test(current.trim());
      const isNextBlock = next ? /^\s*<\/?(ul|ol|li|h\d|pre|div)/i.test(next.trim()) : true;
      
      if (isCurrentBlock || isNextBlock) {
        finalLines.push(current);
      } else {
        finalLines.push(current + '<br>');
      }
    }
    html = finalLines.join('\n');

    // 8. Restore inline code (using a callback to safely handle '$' signs in the code content)
    inlineCodes.forEach((code, index) => {
      html = html.replace(`__INLINE_CODE_${index}__`, () => `<code style="background:rgba(0,0,0,0.3);padding:0.15rem 0.4rem;border-radius:4px;font-size:0.85rem;font-family:monospace;">${code}</code>`);
    });

    // 9. Restore code blocks (using a callback to safely handle '$' signs in the code content)
    codeBlocks.forEach((code, index) => {
      html = html.replace(`__CODE_BLOCK_${index}__`, () => `<pre style="background:rgba(0,0,0,0.3);padding:0.75rem;border-radius:8px;overflow-x:auto;margin:0.5rem 0;font-size:0.8rem;font-family:monospace;white-space:pre-wrap;">${code}</pre>`);
    });

    return html;
  },

  /** Format a date */
  formatDate(dateStr) {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  },
};


/* ============================================
   AUTH HELPERS
   ============================================ */
App.Auth = {
  TOKEN_KEY: 'mbbs_access_token',

  /** Get token from cookie */
  getToken() {
    const match = document.cookie.match(new RegExp('(^| )' + App.Auth.TOKEN_KEY + '=([^;]+)'));
    return match ? match[2] : null;
  },

  /** Set token in cookie (30 days) */
  setToken(token) {
    const expires = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toUTCString();
    document.cookie = `${App.Auth.TOKEN_KEY}=${token}; path=/; expires=${expires}; SameSite=Lax`;
    sessionStorage.setItem('mbbs_tab_session_active', 'true');
  },

  /** Remove token cookie */
  removeToken() {
    document.cookie = `${App.Auth.TOKEN_KEY}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
    document.cookie = `access_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
    sessionStorage.removeItem('mbbs_tab_session_active');
  },

  /** Fetch wrapper that adds Authorization header */
  async authFetch(url, options = {}) {
    const token = App.Auth.getToken();
    if (!token) {
      window.location.href = '/login';
      throw new Error('Not authenticated');
    }

    const headers = options.headers || {};
    headers['Authorization'] = `Bearer ${token}`;

    // Don't set Content-Type for FormData (browser sets it with boundary)
    if (!(options.body instanceof FormData) && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }

    const res = await fetch(url, { ...options, headers });

    if (res.status === 401) {
      App.Auth.removeToken();
      window.location.href = '/login';
      throw new Error('Session expired');
    }

    return res;
  },

  /** Logout */
  async logout() {
    try {
      await App.Auth.authFetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {
      // ignore errors
    }
    App.Auth.removeToken();
    window.location.href = '/login';
  },
};


/* ============================================
   SIDEBAR
   ============================================ */
App.Sidebar = {
  init() {
    const toggleBtn = document.getElementById('sidebar-toggle-btn');
    const overlay = document.getElementById('sidebar-overlay');
    const sidebar = document.getElementById('main-sidebar');
    const logoutBtn = document.getElementById('sidebar-logout-btn');

    if (toggleBtn) {
      toggleBtn.addEventListener('click', () => App.Sidebar.toggle());
    }

    if (overlay) {
      overlay.addEventListener('click', () => App.Sidebar.close());
    }

    if (logoutBtn) {
      logoutBtn.addEventListener('click', () => App.Auth.logout());
    }

    // Set active nav item
    App.Sidebar.setActiveNav();

    // Responsive: auto-collapse on small screens
    if (window.innerWidth <= 768) {
      document.body.classList.add('sidebar-collapsed');
    }
  },

  toggle() {
    const body = document.body;
    const sidebar = document.getElementById('main-sidebar');
    const overlay = document.getElementById('sidebar-overlay');

    if (window.innerWidth <= 768) {
      // Mobile: toggle slide
      sidebar.classList.toggle('mobile-open');
      overlay.classList.toggle('active');
    } else {
      body.classList.toggle('sidebar-collapsed');
    }
  },

  close() {
    const sidebar = document.getElementById('main-sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    sidebar.classList.remove('mobile-open');
    overlay.classList.remove('active');
  },

  setActiveNav() {
    const path = window.location.pathname;
    const navItems = document.querySelectorAll('.sidebar-nav-item[data-page]');
    navItems.forEach(item => {
      item.classList.remove('active');
      const page = item.getAttribute('data-page');
      if (
        (page === 'dashboard' && path === '/dashboard') ||
        (page === 'subjects' && path === '/subjects') ||
        (page === 'profile' && path === '/profile') ||
        (page === 'pyq' && path === '/wip') ||
        (page === 'quizzes' && path === '/wip') ||
        (page === 'revisions' && path === '/wip')
      ) {
        // Only mark dashboard, subjects, profile exactly
        if (['dashboard', 'subjects', 'profile'].includes(page)) {
          item.classList.add('active');
        }
      }
    });
  },
};


/* ============================================
   DASHBOARD
   ============================================ */
App.Dashboard = {
  currentSessionId: null,
  selectedSubjectIds: [],
  selectedFocusAreaIds: [],
  focusAreasBySubject: {},
  subjects: [],
  profile: null,

  async init() {
    await App.Dashboard.loadGreeting();
    await App.Dashboard.loadSubjects();
    await App.Dashboard.loadChatSessions();
    App.Dashboard.setupInputAutoResize();

    // Close context dropdown on outside click
    document.addEventListener('click', (e) => {
      const wrapper = document.querySelector('.context-selector-wrapper');
      if (wrapper && !wrapper.contains(e.target)) {
        document.getElementById('context-dropdown')?.classList.remove('show');
      }
    });
  },

  /** Load greeting based on time of day + profile (Claude-style with study taglines) */
  async loadGreeting() {
    const hour = new Date().getHours();

    // 10-slot schedule with study-relatable taglines
    let greeting, tagline;

    if (hour >= 0 && hour < 1) {
      greeting = 'Happy midnight';
      tagline = 'Late night research session? Let\'s review the charts.';
    } else if (hour >= 1 && hour < 4) {
      greeting = 'Burning the midnight oil';
      tagline = 'Keep pushing, future doctor. What medical concept are we mastering tonight?';
    } else if (hour >= 4 && hour < 7) {
      greeting = 'Good early morning';
      tagline = 'Up early for clinical rounds? Let\'s get ahead of the curriculum.';
    } else if (hour >= 7 && hour < 10) {
      greeting = 'Good morning';
      tagline = 'Ready to start your day? Let\'s tackle some high-yield study topics.';
    } else if (hour >= 10 && hour < 12) {
      greeting = 'Good late morning';
      tagline = 'Before the noon lecture starts, let\'s review our medical textbook notes.';
    } else if (hour >= 12 && hour < 13) {
      greeting = 'Happy noon';
      tagline = 'Time for a midday study break or a quick physiology review?';
    } else if (hour >= 13 && hour < 16) {
      greeting = 'Good afternoon';
      tagline = 'Let\'s keep the momentum going. What subject are we studying this afternoon?';
    } else if (hour >= 16 && hour < 18) {
      greeting = 'Good late afternoon';
      tagline = 'Classes are winding down. Perfect time for some pharmacology or anatomy review.';
    } else if (hour >= 18 && hour < 21) {
      greeting = 'Good evening';
      tagline = 'Winding down for the day? Let\'s consolidate our clinical knowledge.';
    } else {
      greeting = 'Good night';
      tagline = 'Reviewing before sleep is great for memory retention. What shall we look over?';
    }

    try {
      const res = await App.Auth.authFetch('/api/auth/profile');
      const data = await res.json();
      App.Dashboard.profile = data;

      let name = 'Student';
      if (data.name) {
        const parts = data.name.trim().split(/\s+/);
        if (parts.length > 0 && parts[0]) {
          name = parts[0];
        }
      }
      document.getElementById('greeting-text').innerHTML =
        `${greeting}, <span>${App.Utils.escapeHtml(name)}</span>! 👋`;

      const taglineEl = document.getElementById('greeting-tagline');
      if (taglineEl) taglineEl.textContent = tagline;

      const yearSuffix = ['', '1st', '2nd', '3rd', '4th', '5th'];
      document.getElementById('greeting-year').textContent =
        `📅 ${yearSuffix[data.year] || data.year} Year`;
      document.getElementById('greeting-course').textContent =
        `🎓 ${data.course || 'N/A'}`;
    } catch (e) {
      document.getElementById('greeting-text').innerHTML = `${greeting}! 👋`;
      const taglineEl = document.getElementById('greeting-tagline');
      if (taglineEl) taglineEl.textContent = tagline;
    }
  },

  /** Fetch user's subjects from the backend */
  async loadSubjects() {
    try {
      const res = await App.Auth.authFetch('/api/subjects');
      const data = await res.json();
      App.Dashboard.subjects = Array.isArray(data) ? data : [];
      App.Dashboard.renderContextDropdown();
      // Ensure we render empty subjects list correctly
      if (App.Dashboard.subjects.length === 0) {
        App.Dashboard.renderContextPills();
      }
    } catch (e) {
      console.error('Failed to load subjects:', e);
      App.Dashboard.subjects = [];
    }
  },

  /** Load level-1 hierarchy nodes (focus areas) for a subject */
  async loadFocusAreas(subjectId) {
    if (App.Dashboard.focusAreasBySubject[subjectId]) return; // already cached
    try {
      const res = await App.Auth.authFetch(`/api/subjects/${subjectId}/focus-areas`);
      const data = await res.json();
      App.Dashboard.focusAreasBySubject[subjectId] = Array.isArray(data) ? data : [];
    } catch (e) {
      console.error(`Failed to load focus areas for ${subjectId}:`, e);
      App.Dashboard.focusAreasBySubject[subjectId] = [];
    }
  },

  /** Render context dropdown checkboxes */
  renderContextDropdown() {
    const dropdown = document.getElementById('context-dropdown');
    if (!dropdown) return;

    const noSubjects = document.getElementById('context-no-subjects');

    if (App.Dashboard.subjects.length === 0) {
      if (noSubjects) noSubjects.style.display = 'block';
      return;
    }

    if (noSubjects) noSubjects.style.display = 'none';

    // Remove old items (keep the no-subjects message)
    dropdown.querySelectorAll('.context-dropdown-item').forEach(el => el.remove());

    App.Dashboard.subjects.forEach(subject => {
      if (subject.processing_status !== 'ready') return;

      const item = document.createElement('label');
      item.className = 'context-dropdown-item';
      item.innerHTML = `
        <input type="checkbox" value="${subject.id}"
          ${App.Dashboard.selectedSubjectIds.includes(subject.id) ? 'checked' : ''}
          onchange="App.Chat.onContextChange(this)">
        <span>${App.Utils.escapeHtml(subject.name)}</span>
      `;
      dropdown.appendChild(item);
    });
  },

  /** Render pills showing selected subjects */
  renderContextPills() {
    const container = document.getElementById('context-pills');
    if (!container) return;
    
    // Clear everything and let renderFocusAreaPills append after
    container.innerHTML = '';
    
    App.Dashboard.selectedSubjectIds.forEach(id => {
      const subject = App.Dashboard.subjects.find(s => s.id === id);
      if (!subject) return;

      const pill = document.createElement('span');
      pill.className = 'pill';
      pill.innerHTML = `
        ${App.Utils.escapeHtml(subject.name)}
        <button class="pill-remove" onclick="App.Chat.removeContext('${id}')">✕</button>
      `;
      container.appendChild(pill);
    });
  },

  /** Render the Focus Area select dropdown based on selected subjects */
  renderFocusAreaDropdown() {
    const wrapper = document.getElementById('focus-area-wrapper');
    const select = document.getElementById('focus-area-select');
    if (!wrapper || !select) return;

    // Hide if no subjects selected
    if (App.Dashboard.selectedSubjectIds.length === 0) {
      wrapper.style.display = 'none';
      App.Dashboard.selectedFocusAreaIds = [];
      return;
    }

    wrapper.style.display = 'flex';

    // Remember current selection
    const previouslySelected = new Set(App.Dashboard.selectedFocusAreaIds);

    // Clear and rebuild
    select.innerHTML = '<option value="">All Sections</option>';

    const selectedSubjects = App.Dashboard.subjects.filter(
      s => App.Dashboard.selectedSubjectIds.includes(s.id) && s.processing_status === 'ready'
    );

    // If only one subject, no need for optgroup
    if (selectedSubjects.length === 1) {
      const subjectId = selectedSubjects[0].id;
      const areas = App.Dashboard.focusAreasBySubject[subjectId] || [];
      areas.forEach(area => {
        const opt = document.createElement('option');
        opt.value = area.id;
        opt.textContent = area.title;
        if (previouslySelected.has(area.id)) opt.selected = true;
        select.appendChild(opt);
      });
    } else {
      // Multiple subjects: use optgroup
      selectedSubjects.forEach(subject => {
        const areas = App.Dashboard.focusAreasBySubject[subject.id] || [];
        if (areas.length === 0) return;

        const group = document.createElement('optgroup');
        group.label = subject.name;
        areas.forEach(area => {
          const opt = document.createElement('option');
          opt.value = area.id;
          opt.textContent = area.title;
          if (previouslySelected.has(area.id)) opt.selected = true;
          group.appendChild(opt);
        });
        select.appendChild(group);
      });
    }

    // Clean up any focus areas that no longer exist in the dropdown
    const validIds = new Set();
    select.querySelectorAll('option[value]').forEach(opt => {
      if (opt.value) validIds.add(opt.value);
    });
    App.Dashboard.selectedFocusAreaIds = App.Dashboard.selectedFocusAreaIds.filter(id => validIds.has(id));
  },

  /** Render focus area pills alongside subject pills */
  renderFocusAreaPills() {
    const container = document.getElementById('context-pills');
    if (!container) return;

    // Remove existing focus pills
    container.querySelectorAll('.pill-focus').forEach(el => el.remove());

    App.Dashboard.selectedFocusAreaIds.forEach(id => {
      // Find the area across all cached subjects
      let area = null;
      for (const areas of Object.values(App.Dashboard.focusAreasBySubject)) {
        area = areas.find(a => a.id === id);
        if (area) break;
      }
      if (!area) return;

      const pill = document.createElement('span');
      pill.className = 'pill pill-focus';
      pill.innerHTML = `
        🎯 ${App.Utils.escapeHtml(area.title)}
        <button class="pill-remove" onclick="App.Chat.removeFocusArea('${id}')">✕</button>
      `;
      container.appendChild(pill);
    });
  },

  /** Setup auto-resize for textarea */
  setupInputAutoResize() {
    const input = document.getElementById('chat-input');
    if (!input) return;

    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';

      // Enable/disable send button
      const sendBtn = document.getElementById('send-message-btn');
      if (sendBtn) {
        sendBtn.disabled = !input.value.trim();
      }
    });
  },

  /** Load chat sessions */
  async loadChatSessions() {
    const listEl = document.getElementById('chat-sessions-list');
    const emptyEl = document.getElementById('sessions-empty');
    if (!listEl) return;

    try {
      const res = await App.Auth.authFetch('/api/chat/sessions');
      const sessions = await res.json();

      // Remove old session items
      listEl.querySelectorAll('.chat-session-item').forEach(el => el.remove());

      if (!sessions || sessions.length === 0) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
      }

      if (emptyEl) emptyEl.style.display = 'none';

      sessions.forEach(session => {
        const item = document.createElement('div');
        item.className = `chat-session-item ${session.id === App.Dashboard.currentSessionId ? 'active' : ''}`;
        item.setAttribute('data-session-id', session.id);
        item.innerHTML = `
          <span class="chat-session-icon">💬</span>
          <span class="chat-session-title">${App.Utils.escapeHtml(session.title || 'New Chat')}</span>
          <button class="chat-session-delete" onclick="event.stopPropagation(); App.Chat.deleteSession('${session.id}')" title="Delete chat">🗑</button>
        `;
        item.addEventListener('click', () => App.Chat.switchChat(session.id));
        listEl.insertBefore(item, emptyEl);
      });
    } catch (e) {
      console.error('Failed to load sessions:', e);
    }
  },
};


/* ============================================
   CHAT
   ============================================ */
App.Chat = {
  /** Create a new chat session */
  async createNewChat() {
    try {
      const title = 'New Chat ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const res = await App.Auth.authFetch('/api/chat/sessions', {
        method: 'POST',
        body: JSON.stringify({
          title,
          subject_ids: App.Dashboard.selectedSubjectIds,
          focus_area_ids: App.Dashboard.selectedFocusAreaIds,
        }),
      });

      if (!res.ok) throw new Error('Failed to create session');

      const session = await res.json();
      App.Dashboard.currentSessionId = session.id;
      await App.Dashboard.loadChatSessions();
      await App.Chat.switchChat(session.id);
      App.Utils.showToast('New chat created', 'success');
    } catch (e) {
      App.Utils.showToast(e.message, 'error');
    }
  },

  /** Switch to a chat session */
  async switchChat(sessionId) {
    App.Dashboard.currentSessionId = sessionId;

    // Update active state in sidebar
    document.querySelectorAll('.chat-session-item').forEach(item => {
      item.classList.toggle('active', item.getAttribute('data-session-id') == sessionId);
    });

    // Restore context from session data
    try {
      const res = await App.Auth.authFetch('/api/chat/sessions');
      const sessions = await res.json();
      const session = sessions.find(s => s.id === sessionId);
      if (session) {
        App.Dashboard.selectedSubjectIds = session.subject_ids || [];
        App.Dashboard.selectedFocusAreaIds = session.focus_area_ids || [];

        // Load focus areas for all selected subjects
        for (const sid of App.Dashboard.selectedSubjectIds) {
          await App.Dashboard.loadFocusAreas(sid);
        }

        App.Dashboard.renderContextDropdown();
        App.Dashboard.renderContextPills();
        App.Dashboard.renderFocusAreaDropdown();
        App.Dashboard.renderFocusAreaPills();
      }
    } catch (e) {
      console.error('Failed to restore session context:', e);
    }

    // Load messages
    await App.Chat.loadMessages(sessionId);
  },

  /** Load messages for a session */
  async loadMessages(sessionId) {
    const messagesEl = document.getElementById('chat-messages');
    const emptyState = document.getElementById('chat-empty-state');
    if (!messagesEl) return;

    // Clear messages
    messagesEl.querySelectorAll('.message').forEach(el => el.remove());

    try {
      const res = await App.Auth.authFetch(`/api/chat/sessions/${sessionId}/messages`);
      const messages = await res.json();

      if (!messages || messages.length === 0) {
        if (emptyState) emptyState.style.display = 'flex';
        return;
      }

      if (emptyState) emptyState.style.display = 'none';

      messages.forEach(msg => {
        App.Chat.appendMessage(msg.role, msg.content, msg.id, msg.metadata);
      });

      // Scroll to bottom
      messagesEl.scrollTop = messagesEl.scrollHeight;
    } catch (e) {
      console.error('Failed to load messages:', e);
    }
  },

  /** Append a message to the chat */
  appendMessage(role, content, messageId = null, metadata = null) {
    const messagesEl = document.getElementById('chat-messages');
    const emptyState = document.getElementById('chat-empty-state');
    if (!messagesEl) return;

    if (emptyState) emptyState.style.display = 'none';

    const msgDiv = document.createElement('div');
    msgDiv.className = `message message-${role}`;
    if (messageId) msgDiv.setAttribute('data-message-id', messageId);

    const avatarText = role === 'user' ? '👤' : '🤖';
    let actionsHtml = '';
    let sourcesHtml = '';

    if (role === 'assistant') {
      actionsHtml = `
        <div class="message-actions">
          <button class="message-action-btn" onclick="App.Chat.starMessage('${messageId}')" title="Star message">⭐</button>
          <button class="message-action-btn" onclick="App.Chat.retryMessage('${messageId}')" title="Retry">🔄</button>
        </div>
      `;

      if (metadata && metadata.sources) {
        const pages = Array.isArray(metadata.sources) ? metadata.sources.join(', ') : metadata.sources;
        sourcesHtml = `<div class="message-sources">📖 Sources: ${App.Utils.escapeHtml(String(pages))}</div>`;
      }
    }

    msgDiv.innerHTML = `
      <div class="message-avatar">${avatarText}</div>
      <div class="message-content">
        ${actionsHtml}
        <div class="message-bubble">${App.Utils.renderContent(content)}</div>
        ${sourcesHtml}
      </div>
    `;

    messagesEl.appendChild(msgDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  },

  /** Send a message */
  async sendMessage() {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-message-btn');
    if (!input) return;

    const content = input.value.trim();
    if (!content) return;

    // Create session if none selected
    if (!App.Dashboard.currentSessionId) {
      await App.Chat.createNewChat();
      if (!App.Dashboard.currentSessionId) return;
    }

    const sessionId = App.Dashboard.currentSessionId;

    // Append user message to UI
    App.Chat.appendMessage('user', content);
    input.value = '';
    input.style.height = 'auto';
    sendBtn.disabled = true;

    // Show typing indicator
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message message-assistant';
    typingDiv.id = 'typing-indicator';
    typingDiv.innerHTML = `
      <div class="message-avatar">🤖</div>
      <div class="message-content">
        <div class="message-bubble" style="display:flex;align-items:center;gap:0.5rem;">
          <div class="spinner"></div>
          <span style="color:var(--text-muted);font-size:0.825rem;">Thinking...</span>
        </div>
      </div>
    `;
    document.getElementById('chat-messages')?.appendChild(typingDiv);
    document.getElementById('chat-messages').scrollTop = document.getElementById('chat-messages').scrollHeight;

    try {
      const res = await App.Auth.authFetch(`/api/chat/sessions/${sessionId}/messages`, {
        method: 'POST',
        body: JSON.stringify({
          content,
          subject_ids: App.Dashboard.selectedSubjectIds,
          focus_area_ids: App.Dashboard.selectedFocusAreaIds,
        }),
      });

      // Remove typing indicator
      document.getElementById('typing-indicator')?.remove();

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to send message');
      }

      // Check if user is still on the same session
      if (App.Dashboard.currentSessionId !== sessionId) {
        return;
      }

      const data = await res.json();

      // The response could be either a single message or an object with the assistant's reply
      if (data.role && data.content) {
        App.Chat.appendMessage(data.role, data.content, data.id, data.metadata);
      } else if (data.reply) {
        App.Chat.appendMessage('assistant', data.reply.content, data.reply.id, data.reply.metadata);
      } else if (data.assistant_message) {
        App.Chat.appendMessage('assistant', data.assistant_message.content, data.assistant_message.id, data.assistant_message.metadata);
      }
    } catch (e) {
      document.getElementById('typing-indicator')?.remove();
      if (App.Dashboard.currentSessionId === sessionId) {
        App.Utils.showToast(e.message, 'error');
      }
    }
  },

  /** Handle Enter key in chat input */
  handleInputKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      App.Chat.sendMessage();
    }
  },

  /** Toggle context selector dropdown */
  toggleContextSelector() {
    const dropdown = document.getElementById('context-dropdown');
    if (dropdown) dropdown.classList.toggle('show');
  },

  /** Handle context checkbox change */
  async onContextChange(checkbox) {
    const subjectId = checkbox.value;
    if (checkbox.checked) {
      if (!App.Dashboard.selectedSubjectIds.includes(subjectId)) {
        App.Dashboard.selectedSubjectIds.push(subjectId);
      }
      // Load focus areas for this subject
      await App.Dashboard.loadFocusAreas(subjectId);
    } else {
      App.Dashboard.selectedSubjectIds = App.Dashboard.selectedSubjectIds.filter(id => id !== subjectId);
      // Remove any focus areas belonging to the deselected subject
      const subjectAreas = App.Dashboard.focusAreasBySubject[subjectId] || [];
      const areaIds = new Set(subjectAreas.map(a => a.id));
      App.Dashboard.selectedFocusAreaIds = App.Dashboard.selectedFocusAreaIds.filter(id => !areaIds.has(id));
    }
    App.Dashboard.renderContextPills();
    App.Dashboard.renderFocusAreaDropdown();
    App.Dashboard.renderFocusAreaPills();

    // Update context on current session if one is active
    if (App.Dashboard.currentSessionId) {
      App.Chat.updateContext(App.Dashboard.currentSessionId, App.Dashboard.selectedSubjectIds, App.Dashboard.selectedFocusAreaIds);
    }
  },

  /** Handle focus area dropdown change */
  onFocusAreaChange(selectEl) {
    const selectedValue = selectEl.value;
    if (selectedValue) {
      // Add to selection if not already present
      if (!App.Dashboard.selectedFocusAreaIds.includes(selectedValue)) {
        App.Dashboard.selectedFocusAreaIds.push(selectedValue);
      }
    } else {
      // "All Sections" selected — clear focus areas
      App.Dashboard.selectedFocusAreaIds = [];
    }
    App.Dashboard.renderFocusAreaPills();

    // Reset select back to "All Sections" to allow re-selecting
    selectEl.value = '';

    if (App.Dashboard.currentSessionId) {
      App.Chat.updateContext(App.Dashboard.currentSessionId, App.Dashboard.selectedSubjectIds, App.Dashboard.selectedFocusAreaIds);
    }
  },

  /** Remove a focus area from context */
  removeFocusArea(focusAreaId) {
    App.Dashboard.selectedFocusAreaIds = App.Dashboard.selectedFocusAreaIds.filter(id => id !== focusAreaId);
    App.Dashboard.renderFocusAreaPills();

    if (App.Dashboard.currentSessionId) {
      App.Chat.updateContext(App.Dashboard.currentSessionId, App.Dashboard.selectedSubjectIds, App.Dashboard.selectedFocusAreaIds);
    }
  },

  /** Remove a subject from context */
  removeContext(subjectId) {
    App.Dashboard.selectedSubjectIds = App.Dashboard.selectedSubjectIds.filter(id => id !== subjectId);

    // Remove any focus areas belonging to the removed subject
    const subjectAreas = App.Dashboard.focusAreasBySubject[subjectId] || [];
    const areaIds = new Set(subjectAreas.map(a => a.id));
    App.Dashboard.selectedFocusAreaIds = App.Dashboard.selectedFocusAreaIds.filter(id => !areaIds.has(id));

    App.Dashboard.renderContextPills();
    App.Dashboard.renderContextDropdown();
    App.Dashboard.renderFocusAreaDropdown();
    App.Dashboard.renderFocusAreaPills();

    if (App.Dashboard.currentSessionId) {
      App.Chat.updateContext(App.Dashboard.currentSessionId, App.Dashboard.selectedSubjectIds, App.Dashboard.selectedFocusAreaIds);
    }
  },

  /** Update context for a session */
  async updateContext(sessionId, subjectIds, focusAreaIds = []) {
    try {
      await App.Auth.authFetch(`/api/chat/sessions/${sessionId}/context`, {
        method: 'PUT',
        body: JSON.stringify({ subject_ids: subjectIds, focus_area_ids: focusAreaIds }),
      });
    } catch (e) {
      console.error('Failed to update context:', e);
    }
  },

  /** Star a message */
  async starMessage(messageId) {
    if (!messageId) return;
    try {
      const res = await App.Auth.authFetch('/api/starred/', {
        method: 'POST',
        body: JSON.stringify({ message_id: messageId }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to star message');
      }

      // Visual feedback
      const msgEl = document.querySelector(`[data-message-id="${messageId}"] .message-action-btn`);
      if (msgEl) msgEl.classList.add('starred');

      App.Utils.showToast('Message starred!', 'success');
    } catch (e) {
      App.Utils.showToast(e.message, 'error');
    }
  },

  /** Retry last message */
  async retryMessage(messageId) {
    // Find the user message before this assistant message and resend it
    const messages = document.querySelectorAll('.message');
    let userContent = null;

    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].classList.contains('message-user')) {
        const bubble = messages[i].querySelector('.message-bubble');
        if (bubble) {
          userContent = bubble.textContent.trim();
        }
        break;
      }
    }

    if (!userContent) {
      App.Utils.showToast('No message to retry', 'warning');
      return;
    }

    // Remove the last assistant message from UI
    const assistantMsgs = document.querySelectorAll('.message-assistant');
    if (assistantMsgs.length > 0) {
      assistantMsgs[assistantMsgs.length - 1].remove();
    }

    // Resend
    const input = document.getElementById('chat-input');
    input.value = userContent;
    App.Chat.sendMessage();
  },

  /** Delete a session */
  async deleteSession(sessionId) {
    if (!confirm('Delete this chat session?')) return;

    try {
      const res = await App.Auth.authFetch(`/api/chat/sessions/${sessionId}`, {
        method: 'DELETE',
      });

      if (!res.ok) throw new Error('Failed to delete session');

      if (App.Dashboard.currentSessionId === sessionId) {
        App.Dashboard.currentSessionId = null;
        const messagesEl = document.getElementById('chat-messages');
        if (messagesEl) messagesEl.querySelectorAll('.message').forEach(el => el.remove());
        const emptyState = document.getElementById('chat-empty-state');
        if (emptyState) emptyState.style.display = 'flex';
      }

      await App.Dashboard.loadChatSessions();
      App.Utils.showToast('Chat deleted', 'success');
    } catch (e) {
      App.Utils.showToast(e.message, 'error');
    }
  },
};


/* ============================================
   SUBJECTS
   ============================================ */
App.Subjects = {
  pollingInterval: null,

  async init() {
    await App.Subjects.loadSubjects();
  },

  /** Load and render subject cards */
  async loadSubjects() {
    const grid = document.getElementById('subjects-grid');
    const addCard = document.getElementById('add-subject-card');
    if (!grid) return;

    // Remove existing subject cards (keep add card)
    grid.querySelectorAll('.subject-card:not(.subject-add-card)').forEach(el => el.remove());

    try {
      const res = await App.Auth.authFetch('/api/subjects/');
      const subjects = await res.json();

      if (!subjects || subjects.length === 0) return;

      subjects.forEach(subject => {
        const card = document.createElement('div');
        card.className = 'card card-hover subject-card';
        card.setAttribute('data-subject-id', subject.id);

        let statusBadge = '';
        const status = subject.processing_status || 'unknown';
        if (status === 'ready') {
          statusBadge = '<span class="badge badge-success">✓ Ready</span>';
        } else if (status === 'failed') {
          statusBadge = '<span class="badge badge-error">❌ Failed</span>';
        } else {
          statusBadge = '<span class="badge badge-warning">⏳ Processing</span>';
        }

        card.innerHTML = `
          <div class="subject-card-header">
            <div class="subject-card-icon">📘</div>
            <button type="button" class="subject-delete-btn" onclick="event.stopPropagation(); App.Subjects.deleteSubject('${subject.id}')" title="Delete subject">🗑</button>
          </div>
          <div class="subject-card-name">${App.Utils.escapeHtml(subject.name)}</div>
          <div class="subject-card-book">${subject.book_title ? App.Utils.escapeHtml(subject.book_title) : 'No book specified'}</div>
          <div class="subject-card-footer">
            ${statusBadge}
            <span class="text-muted" style="font-size:0.7rem;">${App.Utils.formatDate(subject.created_at)}</span>
          </div>
        `;

        grid.insertBefore(card, addCard);
      });
    } catch (e) {
      console.error('Failed to load subjects:', e);
      App.Utils.showToast('Failed to load subjects', 'error');
    }
  },

  /** Open upload modal */
  openUploadModal() {
    const overlay = document.getElementById('upload-modal-overlay');
    if (overlay) {
      overlay.classList.add('active');
      // Reset form
      document.getElementById('upload-submit-btn').disabled = false;
      document.getElementById('upload-submit-btn').textContent = 'Upload & Process';
      document.getElementById('upload-submit-btn').style.opacity = '1';
      document.getElementById('upload-submit-btn').style.pointerEvents = 'auto';
      
      const closeBtn = document.querySelector('.modal-close');
      if (closeBtn) closeBtn.style.display = 'block';

      // Reset dynamic steps to just uploading
      const stepsEl = document.getElementById('processing-steps');
      if (stepsEl) {
        stepsEl.innerHTML = '';
        stepsEl.classList.remove('show');
      }
    }
  },

  /** Close upload modal */
  closeUploadModal() {
    const overlay = document.getElementById('upload-modal-overlay');
    if (overlay) overlay.classList.remove('active');

    // Stop polling if running
    if (App.Subjects.pollingInterval) {
      clearInterval(App.Subjects.pollingInterval);
      App.Subjects.pollingInterval = null;
    }
  },

  /** Upload a subject */
  async uploadSubject(event) {
    event.preventDefault();

    const name = document.getElementById('upload-subject-name').value.trim();
    const bookTitle = document.getElementById('upload-book-title').value.trim();
    const fileInput = document.getElementById('upload-file-input');
    const submitBtn = document.getElementById('upload-submit-btn');

    if (!name || !fileInput.files.length) {
      App.Utils.showToast('Please fill required fields and select a PDF.', 'warning');
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Uploading...';
    submitBtn.style.opacity = '0.5';
    submitBtn.style.pointerEvents = 'none';
    
    const closeBtn = document.querySelector('.modal-close');
    if (closeBtn) closeBtn.style.display = 'none'; // Lock modal UI

    // Show processing steps
    const stepsEl = document.getElementById('processing-steps');
    stepsEl.innerHTML = `
      <div class="processing-step" data-step="uploading">
        <div class="step-indicator pending" id="step-uploading">●</div>
        <span class="step-label" id="step-uploading-label">Uploading</span>
      </div>
    `;
    stepsEl.classList.add('show');
    App.Subjects.setStepState('uploading', 'active');

    const formData = new FormData();
    formData.append('name', name);
    if (bookTitle) formData.append('book_title', bookTitle);
    formData.append('file', fileInput.files[0]);

    try {
      const res = await App.Auth.authFetch('/api/subjects/', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Upload failed');
      }

      const subject = await res.json();
      App.Subjects.setStepState('uploading', 'done');

      // Start polling for upload status
      App.Subjects.pollUploadStatus(subject.id);
    } catch (e) {
      App.Subjects.setStepState('uploading', 'failed');
      App.Utils.showToast(e.message, 'error');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Upload & Process';
      submitBtn.style.opacity = '1';
      submitBtn.style.pointerEvents = 'auto';
      if (closeBtn) closeBtn.style.display = 'block'; // Unlock modal UI
    }
  },

  /** Render dynamic steps */
  renderSteps(documentType) {
    const stepsEl = document.getElementById('processing-steps');
    if (!stepsEl) return [];
    
    let steps = [];
    if (documentType === 'digital') {
      steps = [
        { id: 'uploading', label: 'Uploading' },
        { id: 'detected_digital', label: 'Detected Digital Document' },
        { id: 'extracting_toc', label: 'Extracting TOC' },
        { id: 'building_hierarchy', label: 'Building hierarchy' },
        { id: 'chunking', label: 'Chunking' },
        { id: 'completed', label: 'Done' }
      ];
    } else if (documentType === 'scanned') {
      steps = [
        { id: 'uploading', label: 'Uploading' },
        { id: 'detected_scanned', label: 'Detected Scanned Document' },
        { id: 'binarising', label: 'Binarising' },
        { id: 'extracting_ocr', label: 'Extracting Text via OCR' },
        { id: 'extracting_toc', label: 'Extracting TOC' },
        { id: 'building_hierarchy', label: 'Building hierarchy' },
        { id: 'chunking', label: 'Chunking' },
        { id: 'completed', label: 'Done' }
      ];
    }

    stepsEl.innerHTML = steps.map(s => `
      <div class="processing-step" data-step="${s.id}">
        <div class="step-indicator pending" id="step-${s.id}">●</div>
        <span class="step-label" id="step-${s.id}-label">${s.label}</span>
      </div>
    `).join('');
    
    return steps.map(s => s.id);
  },

  /** Poll upload status */
  pollUploadStatus(subjectId) {
    let STEP_ORDER = ['uploading'];
    let targetStepIndex = 0;
    let currentAnimatedIndex = 0;
    let backendFailed = false;
    let errorMessage = '';
    let stepsRendered = false;

    // Start a smooth animation sequence loop to step through statuses one by one
    const animationInterval = setInterval(() => {
      if (backendFailed) {
        App.Subjects.setStepState(STEP_ORDER[currentAnimatedIndex], 'failed');
        const closeBtn = document.querySelector('.modal-close');
        if (closeBtn) closeBtn.style.display = 'block'; // Unlock modal
        clearInterval(animationInterval);
        return;
      }

      if (currentAnimatedIndex < targetStepIndex) {
        // Complete current visual step
        App.Subjects.setStepState(STEP_ORDER[currentAnimatedIndex], 'done');
        
        // Advance pointer
        currentAnimatedIndex++;
        
        if (currentAnimatedIndex === STEP_ORDER.length - 1) {
          // If we transitioned into 'completed' step, finish the animation
          App.Subjects.setStepState(STEP_ORDER[currentAnimatedIndex], 'done');
          const closeBtn = document.querySelector('.modal-close');
          if (closeBtn) closeBtn.style.display = 'block'; // Unlock modal
          clearInterval(animationInterval);
          App.Utils.showToast('Subject processed successfully!', 'success');
          
          setTimeout(() => {
            App.Subjects.loadSubjects();
            App.Subjects.closeUploadModal();
          }, 1500);
        } else {
          App.Subjects.setStepState(STEP_ORDER[currentAnimatedIndex], 'active');
        }
      }
    }, 1000);

    // Initial state setup
    App.Subjects.setStepState(STEP_ORDER[0], 'active');

    App.Subjects.pollingInterval = setInterval(async () => {
      try {
        const res = await App.Auth.authFetch(`/api/subjects/${subjectId}/upload-status`);
        const data = await res.json();

        const status = (data.status || '').toLowerCase();

        if (status === 'failed') {
          backendFailed = true;
          errorMessage = data.error_message || 'Processing failed';
          clearInterval(App.Subjects.pollingInterval);
          App.Subjects.pollingInterval = null;
          App.Utils.showToast(errorMessage, 'error');
          return;
        }

        // If we now know the document type, render the full steps
        if (data.document_type && !stepsRendered) {
          STEP_ORDER = App.Subjects.renderSteps(data.document_type);
          stepsRendered = true;
          // Re-apply states up to currentAnimatedIndex since we just overwrote the DOM
          for (let i = 0; i < currentAnimatedIndex; i++) {
            App.Subjects.setStepState(STEP_ORDER[i], 'done');
          }
          App.Subjects.setStepState(STEP_ORDER[currentAnimatedIndex], 'active');
        }

        let stepKey = status;
        if (stepKey === 'uploaded') stepKey = 'uploading';
        if (stepKey === 'indexing') stepKey = 'chunking'; // Map backend 'indexing' -> visual 'chunking'

        const stepIndex = STEP_ORDER.indexOf(stepKey);
        if (stepIndex > targetStepIndex) {
          targetStepIndex = stepIndex;
          
          if (stepKey === 'completed' || stepKey === 'ready') {
            clearInterval(App.Subjects.pollingInterval);
            App.Subjects.pollingInterval = null;
          }
        }
      } catch (e) {
        console.error('Polling error:', e);
      }
    }, 1500);
  },

  /** Set the visual state of a processing step */
  setStepState(step, state) {
    const indicator = document.getElementById(`step-${step}`);
    const label = document.getElementById(`step-${step}-label`);
    if (!indicator) return;

    indicator.className = `step-indicator ${state}`;
    if (label) {
      label.className = 'step-label';
      if (state === 'active') label.classList.add('active-label');
      if (state === 'done') label.classList.add('done-label');
      if (state === 'failed') label.classList.add('failed-label');
    }

    switch (state) {
      case 'done':
        indicator.textContent = '✓';
        break;
      case 'failed':
        indicator.textContent = '✕';
        break;
      case 'active':
        indicator.innerHTML = '<div class="spinner" style="width:14px;height:14px;border-width:2px;"></div>';
        break;
      default:
        indicator.textContent = '●';
    }
  },

  /** Delete a subject */
  async deleteSubject(subjectId) {
    if (!confirm('Delete this subject? This cannot be undone.')) return;

    try {
      const res = await App.Auth.authFetch(`/api/subjects/${subjectId}`, {
        method: 'DELETE',
      });

      if (!res.ok) throw new Error('Failed to delete subject');

      App.Utils.showToast('Subject deleted', 'success');
      await App.Subjects.loadSubjects();
    } catch (e) {
      App.Utils.showToast(e.message, 'error');
    }
  },
};


/* ============================================
   PROFILE
   ============================================ */
App.Profile = {
  async init() {
    await App.Profile.loadProfile();
    await App.Profile.loadStarredMessages();
  },

  /** Load profile data */
  async loadProfile() {
    try {
      const res = await App.Auth.authFetch('/api/auth/profile');
      const data = await res.json();

      document.getElementById('profile-name').value = data.name || '';
      document.getElementById('profile-year').value = data.year || '1';
      document.getElementById('profile-course').value = data.course || 'MBBS';
      document.getElementById('profile-email-readonly').value = data.email || '';
      document.getElementById('profile-display-name').textContent = data.name || 'Student';
      document.getElementById('profile-display-email').textContent = data.email || '';

      // Avatar initial
      const avatar = document.getElementById('profile-avatar');
      if (avatar && data.name) {
        avatar.textContent = data.name.charAt(0).toUpperCase();
      }
    } catch (e) {
      App.Utils.showToast('Failed to load profile', 'error');
    }
  },

  /** Save profile changes */
  async saveProfile(event) {
    event.preventDefault();

    const name = document.getElementById('profile-name').value.trim();
    const year = parseInt(document.getElementById('profile-year').value);
    const course = document.getElementById('profile-course').value;
    const saveBtn = document.getElementById('profile-save-btn');

    if (!name) {
      App.Utils.showToast('Name is required', 'warning');
      return;
    }

    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    try {
      const res = await App.Auth.authFetch('/api/auth/profile', {
        method: 'PUT',
        body: JSON.stringify({ name, year, course }),
      });

      if (!res.ok) throw new Error('Failed to save profile');

      App.Utils.showToast('Profile updated!', 'success');

      // Update display
      document.getElementById('profile-display-name').textContent = name;
      const avatar = document.getElementById('profile-avatar');
      if (avatar) avatar.textContent = name.charAt(0).toUpperCase();
    } catch (e) {
      App.Utils.showToast(e.message, 'error');
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Changes';
    }
  },

  /** Load starred messages */
  async loadStarredMessages() {
    const listEl = document.getElementById('starred-list');
    const emptyEl = document.getElementById('starred-empty');
    if (!listEl) return;

    // Remove existing items
    listEl.querySelectorAll('.starred-item').forEach(el => el.remove());

    try {
      const res = await App.Auth.authFetch('/api/starred/');
      const starred = await res.json();

      if (!starred || starred.length === 0) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
      }

      if (emptyEl) emptyEl.style.display = 'none';

      starred.forEach(item => {
        const el = document.createElement('div');
        el.className = 'starred-item';
        el.setAttribute('data-star-id', item.id);

        let metaHtml = '';
        if (item.metadata && item.metadata.sources) {
          const pages = Array.isArray(item.metadata.sources) ? item.metadata.sources.join(', ') : item.metadata.sources;
          metaHtml = `<div class="starred-meta">📖 Sources: ${App.Utils.escapeHtml(String(pages))}</div>`;
        }

        el.innerHTML = `
          <div class="starred-content">
            ${App.Utils.renderContent(item.content)}
            ${metaHtml}
          </div>
          <button class="btn btn-danger btn-icon starred-unstar-btn" onclick="App.Profile.unstarMessage('${item.id}')" title="Unstar">
            ✕
          </button>
        `;
        listEl.insertBefore(el, emptyEl);
      });
    } catch (e) {
      console.error('Failed to load starred messages:', e);
    }
  },

  /** Unstar a message */
  async unstarMessage(starId) {
    try {
      const res = await App.Auth.authFetch(`/api/starred/${starId}`, {
        method: 'DELETE',
      });

      if (!res.ok) throw new Error('Failed to unstar');

      // Remove from UI
      const item = document.querySelector(`[data-star-id="${starId}"]`);
      if (item) {
        item.style.opacity = '0';
        item.style.transform = 'translateX(20px)';
        item.style.transition = 'all 0.3s ease';
        setTimeout(() => {
          item.remove();
          // Show empty state if no more items
          const remaining = document.querySelectorAll('.starred-item');
          if (remaining.length === 0) {
            const emptyEl = document.getElementById('starred-empty');
            if (emptyEl) emptyEl.style.display = 'block';
          }
        }, 300);
      }

      App.Utils.showToast('Message unstarred', 'success');
    } catch (e) {
      App.Utils.showToast(e.message, 'error');
    }
  },
};


/* ============================================
   INITIALIZE
   ============================================ */
document.addEventListener('DOMContentLoaded', () => {
  // Clear token if this is a new tab/session (user closed tab previously)
  if (App.Auth.getToken() && !sessionStorage.getItem('mbbs_tab_session_active')) {
    App.Auth.removeToken();
    if (window.location.pathname !== '/login' && window.location.pathname !== '/signup') {
      window.location.href = '/login';
      return;
    }
  }

  // Init sidebar on pages that use base.html
  if (document.getElementById('main-sidebar')) {
    App.Sidebar.init();
  }

  // Auto-logout after 20 minutes of inactivity
  if (App.Auth.getToken()) {
    let inactivityTimer;
    const INACTIVITY_TIMEOUT = 20 * 60 * 1000; // 20 minutes in milliseconds

    const resetInactivityTimer = () => {
      clearTimeout(inactivityTimer);
      inactivityTimer = setTimeout(() => {
        App.Utils.showToast('Logged out due to 20 minutes of inactivity.', 'warning');
        setTimeout(() => {
          App.Auth.logout();
        }, 1500);
      }, INACTIVITY_TIMEOUT);
    };

    // Events to track user activity
    const activityEvents = ['mousemove', 'mousedown', 'keypress', 'touchstart', 'scroll', 'click'];
    activityEvents.forEach(event => {
      document.addEventListener(event, resetInactivityTimer, true);
    });

    // Start timer on load
    resetInactivityTimer();
  }
});
