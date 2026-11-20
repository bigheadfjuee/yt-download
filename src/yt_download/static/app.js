const state = {
  authMode: "cookies_file",
  cookiesValid: false,
  eventSources: new Map(),
};

const $ = (id) => document.getElementById(id);

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i += 1;
  }
  return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatDuration(sec) {
  if (!sec) return "--:--";
  const s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`
    : `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function getAuthPayload() {
  if (state.authMode === "cookies_file") {
    return { mode: "cookies_file" };
  }
  if (state.authMode === "browser") {
    return {
      mode: "browser",
      browser: $("browserSelect").value,
      browser_profile: $("browserProfileInput").value.trim() || null,
    };
  }
  return { mode: "none" };
}

function setAuthMode(mode) {
  state.authMode = mode;
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.authMode === mode);
  });
  $("panelCookiesFile").hidden = mode !== "cookies_file";
  $("panelBrowser").hidden = mode !== "browser";
  $("panelNone").hidden = mode !== "none";
}

function renderCookieStatus(cookies) {
  const badge = $("cookieStatusBadge");
  const msg = $("cookieStatusMessage");
  const delBtn = $("deleteCookiesBtn");

  state.cookiesValid = Boolean(cookies.exists && cookies.valid_format);
  msg.textContent = cookies.message || "";
  delBtn.hidden = !cookies.exists;

  badge.className = "badge";
  if (cookies.has_auth_cookies) {
    badge.classList.add("badge-ok");
    badge.textContent = "cookies.txt 已驗證登入";
  } else if (cookies.exists) {
    badge.classList.add("badge-warn");
    badge.textContent = "cookies.txt 未含登入憑證";
  } else {
    badge.textContent = "尚未設定 cookies.txt";
  }
}

async function loadStatus() {
  const res = await fetch("/api/status");
  const data = await res.json();

  const env = data.environment;
  const badges = [];
  badges.push(
    `<span class="badge ${env.ffmpeg_available ? "badge-ok" : "badge-err"}">FFmpeg: ${
      env.ffmpeg_available ? "可用" : "缺少"
    }</span>`
  );
  const hasJs = env.node_available || env.deno_available;
  badges.push(
    `<span class="badge ${hasJs ? "badge-ok" : "badge-warn"}">JS Runtime: ${
      env.node_available ? "Node.js" : env.deno_available ? "Deno" : "未偵測"
    }</span>`
  );
  $("envBadges").innerHTML = badges.join("");
  $("downloadsDirLabel").textContent = data.downloads_dir;

  renderCookieStatus(data.cookies);

  // 若尚未上傳 cookies.txt，仍留在 cookies.txt 分頁方便使用者匯入
  setAuthMode(state.authMode);
}

async function uploadCookiesFile(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/auth/cookies", { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "上傳 cookies.txt 失敗");
    return;
  }
  renderCookieStatus(data);
}

async function saveCookiesText() {
  const content = $("cookieTextArea").value.trim();
  if (!content) return;
  const res = await fetch("/api/auth/cookies/text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "驗證 cookies 失敗");
    return;
  }
  $("cookieTextArea").value = "";
  $("pasteCookiesBox").hidden = true;
  renderCookieStatus(data);
}

async function deleteCookies() {
  const res = await fetch("/api/auth/cookies", { method: "DELETE" });
  const data = await res.json();
  renderCookieStatus(data);
}

