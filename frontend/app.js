"use strict";

// API CONFIGURATION: feature/backend-uldana (backend/main.py and backend/schemas.py).
// Separate local frontend servers connect directly to FastAPI; configure FRONTEND_ORIGINS there.
// POST analyzeAudio: FormData containing only file; response {protocol, language,
// diarization_available, warnings}. No polling or backend stage telemetry exists.
// POST exportDocx: the unchanged protocol as JSON; response is a DOCX blob.
const API = Object.freeze({
  baseUrl: "http://127.0.0.1:8000",
  health: "/health",
  transcribe: "/transcribe",
  analyzeAudio: "/analyze-audio",
  exportDocx: "/export-docx",
  requestTimeoutMs: 30000,
  analysisTimeoutMs: 60 * 60 * 1000,
  exportTimeoutMs: 120000,
});

const $ = (id) => document.getElementById(id);
const stages = ["preparing", "transcribing", "diarizing", "analyzing", "generating"];
const labels = {
  idle: "Ожидается загрузка", ready: "Готово к обработке",
  preparing: "Подготовка аудио", transcribing: "Распознавание речи",
  diarizing: "Разделение говорящих", analyzing: "Анализ поручений",
  generating: "Формирование протокола", completed: "Готово",
  error: "Ошибка", offline: "Backend недоступен",
};
const state = {file: null, busy: false, protocol: null, transcript: [], diarizationAvailable: null, exported: false};
const stageElements = [...document.querySelectorAll("[data-stage]")];
const warningsElement = document.createElement("p");
warningsElement.className = "processing-note";
warningsElement.setAttribute("role", "status");
warningsElement.hidden = true;
document.querySelector(".results-heading").after(warningsElement);

class ApiError extends Error {
  constructor(message, offline = false) { super(message); this.offline = offline; }
}

function localUrl(path) {
  const base = new URL(API.baseUrl);
  const url = new URL(path, `${base.origin}/`);
  if (!["http:", "https:"].includes(url.protocol) || url.origin !== base.origin || url.username || url.password) {
    throw new ApiError("Некорректный адрес локального API.");
  }
  return url.href;
}

async function request(path, options = {}, asBlob = false) {
  const controller = new AbortController();
  const timeoutMs = path === API.analyzeAudio ? API.analysisTimeoutMs : asBlob ? API.exportTimeoutMs : API.requestTimeoutMs;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(localUrl(path), {...options, signal: controller.signal, redirect: "error", cache: "no-store"});
    if (!response.ok) {
      const messages = {
        404: "API не найден. Проверьте адрес и версию backend.",
        413: "Файл слишком большой. Максимальный размер аудио: 32 МиБ.",
        415: "Формат аудио не поддерживается. Выберите MP3 / MPEG.",
        422: "Не удалось проверить данные или распознать речь. Проверьте запись.",
        500: "Ошибка обработки на сервере. Попробуйте ещё раз или проверьте backend.",
        502: "Backend недоступен. Проверьте запуск локального сервера.",
        503: "Backend недоступен: обработчик занят или локальная модель не готова.",
        504: "Backend не ответил вовремя. Проверьте локальный сервер.",
      };
      let detail = "";
      try {
        const body = await response.json();
        if (typeof body.detail === "string") detail = body.detail.trim();
      } catch { /* A proxy may return a non-JSON error page. */ }
      const message = messages[response.status] || `Не удалось выполнить запрос (HTTP ${response.status}).`;
      throw new ApiError(`${message}${detail ? ` ${detail}` : ""}`, [502, 503, 504].includes(response.status));
    }
    if (asBlob) {
      const type = (response.headers.get("content-type") || "").split(";")[0].trim();
      if (!["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/octet-stream"].includes(type)) {
        throw new ApiError("Сервер не вернул DOCX-документ.");
      }
      const blob = await response.blob();
      const signature = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
      if (signature[0] !== 80 || signature[1] !== 75 || signature[2] !== 3 || signature[3] !== 4) throw new ApiError("Получен пустой или некорректный DOCX-документ.");
      return blob;
    }
    try { return await response.json(); }
    catch { throw new ApiError("Сервер вернул некорректный ответ. Проверьте формат API."); }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("Backend недоступен. Проверьте запуск локального сервера и соединение. Обработка на сервере могла продолжиться.", true);
  } finally { clearTimeout(timeout); }
}

