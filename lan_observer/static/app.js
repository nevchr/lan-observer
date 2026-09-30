'use strict';
const scanNetwork = document.getElementById('scan-network');
if (scanNetwork) {
  const selection = document.getElementById('scan-selection');
  scanNetwork.addEventListener('change', () => {
    const option = scanNetwork.selectedOptions[0];
    selection.textContent = option?.value
      ? `Selected: ${option.dataset.name} · ${option.dataset.scope}`
      : 'Choose a network to see its range.';
  });
}
for (const button of document.querySelectorAll('[data-copy]')) {
  button.addEventListener('click', async () => {
    const feedback = button.nextElementSibling;
    try { await navigator.clipboard.writeText(button.dataset.copy); feedback.textContent = 'Copied'; }
    catch { feedback.textContent = 'Copy unavailable. Select the address and copy it manually.'; }
  });
}
for (const form of document.querySelectorAll('[data-unsaved]')) {
  let dirty = false;
  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
}
const scan = document.querySelector('[data-scan-url]');
if (scan) {
  let failures = 0;
  async function poll() {
    try {
      const response = await fetch(scan.dataset.scanUrl, {headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error('Unable to read scan');
      const result = await response.json();
      document.getElementById('scan-phase').textContent = result.status.charAt(0).toUpperCase() + result.status.slice(1);
      document.getElementById('scan-count').textContent = `${result.completed} of ${result.total} probes finished`;
      document.getElementById('scan-progress').value = result.completed;
      failures = 0;
      if (!['queued','discovering','enriching','canceling'].includes(result.status)) { location.reload(); return; }
    } catch {
      failures++;
      document.getElementById('scan-count').textContent = 'Progress is temporarily unavailable. Retrying… You can also refresh this page.';
    }
    setTimeout(poll, Math.min(1000 * 2 ** failures, 15000));
  }
  setTimeout(poll, 1000);
}
