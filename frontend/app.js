"use strict";

// API CONFIGURATION: provisional contract; replace these routes with the backend team's API.
// POST multipart: file, meeting_date, optional num_speakers. Response: {job_id, status}.
// GET status: {status, stage?, progress? (0..100), error?}. Success status: completed.
// GET result: {summary: string[], transcript: [{id?, start, speaker, text}],
// tasks: [{task, responsible?, deadline?, evidence?, timestamp?}], document_url?: string}.
// document_url must reference an existing DOCX on the configured backend origin.
const API = Object.freeze({
  baseUrl: location.protocol === "file:" ? "http://127.0.0.1:8000" : location.origin,
  health: "/api/health",
  upload: "/api/meetings",
  status: (id) => `/api/meetings/${encodeURIComponent(id)}/status`,
  result: (id) => `/api/meetings/${encodeURIComponent(id)}/result`,
  pollIntervalMs: 1800,
  requestTimeoutMs: 30000,
  uploadTimeoutMs: 120000,
  maxPollingMs: 60 * 60 * 1000,
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
const state = {file: null, busy: false, documentUrl: null, transcript: []};
const stageElements = [...document.querySelectorAll("[data-stage]")];

class ApiError extends Error {
  constructor(message, offline = false) { super(message); this.offline = offline; }
}

function localUrl(path) {
  const base = new URL(API.baseUrl);
  const url = new URL(path, `${base.origin}/`);
  if (!["http:", "https:"].includes(url.protocol) || url.origin !== base.origin || url.username || url.password) {
    throw new ApiError("Сервер вернул недопустимый адрес документа.");
  }
  return url.href;
}

async function request(path, options = {}, asBlob = false) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.body ? API.uploadTimeoutMs : API.requestTimeoutMs);
  try {
    const response = await fetch(localUrl(path), {...options, signal: controller.signal, redirect: "error", cache: "no-store"});
    if (!response.ok) {
      if ([404, 502, 503, 504].includes(response.status)) throw new ApiError("Backend недоступен. Проверьте запуск локального сервера и адрес API.", true);
      throw new ApiError(`Не удалось выполнить запрос (HTTP ${response.status}). Попробуйте ещё раз.`);
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
    const complete = status === "completed" || (current >= 0 && index < current);
    const active = index === current;
    item.className = complete ? "complete" : active ? "active" : "";
    item.querySelector(".stage-icon").textContent = complete ? "✓" : String(index + 1);
    item.querySelector(".stage-state").textContent = active ? "В процессе" : "";
    if (active) item.setAttribute("aria-current", "step"); else item.removeAttribute("aria-current");
  });
}

function showError(message) { $("error-message").textContent = message; $("error-message").hidden = false; }
function clearError() { $("error-message").hidden = true; $("error-message").textContent = ""; }
function setBusy(busy) {
  state.busy = busy;
  ["audio-file", "remove-file", "process-button", "meeting-date", "speaker-count"].forEach((id) => { $(id).disabled = busy; });
  $("upload-form").setAttribute("aria-busy", String(busy));
  $("download-button").disabled = busy || !state.documentUrl;
}