async function probeUrl() {
  const url = $("urlInput").value.trim();
  if (!url) {
    alert("請先貼上 YouTube 網址");
    return;
  }

  $("probeError").hidden = true;
  $("probePreview").hidden = true;
  $("probeBtn").disabled = true;
  $("probeBtn").textContent = "解析中...";

  try {
    const res = await fetch("/api/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        allow_playlist: $("playlistCheck").checked,
        auth: getAuthPayload(),
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      $("probeError").textContent = data.detail || "解析失敗";
      $("probeError").hidden = false;
      return;
    }

    $("previewTitle").textContent = data.title || "未命名";
    if (data.thumbnail) {
      $("previewThumb").src = data.thumbnail;
      $("previewThumb").hidden = false;
    } else {
      $("previewThumb").hidden = true;
    }

    $("premiumBadge").hidden = !data.has_premium_format;

    if (data.is_playlist) {
      $("previewSub").textContent = `頻道：${data.uploader || "未知"} ｜ 共 ${data.entry_count} 部影片`;
      $("previewPlaylistInfo").hidden = false;
      $("previewPlaylistInfo").textContent =
        "已偵測為播放清單，請確認已勾選下方「下載整份播放清單」。";
      $("playlistCheck").checked = true;
      $("playlistOptions").hidden = false;
    } else {
      const subText =
        data.subtitles && data.subtitles.length > 0
          ? `人工字幕：${data.subtitles.slice(0, 6).join(", ")}`
          : "人工字幕：無（可勾選自動字幕）";
      $("previewSub").textContent = `頻道：${data.uploader || "未知"} ｜ 片長：${formatDuration(
        data.duration
      )} ｜ ${subText}`;
      $("previewPlaylistInfo").hidden = true;
    }

    // 填入可用串流選單
    const fmtSelect = $("formatIdSelect");
    fmtSelect.innerHTML = '<option value="">自動依上方畫質預設選擇</option>';
    (data.formats || []).forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f.format_id;
      opt.textContent = `[${f.format_id}] ${f.label}`;
      fmtSelect.appendChild(opt);
    });

    $("probePreview").hidden = false;
  } catch (err) {
    $("probeError").textContent = `連線失敗：${err.message}`;
    $("probeError").hidden = false;
  } finally {
    $("probeBtn").disabled = false;
    $("probeBtn").textContent = "解析資訊";
  }
}

async function startDownload() {
  const url = $("urlInput").value.trim();
  if (!url) {
    alert("請先貼上 YouTube 網址");
    return;
  }

  $("probeError").hidden = true;
  const subtitleLangs = $("subtitleLangsInput")
    .value.split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const payload = {
    url,
    preset: $("presetSelect").value,
    format_id: $("formatIdSelect").value || null,
    subtitles: $("subtitlesCheck").checked,
    auto_subtitles: $("autoSubtitlesCheck").checked,
    subtitle_langs: subtitleLangs,
    embed_subtitles: $("embedSubtitlesCheck").checked,
    allow_playlist: $("playlistCheck").checked,
    playlist_items: $("playlistItemsInput").value.trim() || null,
    auth: getAuthPayload(),
  };

  $("downloadBtn").disabled = true;
  try {
    const res = await fetch("/api/downloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      $("probeError").textContent = data.detail || "無法建立下載任務";
      $("probeError").hidden = false;
      return;
    }
    upsertTaskCard(data);
    subscribeTask(data.id);
  } finally {
    $("downloadBtn").disabled = false;
  }
}

function renderTaskInner(task) {
  const statusMap = {
    queued: ["排隊中", "badge"],
    downloading: ["下載中", "badge badge-warn"],
    postprocessing: ["合併/轉檔中", "badge badge-warn"],
    completed: ["已完成", "badge badge-ok"],
    failed: ["失敗", "badge badge-err"],
    cancelled: ["已取消", "badge"],
  };
  const [label, badgeClass] = statusMap[task.status] || [task.status, "badge"];
  const isRunning = ["queued", "downloading", "postprocessing"].includes(task.status);
  const pct = Math.min(100, Math.max(0, Number(task.percent || 0)));

  const speedText = task.speed ? `${formatBytes(task.speed)}/s` : "";
  const etaText = task.eta != null ? `剩餘 ${formatDuration(task.eta)}` : "";
  const sizeText = task.total_bytes
    ? `${formatBytes(task.downloaded_bytes)} / ${formatBytes(task.total_bytes)}`
    : "";
  const metaParts = [task.stage_text, `${pct.toFixed(1)}%`, sizeText, speedText, etaText].filter(Boolean);

  const filesHtml = (task.files || [])
    .map(
      (fp) =>
        `<a class="btn btn-secondary btn-sm" href="/api/files/download?path=${encodeURIComponent(
          fp
        )}">下載：${escapeHtml(fp.split("/").pop())}</a>`
    )
    .join("");

  return `
    <div class="task-top">
      <div>
        <div class="task-title">${escapeHtml(task.title)}</div>
        <div class="task-meta">${escapeHtml(metaParts.join(" ｜ "))}</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;">
        <span class="${badgeClass}">${label}</span>
        ${
          isRunning
            ? `<button type="button" class="btn btn-danger-ghost btn-sm" onclick="cancelTask('${task.id}')">取消</button>`
            : ""
        }
      </div>
    </div>
    <div class="progress-bar">
      <div class="progress-fill ${task.status === "completed" ? "done" : ""}" style="width:${pct}%"></div>
    </div>
    ${task.error ? `<div class="task-error">${escapeHtml(task.error)}</div>` : ""}
    ${filesHtml ? `<div class="task-files">${filesHtml}</div>` : ""}
  `;
}

