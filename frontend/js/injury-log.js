/**
 * injury-log.js — quick-log modal + active entry strip (issue #1350)
 *
 * Exposes:
 *   InjuryLog.openModal()       — open the quick-log modal
 *   InjuryLog.renderActiveStrip(containerId)  — render active entries into a container
 */

const InjuryLog = (() => {
  const KIND_LABELS = { injury: 'Injury', illness: 'Illness', niggle: 'Niggle' };
  const SEV_LABELS  = { 1: 'Minor', 2: 'Moderate', 3: 'Severe' };

  // ── Modal ────────────────────────────────────────────────────────────────

  function _buildModal() {
    const el = document.createElement('div');
    el.id = 'injury-log-modal';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-label', 'Log niggle / illness');
    el.style.cssText = `
      display:none; position:fixed; inset:0; z-index:9000;
      background:rgba(0,0,0,0.45); justify-content:center; align-items:flex-end;
    `;

    const today = new Date().toISOString().split('T')[0];

    el.innerHTML = `
      <div style="
        background:#fff; border-radius:16px 16px 0 0; width:100%; max-width:480px;
        padding:24px 20px 32px; font-family:'Inter Tight',system-ui,sans-serif;
      ">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:18px;">
          <h2 style="margin:0; font-size:17px; font-weight:700; color:#0b1530;">Log niggle / illness</h2>
          <button id="ilm-close" type="button" aria-label="Close"
            style="background:none; border:none; font-size:22px; color:#6b7280; cursor:pointer; padding:0 4px;">✕</button>
        </div>

        <form id="ilm-form" novalidate>
          <!-- Kind -->
          <div style="margin-bottom:14px;">
            <label style="font-size:12px; font-weight:600; color:#5c6886; text-transform:uppercase; letter-spacing:.04em;">Type</label>
            <div style="display:flex; gap:8px; margin-top:6px;">
              ${Object.entries(KIND_LABELS).map(([v, l]) => `
                <label style="flex:1; text-align:center; cursor:pointer;">
                  <input type="radio" name="ilm-kind" value="${v}" ${v === 'niggle' ? 'checked' : ''}
                    style="position:absolute; opacity:0; width:0; height:0;">
                  <span class="ilm-kind-pill" data-val="${v}" style="
                    display:block; padding:8px 0; border-radius:999px;
                    border:1.5px solid #d8e3f5; font-size:13px; font-weight:600;
                    color:#5c6886; background:#fff; transition:all .15s;
                  ">${l}</span>
                </label>
              `).join('')}
            </div>
          </div>

          <!-- Severity -->
          <div style="margin-bottom:14px;">
            <label style="font-size:12px; font-weight:600; color:#5c6886; text-transform:uppercase; letter-spacing:.04em;">Severity</label>
            <div style="display:flex; gap:8px; margin-top:6px;">
              ${Object.entries(SEV_LABELS).map(([v, l]) => `
                <label style="flex:1; text-align:center; cursor:pointer;">
                  <input type="radio" name="ilm-severity" value="${v}" ${v === '1' ? 'checked' : ''}
                    style="position:absolute; opacity:0; width:0; height:0;">
                  <span class="ilm-sev-pill" data-val="${v}" style="
                    display:block; padding:8px 0; border-radius:999px;
                    border:1.5px solid #d8e3f5; font-size:13px; font-weight:600;
                    color:#5c6886; background:#fff; transition:all .15s;
                  ">${l}</span>
                </label>
              `).join('')}
            </div>
          </div>

          <!-- Body area -->
          <div style="margin-bottom:14px;">
            <label for="ilm-area" style="font-size:12px; font-weight:600; color:#5c6886; text-transform:uppercase; letter-spacing:.04em;">Body area <span style="font-weight:400;">(optional)</span></label>
            <input id="ilm-area" type="text" maxlength="100" placeholder="e.g. left calf"
              style="display:block; width:100%; margin-top:6px; padding:10px 12px; border:1.5px solid #d8e3f5;
                     border-radius:10px; font-size:14px; font-family:inherit; color:#0b1530; box-sizing:border-box;">
          </div>

          <!-- Started on -->
          <div style="margin-bottom:14px;">
            <label for="ilm-started" style="font-size:12px; font-weight:600; color:#5c6886; text-transform:uppercase; letter-spacing:.04em;">Started on</label>
            <input id="ilm-started" type="date" value="${today}" max="${today}"
              style="display:block; width:100%; margin-top:6px; padding:10px 12px; border:1.5px solid #d8e3f5;
                     border-radius:10px; font-size:14px; font-family:inherit; color:#0b1530; box-sizing:border-box;">
          </div>

          <!-- Notes -->
          <div style="margin-bottom:20px;">
            <label for="ilm-notes" style="font-size:12px; font-weight:600; color:#5c6886; text-transform:uppercase; letter-spacing:.04em;">Notes <span style="font-weight:400;">(optional)</span></label>
            <textarea id="ilm-notes" rows="2" maxlength="500" placeholder="Optional details…"
              style="display:block; width:100%; margin-top:6px; padding:10px 12px; border:1.5px solid #d8e3f5;
                     border-radius:10px; font-size:14px; font-family:inherit; color:#0b1530; box-sizing:border-box; resize:vertical;"></textarea>
          </div>

          <p id="ilm-error" style="color:#7a1a1a; font-size:13px; margin:0 0 10px; min-height:18px;"></p>

          <button type="submit" style="
            width:100%; padding:13px; border:none; border-radius:12px;
            background:#5a8dee; color:#fff; font-size:15px; font-weight:700;
            font-family:inherit; cursor:pointer; letter-spacing:-.01em;
          ">Save entry</button>
        </form>
      </div>
    `;

    document.body.appendChild(el);
    _bindModal(el, today);
    return el;
  }

  function _bindModal(el, _today) {
    // Kind pill highlight
    el.querySelectorAll('input[name="ilm-kind"]').forEach(radio => {
      radio.addEventListener('change', () => _updatePills(el, 'ilm-kind', 'ilm-kind-pill', '#5a8dee'));
    });
    el.querySelectorAll('input[name="ilm-severity"]').forEach(radio => {
      radio.addEventListener('change', () => _updatePills(el, 'ilm-severity', 'ilm-sev-pill', '#5a8dee'));
    });

    // Close
    el.querySelector('#ilm-close').addEventListener('click', closeModal);
    el.addEventListener('click', e => { if (e.target === el) closeModal(); });

    // Submit
    el.querySelector('#ilm-form').addEventListener('submit', async e => {
      e.preventDefault();
      const err = el.querySelector('#ilm-error');
      err.textContent = '';
      const kind = el.querySelector('input[name="ilm-kind"]:checked')?.value;
      const severity = parseInt(el.querySelector('input[name="ilm-severity"]:checked')?.value || '0', 10);
      const started_on = el.querySelector('#ilm-started').value;
      const body_area = el.querySelector('#ilm-area').value.trim() || null;
      const notes = el.querySelector('#ilm-notes').value.trim() || null;

      if (!started_on) { err.textContent = 'Started on is required.'; return; }

      try {
        const csrfToken = document.cookie.split(';')
          .map(c => c.trim()).find(c => c.startsWith('csrf_token='))
          ?.split('=')[1];
        const res = await fetch('/api/injury-log', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
          },
          body: JSON.stringify({ kind, severity, started_on, body_area, notes }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          err.textContent = data.detail || `Error ${res.status}`;
          return;
        }
        closeModal();
        // Refresh any active strip on the page
        document.querySelectorAll('[data-injury-strip]').forEach(container => {
          renderActiveStrip(container.id);
        });
      } catch (ex) {
        err.textContent = 'Network error — please try again.';
      }
    });

    // Initial pill highlight
    _updatePills(el, 'ilm-kind', 'ilm-kind-pill', '#5a8dee');
    _updatePills(el, 'ilm-severity', 'ilm-sev-pill', '#5a8dee');
  }

  function _updatePills(el, radioName, pillClass, activeColor) {
    const checked = el.querySelector(`input[name="${radioName}"]:checked`)?.value;
    el.querySelectorAll(`.${pillClass}`).forEach(span => {
      const active = span.dataset.val === checked;
      span.style.background = active ? activeColor : '#fff';
      span.style.color = active ? '#fff' : '#5c6886';
      span.style.borderColor = active ? activeColor : '#d8e3f5';
    });
  }

  function openModal() {
    let el = document.getElementById('injury-log-modal');
    if (!el) el = _buildModal();
    // Reset form
    const form = el.querySelector('#ilm-form');
    if (form) form.reset();
    const today = new Date().toISOString().split('T')[0];
    const startedInput = el.querySelector('#ilm-started');
    if (startedInput) startedInput.value = today;
    el.querySelector('#ilm-error').textContent = '';
    _updatePills(el, 'ilm-kind', 'ilm-kind-pill', '#5a8dee');
    _updatePills(el, 'ilm-severity', 'ilm-sev-pill', '#5a8dee');
    el.style.display = 'flex';
  }

  function closeModal() {
    const el = document.getElementById('injury-log-modal');
    if (el) el.style.display = 'none';
  }

  // ── Active strip ─────────────────────────────────────────────────────────

  async function renderActiveStrip(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    try {
      const res = await fetch('/api/injury-log/active');
      if (res.status === 401) return; // not logged in
      if (!res.ok) return;
      const entries = await res.json();

      if (!entries.length) {
        container.innerHTML = '';
        return;
      }

      const sevColors = {
        1: { bg: '#fff0c4', text: '#6b4408', dot: '#f59e0b' },
        2: { bg: '#ffe1d4', text: '#8a3d12', dot: '#ea580c' },
        3: { bg: '#ffd9d9', text: '#7a1a1a', dot: '#dc2626' },
      };

      const items = entries.map(e => {
        const col = sevColors[e.severity] || sevColors[1];
        const label = [KIND_LABELS[e.kind] || e.kind, e.body_area].filter(Boolean).join(' — ');
        const sevLabel = SEV_LABELS[e.severity] || '';
        return `
          <div style="
            display:inline-flex; align-items:center; gap:6px;
            padding:5px 11px 5px 8px; border-radius:999px;
            background:${col.bg}; color:${col.text};
            font-size:12px; font-weight:600; white-space:nowrap;
          ">
            <span style="width:7px; height:7px; border-radius:50%; background:${col.dot}; flex-shrink:0;"></span>
            ${label} · ${sevLabel}
            <button data-id="${e.id}" class="ilm-resolve-btn"
              style="margin-left:4px; background:none; border:none; font-size:11px; font-weight:700;
                     color:${col.text}; opacity:.7; cursor:pointer; padding:0; font-family:inherit;"
              title="Mark resolved">✓</button>
          </div>
        `;
      }).join('');

      container.setAttribute('data-injury-strip', '1');
      container.innerHTML = `
        <div style="
          display:flex; flex-wrap:wrap; gap:7px; padding:10px 16px;
          background:rgba(255,255,255,0.55); border-radius:12px;
          margin-bottom:12px; align-items:center;
        ">
          <span style="font-size:11px; font-weight:700; color:#5c6886; text-transform:uppercase;
                       letter-spacing:.05em; margin-right:4px;">Active</span>
          ${items}
        </div>
      `;

      // Resolve buttons
      container.querySelectorAll('.ilm-resolve-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
          const id = btn.dataset.id;
          const today = new Date().toISOString().split('T')[0];
          const csrfToken = document.cookie.split(';')
            .map(c => c.trim()).find(c => c.startsWith('csrf_token='))
            ?.split('=')[1];
          try {
            await fetch(`/api/injury-log/${id}`, {
              method: 'PATCH',
              headers: {
                'Content-Type': 'application/json',
                ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
              },
              body: JSON.stringify({ ended_on: today }),
            });
            renderActiveStrip(containerId);
          } catch (_) {}
        });
      });
    } catch (_) {}
  }

  return { openModal, closeModal, renderActiveStrip };
})();
