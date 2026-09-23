// Integrate these functions into the existing frontend; no new UI is required.
// Serve this frontend from the same FastAPI origin.
const API_BASE = '';

async function checked(response) {
  if (response.ok) return response;
  let message = `Ошибка сервера (${response.status})`;
  try {
    const body = await response.json();
    message = typeof body.detail === 'string' ? body.detail : 'Проверьте формат отправленных данных.';
  } catch { /* Non-JSON server / proxy response. */ }
  throw new Error(message);
}

export async function analyzeAudio(file, {language, signal} = {}) {
  const form = new FormData();
  form.append('file', file);
  const query = language ? `?language=${encodeURIComponent(language)}` : '';
  const response = await checked(await fetch(`${API_BASE}/analyze-audio${query}`, {
    method: 'POST', body: form, signal,
  }));
  // Display warnings as well as protocol; diarization may be unavailable.
  return response.json();
}

export async function analyzeText(text, {signal} = {}) {
  const response = await checked(await fetch(`${API_BASE}/analyze`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text}), signal,
  }));
  return response.json();
}

export async function downloadProtocol(protocol) {
  // Pass the nested .protocol from analyzeAudio, or the result of analyzeText.
  const response = await checked(await fetch(`${API_BASE}/export-docx`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(protocol),
  }));
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'meeting_protocol.docx';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
