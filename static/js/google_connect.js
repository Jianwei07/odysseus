/* Shared "Connect with Google" form.
 *
 * One source of truth for the OAuth client-credential form used by both the
 * calendar settings overlay and the Settings → Integrations panel. Renders the
 * label / client-id / client-secret inputs + the redirect-URI hint, POSTs to
 * the shared /api/google/accounts endpoint, and opens Google's consent screen.
 *
 * Secrets are sent over same-origin to the local backend, which encrypts them
 * at rest — nothing is persisted client-side.
 */

const API_BASE = window.location.origin;

/**
 * Render the Google connect form into `containerEl`.
 * @param {HTMLElement} containerEl - element to render the form into.
 * @param {object} [opts]
 * @param {function} [opts.onCreated] - called after the account shell is created
 *        and the consent tab is opened (e.g. to refresh an account list).
 */
export function showGoogleConnectForm(containerEl, opts = {}) {
  if (!containerEl) return;
  const onCreated = typeof opts.onCreated === 'function' ? opts.onCreated : () => {};
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const inp = 'background:none;border:1px solid var(--border);border-radius:4px;padding:5px 7px;color:var(--fg);font-size:12px;';
  const redirect = `${window.location.origin}/api/google/oauth/callback`;
  containerEl.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:6px;border:1px solid var(--border);border-radius:6px;padding:8px;">
      <div style="font-size:11px;opacity:0.65;line-height:1.5;">Paste your Google OAuth <b>Web application</b> client. In Google Cloud Console add this redirect URI to it:<br><code style="font-size:10px;word-break:break-all;">${esc(redirect)}</code></div>
      <input id="gc-label" placeholder="Label (e.g. Personal Google)" style="${inp}" />
      <input id="gc-cid" placeholder="Client ID" style="${inp}" />
      <input id="gc-secret" type="password" placeholder="Client Secret" style="${inp}" />
      <button id="gc-connect" class="memory-toolbar-btn" style="cursor:pointer;">Connect with Google</button>
      <div id="gc-status" style="font-size:11px;opacity:0.7;"></div>
    </div>`;
  const status = containerEl.querySelector('#gc-status');
  containerEl.querySelector('#gc-connect').addEventListener('click', async () => {
    const label = containerEl.querySelector('#gc-label').value.trim();
    const client_id = containerEl.querySelector('#gc-cid').value.trim();
    const client_secret = containerEl.querySelector('#gc-secret').value.trim();
    if (!client_id || !client_secret) { status.textContent = 'Client ID and secret are required.'; return; }
    status.textContent = 'Creating account…';
    try {
      const r = await fetch(`${API_BASE}/api/google/accounts`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label, client_id, client_secret }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.authorize_url) {
        status.innerHTML = 'Opening Google sign-in… After you approve, the calendar syncs automatically.';
        window.open(d.authorize_url, '_blank', 'noopener');
        onCreated(d);
      } else {
        status.textContent = d.detail || d.error || 'Failed to create account.';
      }
    } catch (e) {
      status.textContent = 'Request failed.';
    }
  });
}