function connection(online) {
  $("connection").textContent = online ? "Backend подключён" : "Backend недоступен";
  $("connection").className = `connection ${online ? "online" : "offline"}`;
}

function setStatus(status, description, progress) {
  $("status-title").textContent = labels[status] || "Обработка";
  $("status-description").textContent = description;
  $("status-dot").className = `status-dot ${state.busy ? "busy" : ""} ${status === "completed" ? "done" : status}`;
  if (Number.isFinite(progress)) $("progress").value = Math.max(0, Math.min(100, progress));
  else if (state.busy) $("progress").removeAttribute("value");
  else $("progress").value = status === "completed" ? 100 : 0;
  const current = stages.indexOf(status);
  stageElements.forEach((item, index) => {
    const unavailable = item.dataset.stage === "diarizing" && state.diarizationAvailable === false;
    const waitingForExport = item.dataset.stage === "generating" && !state.exported;
    const complete = status === "completed" && !unavailable && !waitingForExport;
    const active = index === current && !unavailable;
    item.className = complete ? "complete" : active ? "active" : "";
    item.querySelector(".stage-icon").textContent = complete ? "✓" : String(index + 1);
    item.querySelector(".stage-state").textContent = unavailable ? "Недоступно" : active ? (status === "generating" ? "Экспорт" : "Ориентировочно") : status === "completed" && waitingForExport ? "При скачивании" : "";
    if (active) item.setAttribute("aria-current", "step"); else item.removeAttribute("aria-current");
  });
}

function showError(message) { $("error-message").textContent = message; $("error-message").hidden = false; }
function clearError() { $("error-message").hidden = true; $("error-message").textContent = ""; }
function setBusy(busy) {
  state.busy = busy;
  ["audio-file", "remove-file", "process-button", "meeting-date", "speaker-count"].forEach((id) => { $(id).disabled = busy; });
  $("upload-form").setAttribute("aria-busy", String(busy));
  $("download-button").disabled = busy || !state.protocol;
}

function resetResults() {
  state.protocol = null;
  state.diarizationAvailable = null;
  state.exported = false;
  warningsElement.hidden = true;
  warningsElement.textContent = "";
  state.transcript = [];
  ["summary-list", "transcript-list", "task-list"].forEach((id) => $(id).replaceChildren());
  ["summary-empty", "transcript-empty", "tasks-empty"].forEach((id) => { $(id).hidden = false; });
  $("summary-list").hidden = true;
  $("transcript-list").hidden = true;
  $("summary-count").textContent = "0";
  $("transcript-count").textContent = "0 реплик";
  $("task-count").textContent = "0";
  $("result-state").textContent = "Нет обработанной записи";
  $("document-note").textContent = "Документ ещё не сформирован.";
  $("summary-empty").querySelector("p").textContent = "Ключевые выводы встречи появятся после обработки записи.";
  $("transcript-empty").querySelector("p").textContent = "Здесь будут текст, говорящие и временные отметки.";
  $("tasks-empty").querySelector("p").textContent = "Договорённости и фрагменты-основания появятся после обработки.";
  $("download-button").disabled = true;
}