function resetResults() {
  state.documentUrl = null;
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

function renderResults(data) {
  if (!data || !Array.isArray(data.summary) || !Array.isArray(data.transcript) || !Array.isArray(data.tasks) ||
      data.summary.some((point) => !nonempty(point)) ||
      data.transcript.some((segment) => !segment || typeof segment.text !== "string") ||
      data.tasks.some((task) => !task || !nonempty(task.task))) {
    throw new ApiError("Формат результата не соответствует API: ожидаются summary, transcript и tasks.");
  }
  const documentUrl = nonempty(data.document_url) ? localUrl(data.document_url) : null;
  // Keep segment IDs and independent fields for a future editor/save API.
  state.transcript = data.transcript.map((segment, index) => ({...segment, id: segment.id ?? index}));
  data.summary.forEach((point) => $("summary-list").append(node("li", "", point)));
  $("summary-count").textContent = String(data.summary.length);
  $("summary-empty").hidden = data.summary.length > 0;
  $("summary-list").hidden = !data.summary.length;
  if (!data.summary.length) $("summary-empty").querySelector("p").textContent = "Сервер не вернул ключевые выводы.";
  const speakers = new Map();
  state.transcript.forEach((segment) => {
    const row = node("div", "transcript-segment");
    row.dataset.segmentId = String(segment.id);
    const content = node("div", "segment-content");
    const sourceSpeaker = nonempty(segment.speaker) || (Number.isFinite(segment.speaker) ? String(segment.speaker) : null);
    if (sourceSpeaker && !speakers.has(sourceSpeaker)) speakers.set(sourceSpeaker, speakers.size + 1);
    const label = sourceSpeaker ? (/^SPEAKER[_ ]?\d+$/i.test(sourceSpeaker) || /^\d+$/.test(sourceSpeaker) ? `Говорящий ${speakers.get(sourceSpeaker)}` : sourceSpeaker) : "Говорящий не указан";
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
  data.tasks.forEach((task) => {
    const row = node("tr");
    const evidence = nonempty(task.evidence);
    const time = timestamp(task.timestamp);
    [task.task, nonempty(task.responsible), nonempty(task.deadline), evidence ? `${time !== "—" ? `${time} · ` : ""}${evidence}` : null].forEach((value) => {
      row.append(node("td", value ? "" : "missing", value || "Не указан"));
    });
    $("task-list").append(row);
  });
  $("task-count").textContent = String(data.tasks.length);
  $("tasks-empty").hidden = data.tasks.length > 0;
  if (!data.tasks.length) $("tasks-empty").querySelector("p").textContent = "В результате обработки поручения отсутствуют.";
  $("result-state").textContent = "Результаты обработки";
  if (documentUrl) {
    state.documentUrl = documentUrl;
    $("document-note").textContent = "Документ предоставлен сервером.";
  } else {
    $("document-note").textContent = "Сервер ещё не предоставил DOCX-документ.";
  }
}

async function processMeeting(event) {
  event.preventDefault();
  if (state.busy) return;
  clearError();
  if (!state.file) { showError("Файл не выбран. Добавьте запись совещания MP3 / MPEG."); $("audio-file").focus(); return; }
  if (!$("meeting-date").reportValidity() || !$("speaker-count").reportValidity()) return;
  resetResults();
  setBusy(true);
  setStatus("ready", "Отправка записи на локальный сервер…");
  try {
    const form = new FormData();
    form.append("file", state.file);
    form.append("meeting_date", $("meeting-date").value);
    if ($("speaker-count").value) form.append("num_speakers", $("speaker-count").value);
    let job = await request(API.upload, {method: "POST", body: form});
    connection(true);
    if (!job || !["string", "number"].includes(typeof job.job_id) || String(job.job_id).trim() === "") throw new ApiError("Сервер не вернул идентификатор задания.");
    const id = job.job_id;
    const started = Date.now();
    while (true) {
      if (!job || typeof job.status !== "string") throw new ApiError("Сервер не вернул статус задания.");
      if (["failed", "error"].includes(job.status)) throw new ApiError(nonempty(job.error) || "Не удалось обработать запись. Попробуйте другой файл MP3 / MPEG.");
      if (job.status === "completed") break;
      const stage = stages.includes(job.stage) ? job.stage : stages.includes(job.status) ? job.status : null;
      setStatus(stage || "processing", stage ? "Выполняется на локальном сервере." : "Ожидаем сведения о текущем этапе от сервера.", Number.isFinite(job.progress) ? Math.min(99, job.progress) : undefined);
      if (Date.now() - started > API.maxPollingMs) throw new ApiError("Ожидание результата превысило 60 минут. Проверьте состояние задания на сервере.");
      await new Promise((resolve) => setTimeout(resolve, API.pollIntervalMs));
      job = await request(API.status(id));
    }
    const result = await request(API.result(id));
    renderResults(result);
    setBusy(false);
    setStatus("completed", "Результаты совещания получены с локального сервера.", 100);
  } catch (error) {
    setBusy(false);
    if (error.offline) connection(false);
    setStatus(error.offline ? "offline" : "error", "Протокол не сформирован. Можно повторить попытку.");
    showError(error.message);
  }
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
  if (!state.documentUrl || state.busy) return;
  clearError();
  setBusy(true);
  try {
    const blob = await request(state.documentUrl, {}, true);
    const url = URL.createObjectURL(blob);
    const link = node("a");
    link.href = url;
    link.download = "meeting-protocol.docx";
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    connection(true);
  } catch (error) {
    if (error.offline) connection(false);
    showError(`Не удалось скачать документ. ${error.message}`);
  } finally { setBusy(false); }
});

const today = new Date();
$("meeting-date").value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
// A health failure never invents a processing outcome or overwrites an active job.
request(API.health).then(() => { if (!state.busy) connection(true); }).catch(() => {
  if (state.busy) return;
  connection(false);
  if (!state.file) setStatus("offline", "Запустите локальный сервер. Запись можно выбрать заранее.");
});