function upsertTaskCard(task) {
  const container = $("tasksContainer");
  const empty = container.querySelector(".empty-text");
  if (empty) empty.remove();

  let el = document.getElementById(`task-${task.id}`);
  if (!el) {
    el = document.createElement("div");
    el.id = `task-${task.id}`;
    el.className = "task-item";
    container.prepend(el);
  }
  el.innerHTML = renderTaskInner(task);
}

function subscribeTask(taskId) {
  if (state.eventSources.has(taskId)) return;
  const es = new EventSource(`/api/downloads/${taskId}/events`);
  state.eventSources.set(taskId, es);

  es.onmessage = (event) => {
    const task = JSON.parse(event.data);
    upsertTaskCard(task);
    if (["completed", "failed", "cancelled"].includes(task.status)) {
      es.close();
      state.eventSources.delete(taskId);
      if (task.status === "completed") {
        loadFiles();
      }
    }
  };
  es.onerror = () => {
    es.close();
    state.eventSources.delete(taskId);
  };
}

window.cancelTask = async function cancelTask(taskId) {
  await fetch(`/api/downloads/${taskId}/cancel`, { method: "POST" });
};

async function loadTasks() {
  const res = await fetch("/api/downloads");
  const tasks = await res.json();
  if (!tasks.length) return;
  $("tasksContainer").innerHTML = "";
  tasks.reverse().forEach((task) => {
    upsertTaskCard(task);
    if (["queued", "downloading", "postprocessing"].includes(task.status)) {
      subscribeTask(task.id);
    }
  });
}

async function loadFiles() {
  const res = await fetch("/api/files");
  const files = await res.json();
  const container = $("filesContainer");
  if (!files.length) {
    container.innerHTML = '<p class="empty-text">尚無已下載檔案。</p>';
    return;
  }
  container.innerHTML = files
    .map(
      (f) => `
      <div class="file-item">
        <div>
          <div class="task-title">${escapeHtml(f.path)}</div>
          <div class="task-meta">${formatBytes(f.size)} ｜ ${escapeHtml(f.modified)}</div>
        </div>
        <a class="btn btn-secondary btn-sm" href="/api/files/download?path=${encodeURIComponent(f.path)}">
          儲存檔案
        </a>
      </div>`
    )
    .join("");
}

// Event Listeners
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => setAuthMode(btn.dataset.authMode));
});

$("cookieFileInput").addEventListener("change", (e) => {
  const file = e.target.files?.[0];
  if (file) uploadCookiesFile(file);
  e.target.value = "";
});

$("togglePasteCookiesBtn").addEventListener("click", () => {
  $("pasteCookiesBox").hidden = !$("pasteCookiesBox").hidden;
});
$("saveCookiesTextBtn").addEventListener("click", saveCookiesText);
$("deleteCookiesBtn").addEventListener("click", deleteCookies);

$("subtitlesCheck").addEventListener("change", (e) => {
  $("subtitleOptions").hidden = !e.target.checked;
});
$("playlistCheck").addEventListener("change", (e) => {
  $("playlistOptions").hidden = !e.target.checked;
});

$("probeBtn").addEventListener("click", probeUrl);
$("downloadBtn").addEventListener("click", startDownload);
$("refreshFilesBtn").addEventListener("click", loadFiles);

// Init
loadStatus();
loadTasks();
loadFiles();