function selectFile(files) {
  if (state.busy || !files.length) return;
  clearError();
  resetResults();
  state.file = null;
  $("audio-file").value = "";
  $("selected-file").hidden = true;
  const file = files[0];
  // Windows may report an empty or inconsistent MIME type; use the file extension.
  if (files.length !== 1 || !/\.(mp3|mpeg)$/i.test(file.name) || file.size === 0) {
    setStatus("error", "Запись не выбрана.");
    showError(files.length !== 1 ? "Выберите одну запись MP3 / MPEG." : file.size === 0 ? "Файл пуст. Выберите другую запись MP3 / MPEG." : "Неверный тип файла. Допускаются только файлы MP3 / MPEG.");
    return;
  }
  state.file = file;
  $("file-name").textContent = file.name;
  $("file-size").textContent = `${(file.size / 1024 / 1024).toLocaleString("ru-RU", {maximumFractionDigits: 2})} МБ`;
  $("selected-file").hidden = false;
  setStatus("ready", "Запись выбрана. Можно сформировать протокол.", 0);
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function timestamp(value) {
  if (typeof value === "string" && /^\d{1,3}:\d{2}(:\d{2})?$/.test(value)) return value;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—";
  const seconds = Math.floor(value);
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
function nonempty(value) { return typeof value === "string" && value.trim() ? value.trim() : null; }

function renderResults(result) {
  const data = result?.protocol;
  if (!data || !nonempty(data.summary) || !Array.isArray(data.transcript) || !Array.isArray(data.action_items) ||
      typeof result.diarization_available !== "boolean" || !Array.isArray(result.warnings) ||
      result.warnings.some((warning) => typeof warning !== "string") ||
      data.transcript.some((segment) => !segment || typeof segment.text !== "string") ||
      data.action_items.some((task) => !task || !nonempty(task.text) || !nonempty(task.source_fragment))) {
    throw new ApiError("Некорректный ответ API: ожидается protocol с summary, transcript и action_items.");
  }
  state.diarizationAvailable = result.diarization_available;
  const warnings = [...result.warnings];
  if (!state.diarizationAvailable) warnings.unshift("Разделение говорящих недоступно. Реплики не привязаны к участникам.");
  warningsElement.textContent = [...new Set(warnings.filter(Boolean))].join(" · ");
  warningsElement.hidden = !warningsElement.textContent;
  // Summary is backend-authored text, not an array. Preserve its content without inventing points.
  const summary = data.summary.split(/\r?\n/).map((point) => point.trim()).filter(Boolean);
  // Keep segment IDs and independent fields for a future editor/save API.
  state.transcript = data.transcript.map((segment, index) => ({...segment, id: segment.id ?? index}));
  summary.forEach((point) => $("summary-list").append(node("li", "", point)));
  $("summary-count").textContent = String(summary.length);
  $("summary-empty").hidden = true;
  $("summary-list").hidden = false;
  state.transcript.forEach((segment) => {
    const row = node("div", "transcript-segment");
    row.dataset.segmentId = String(segment.id);
    const content = node("div", "segment-content");
    const label = state.diarizationAvailable ? nonempty(segment.speaker) || "Говорящий не указан" : "Говорящий не определён";
    const speaker = node("span", "speaker", label);
    speaker.dataset.field = "speaker";
    const text = node("p", "transcript-text", segment.text);
    text.dataset.field = "text";
    content.append(speaker, text);
    row.append(node("span", "timestamp", timestamp(segment.start)), content);
    $("transcript-list").append(row);
  });
  $("transcript-count").textContent = `Реплик: ${data.transcript.length}`;
  $("transcript-empty").hidden = data.transcript.length > 0;
  $("transcript-list").hidden = !data.transcript.length;
  if (!data.transcript.length) $("transcript-empty").querySelector("p").textContent = "Сервер не вернул реплики.";
  data.action_items.forEach((task) => {
    const row = node("tr");
    [task.text, nonempty(task.responsible), nonempty(task.deadline), task.source_fragment].forEach((value) => {
      row.append(node("td", value ? "" : "missing", value || "Не указан"));
    });
    $("task-list").append(row);
  });
  $("task-count").textContent = String(data.action_items.length);
  $("tasks-empty").hidden = data.action_items.length > 0;
  if (!data.action_items.length) $("tasks-empty").querySelector("p").textContent = "В результате обработки поручения отсутствуют.";
  $("result-state").textContent = "Результаты обработки";
  state.protocol = data;
  $("document-note").textContent = "Протокол готов. DOCX будет сформирован при скачивании.";
}

async function processMeeting(event) {
  event.preventDefault();
  if (state.busy) return;
  clearError();
  if (!state.file) { showError("Файл не выбран. Добавьте запись совещания MP3 / MPEG."); $("audio-file").focus(); return; }
  if (!$("meeting-date").reportValidity() || !$("speaker-count").reportValidity()) return;
  resetResults();
  setBusy(true);
  const progressNote = "Ориентировочный этап интерфейса. Сервер не сообщает текущий этап; ожидаем результат.";
  setStatus("preparing", progressNote);
  // These timers guide the UI only: no percentages or completed steps before the response.
  const progressTimers = [
    setTimeout(() => setStatus("transcribing", progressNote), 2000),
    setTimeout(() => setStatus("analyzing", progressNote), 8000),
  ];
  try {
    const form = new FormData();
    form.append("file", state.file);
    // Meeting date and participant count are not accepted by the current backend API.
    const result = await request(API.analyzeAudio, {method: "POST", body: form});
    connection(true);
    renderResults(result);
    setBusy(false);
    setStatus("completed", "Результаты совещания получены с локального сервера.", 100);
  } catch (error) {
    setBusy(false);
    if (error.offline) connection(false);
    setStatus(error.offline ? "offline" : "error", "Протокол не сформирован. Можно повторить попытку.");
    showError(error.message);
  } finally { progressTimers.forEach(clearTimeout); }
}

$("upload-form").addEventListener("submit", processMeeting);
$("audio-file").addEventListener("change", (event) => selectFile([...event.target.files]));
$("remove-file").addEventListener("click", () => {
  state.file = null;
  $("audio-file").value = "";
  $("selected-file").hidden = true;
  clearError(); resetResults(); setStatus("idle", "Запись ещё не выбрана.", 0);
});
const dropZone = $("drop-zone");
let dragDepth = 0;
dropZone.addEventListener("dragenter", (event) => { event.preventDefault(); if (!state.busy) { dragDepth++; dropZone.classList.add("dragging"); } });
dropZone.addEventListener("dragover", (event) => { event.preventDefault(); event.dataTransfer.dropEffect = state.busy ? "none" : "copy"; });
dropZone.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) dropZone.classList.remove("dragging"); });
dropZone.addEventListener("drop", (event) => { event.preventDefault(); dragDepth = 0; dropZone.classList.remove("dragging"); selectFile([...event.dataTransfer.files]); });
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());

$("download-button").addEventListener("click", async () => {
  if (!state.protocol || state.busy) return;
  clearError();
  setBusy(true);
  setStatus("generating", "Сервер формирует DOCX из полученного протокола.");
  try {
    const blob = await request(API.exportDocx, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(state.protocol),
    }, true);
    const url = URL.createObjectURL(blob);
    const link = node("a");
    link.href = url;
    link.download = "meeting_protocol.docx";
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    connection(true);
    state.exported = true;
    $("document-note").textContent = "DOCX получен с сервера.";
    setBusy(false);
    setStatus("completed", "Протокол и DOCX получены с локального сервера.", 100);
  } catch (error) {
    if (error.offline) connection(false);
    setBusy(false);
    setStatus(error.offline ? "offline" : "error", "Не удалось скачать DOCX. Результаты сохранены на странице; повторите скачивание.");
    showError(`Не удалось скачать документ. ${error.message}`);
  } finally { setBusy(false); }
});

const today = new Date();
$("meeting-date").value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
// Ignore a late health response after the user has started interacting with a recording.
request(API.health).then(() => { if (!state.busy && !state.file && !state.protocol) connection(true); }).catch(() => {
  if (state.busy || state.file || state.protocol) return;
  connection(false);
  if (!state.file) setStatus("offline", "Запустите локальный сервер. Запись можно выбрать заранее.");
});
