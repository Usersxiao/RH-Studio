const state = {
  view: "library",
  tools: [],
  tasks: [],
  settings: {},
  currentTool: null,
  runToolId: null,
  pollTimer: null,
};

const viewEl = document.querySelector("#view");
const titleEl = document.querySelector("#page-title");
const subEl = document.querySelector("#page-sub");
const actionsEl = document.querySelector("#top-actions");
const modalEl = document.querySelector("#modal");

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

function toast(message, err = false) {
  const node = document.createElement("div");
  node.className = `toast${err ? " err" : ""}`;
  node.textContent = message;
  document.querySelector("#toasts").appendChild(node);
  setTimeout(() => node.remove(), 3200);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.message || `请求失败 ${res.status}`);
  }
  return data;
}

function setNav(view) {
  document.querySelectorAll("nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
}

function switchView(view, extra = {}) {
  state.view = view;
  if (extra.toolId) state.runToolId = extra.toolId;
  setNav(view);
  render();
}

function copy(text) {
  navigator.clipboard.writeText(text).then(
    () => toast("已复制"),
    () => toast("复制失败", true)
  );
}

function statusPill(status) {
  return `<span class="pill ${status || "queued"}">${status || "unknown"}</span>`;
}

function filePreview(outputs = []) {
  if (!outputs.length) return `<p class="muted">还没有产物。</p>`;
  return outputs.map((item) => {
    const url = item.fileUrl || item.url || "";
    const type = (item.fileType || item.nodeType || "").toLowerCase();
    if (!url) return `<div class="panel" style="padding:12px">${JSON.stringify(item)}</div>`;
    if (type.includes("video") || url.match(/\.(mp4|webm)(\?|$)/i)) {
      return `<video src="${url}" controls></video>`;
    }
    if (type.includes("audio") || url.match(/\.(mp3|wav|m4a)(\?|$)/i)) {
      return `<audio src="${url}" controls></audio>`;
    }
    return `<a href="${url}" target="_blank" rel="noreferrer"><img src="${url}" alt="output" /></a>`;
  }).join("");
}

async function loadAll() {
  const [tools, tasks, settings] = await Promise.all([
    api("/api/tools"),
    api("/api/tasks"),
    api("/api/settings"),
  ]);
  state.tools = tools.items || [];
  state.tasks = tasks.items || [];
  state.settings = settings;
  if (state.runToolId) {
    state.currentTool = await api(`/api/tools/${state.runToolId}`).catch(() => null);
  }
}

function render() {
  const titles = {
    library: ["工具库", "只填 webappId 或链接，后台从公开页拉 nodeInfoList，不需要 Key。"],
    run: ["运行", "选中一个已导入的应用，按字段类型动态生成表单。"],
    tasks: ["任务", "提交后自动轮询 outputs，直到成功、失败或取消。"],
    settings: ["设置", "导入应用不需要 Key。Key 只用于上传文件和提交任务。"],
  };
  titleEl.textContent = titles[state.view][0];
  subEl.textContent = titles[state.view][1];
  actionsEl.innerHTML = "";
  if (state.view === "library") renderLibrary();
  if (state.view === "run") renderRun();
  if (state.view === "tasks") renderTasks();
  if (state.view === "settings") renderSettings();
}

function renderLibrary() {
  actionsEl.innerHTML = `<button class="ghost" id="demo-btn">导入官方示例</button>`;
  document.querySelector("#demo-btn").onclick = importDemo;
  viewEl.innerHTML = `
    <div class="import-bar">
      <input id="webapp-input" placeholder="粘贴 webappId 或链接，例如 1937084629516193794" />
      <button class="primary" id="import-btn">导入应用</button>
      <button class="ghost" id="demo-btn-2">官方示例</button>
    </div>
    ${state.tools.length ? `<div class="grid">${state.tools.map(toolCard).join("")}</div>` : `
      <div class="empty">
        <h2>还没有工具</h2>
        <p>先导入一个 RunningHub AI 应用。后台会调用 apiCallDemo，把 nodeInfoList 存成可编辑目录。</p>
      </div>`}
  `;
  document.querySelector("#import-btn").onclick = importTool;
  document.querySelector("#demo-btn-2").onclick = importDemo;
  document.querySelector("#webapp-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") importTool();
  });
  viewEl.querySelectorAll("[data-run]").forEach((btn) => {
    btn.onclick = () => switchView("run", { toolId: Number(btn.dataset.run) });
  });
  viewEl.querySelectorAll("[data-edit]").forEach((btn) => {
    btn.onclick = () => openEditor(Number(btn.dataset.edit));
  });
  viewEl.querySelectorAll("[data-refresh]").forEach((btn) => {
    btn.onclick = () => refreshTool(Number(btn.dataset.refresh));
  });
  viewEl.querySelectorAll("[data-del]").forEach((btn) => {
    btn.onclick = () => deleteTool(Number(btn.dataset.del));
  });
}

function toolCard(tool) {
  const cover = tool.cover_url
    ? `style="background-image:url('${tool.cover_url}')"`
    : "";
  return `
    <article class="card">
      <div class="cover" ${cover}><span>${tool.field_count || 0} 个参数</span></div>
      <div class="card-body">
        <h3>${escapeHtml(tool.display_name || tool.name)}</h3>
        <div class="meta">${escapeHtml(tool.category || "未分类")} · ${escapeHtml(tool.webapp_id)}</div>
        ${tool.warning ? `<div class="help">${escapeHtml(tool.warning)}</div>` : ""}
        <div class="card-actions">
          <button class="primary" data-run="${tool.id}">运行</button>
          <button class="ghost" data-edit="${tool.id}">字段</button>
        </div>
        <div class="card-actions">
          <button class="ghost" data-refresh="${tool.id}">刷新 schema</button>
          <button class="danger" data-del="${tool.id}">删除</button>
        </div>
      </div>
    </article>
  `;
}

async function importTool() {
  const value = document.querySelector("#webapp-input").value.trim();
  if (!value) return toast("请输入 webappId 或链接", true);
  try {
    const tool = await api("/api/tools/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ webappId: value }),
    });
    toast(`已导入 ${tool.display_name}`);
    await loadAll();
    render();
  } catch (err) {
    toast(err.message, true);
  }
}

async function importDemo() {
  try {
    const tool = await api("/api/tools/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ demo: true }),
    });
    toast(`已导入示例 ${tool.display_name}`);
    await loadAll();
    render();
  } catch (err) {
    toast(err.message, true);
  }
}

async function refreshTool(id) {
  try {
    await api(`/api/tools/${id}/refresh`, { method: "POST" });
    toast("已刷新 schema");
    await loadAll();
    render();
  } catch (err) {
    toast(err.message, true);
  }
}

async function deleteTool(id) {
  if (!confirm("删除这个工具？历史任务会保留。")) return;
  try {
    await api(`/api/tools/${id}`, { method: "DELETE" });
    if (state.runToolId === id) state.runToolId = null;
    await loadAll();
    render();
  } catch (err) {
    toast(err.message, true);
  }
}

async function openEditor(id) {
  const tool = await api(`/api/tools/${id}`);
  modalEl.hidden = false;
  modalEl.innerHTML = `
    <div class="modal-card">
      <h2>编辑 ${escapeHtml(tool.display_name)}</h2>
      <p class="muted">刷新 schema 时会保留别名、隐藏和必填设置。</p>
      <label>显示名称</label>
      <input id="edit-name" value="${escapeAttr(tool.display_name || "")}" />
      <label>分类</label>
      <input id="edit-cat" value="${escapeAttr(tool.category || "")}" />
      <label>备注</label>
      <textarea id="edit-desc">${escapeHtml(tool.description || "")}</textarea>
      <div style="height:12px"></div>
      ${(tool.fields || []).map((field) => `
        <div class="field-edit">
          <div>
            <strong>${escapeHtml(field.display_label)}</strong>
            <div class="meta">${field.node_id} / ${field.field_name} · ${field.field_type}</div>
            <input data-label="${field.id}" value="${escapeAttr(field.display_label)}" />
          </div>
          <label><input type="checkbox" data-hidden="${field.id}" ${field.hidden ? "checked" : ""} /> 隐藏</label>
          <label><input type="checkbox" data-required="${field.id}" ${field.required ? "checked" : ""} /> 必填</label>
        </div>
      `).join("")}
      <div class="row" style="margin-top:16px">
        <button class="primary" id="save-tool">保存</button>
        <button class="ghost" id="close-modal">关闭</button>
      </div>
    </div>
  `;
  modalEl.querySelector("#close-modal").onclick = closeModal;
  modalEl.querySelector("#save-tool").onclick = async () => {
    const fields = (tool.fields || []).map((field) => ({
      id: field.id,
      display_label: modalEl.querySelector(`[data-label="${field.id}"]`).value,
      hidden: modalEl.querySelector(`[data-hidden="${field.id}"]`).checked,
      required: modalEl.querySelector(`[data-required="${field.id}"]`).checked,
    }));
    try {
      await api(`/api/tools/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: modalEl.querySelector("#edit-name").value,
          category: modalEl.querySelector("#edit-cat").value,
          description: modalEl.querySelector("#edit-desc").value,
          fields,
        }),
      });
      toast("已保存字段配置");
      closeModal();
      await loadAll();
      render();
    } catch (err) {
      toast(err.message, true);
    }
  };
}

function closeModal() {
  modalEl.hidden = true;
  modalEl.innerHTML = "";
}

function renderRun() {
  const tools = state.tools;
  if (!tools.length) {
    viewEl.innerHTML = `<div class="empty"><h2>先去工具库导入一个应用</h2></div>`;
    return;
  }
  if (!state.runToolId) state.runToolId = tools[0].id;
  const selected = state.currentTool && state.currentTool.id === state.runToolId
    ? state.currentTool
    : tools.find((item) => item.id === state.runToolId);
  viewEl.innerHTML = `
    <div class="split">
      <div class="tool-list">
        ${tools.map((tool) => `
          <button data-pick="${tool.id}" class="${tool.id === state.runToolId ? "active" : ""}">
            <strong>${escapeHtml(tool.display_name)}</strong>
            <div class="meta">${escapeHtml(tool.webapp_id)}</div>
          </button>
        `).join("")}
      </div>
      <div class="panel" style="padding:20px" id="run-form-wrap">加载表单...</div>
    </div>
  `;
  viewEl.querySelectorAll("[data-pick]").forEach((btn) => {
    btn.onclick = async () => {
      state.runToolId = Number(btn.dataset.pick);
      state.currentTool = await api(`/api/tools/${state.runToolId}`);
      render();
    };
  });
  fillRunForm(selected);
}

async function fillRunForm(selected) {
  const wrap = document.querySelector("#run-form-wrap");
  if (!selected) return;
  const tool = selected.fields ? selected : await api(`/api/tools/${selected.id}`);
  state.currentTool = tool;
  const fields = (tool.fields || []).filter((field) => !field.hidden);
  wrap.innerHTML = `
    <h2>${escapeHtml(tool.display_name)}</h2>
    <p class="muted">${escapeHtml(tool.warning || tool.description || "提交时只发送 nodeId / fieldName / fieldValue")}</p>
    <form id="run-form" class="form-grid">
      ${fields.map(renderField).join("")}
      <label>实例类型</label>
      <select name="instance_type">
        <option value="default">default</option>
        <option value="plus">plus</option>
      </select>
      <button class="primary" type="submit">提交运行</button>
    </form>
    <div class="outputs" id="live-outputs"></div>
  `;
  wrap.querySelectorAll("input[type=file]").forEach((input) => {
    input.addEventListener("change", async () => {
      if (!input.files[0]) return;
      const body = new FormData();
      body.append("file", input.files[0]);
      input.disabled = true;
      try {
        const uploaded = await api("/api/upload", { method: "POST", body });
        input.dataset.fileName = uploaded.fileName;
        toast(`已上传 ${uploaded.original_name}`);
      } catch (err) {
        toast(err.message, true);
      } finally {
        input.disabled = false;
      }
    });
  });
  wrap.querySelector("#run-form").onsubmit = submitRun;
}

function renderField(field) {
  const label = escapeHtml(field.display_label || field.field_name);
  const help = escapeHtml(field.description || `${field.node_id} · ${field.field_name}`);
  const key = field.key;
  if (field.widget === "select") {
    const options = field.options.map((opt) => {
      const selected = String(opt.value) === String(field.field_value) ? "selected" : "";
      return `<option value="${escapeAttr(opt.value)}" ${selected}>${escapeHtml(opt.label)}</option>`;
    }).join("");
    return `<div class="field"><label>${label}</label><select name="${key}">${options}</select><div class="help">${help}</div></div>`;
  }
  if (field.widget === "number") {
    return `<div class="field"><label>${label}</label><input type="number" name="${key}" value="${escapeAttr(field.field_value || "")}" /><div class="help">${help}</div></div>`;
  }
  if (field.widget === "checkbox") {
    const checked = ["true", "1", "yes"].includes(String(field.field_value).toLowerCase()) ? "checked" : "";
    return `<div class="field"><label><input type="checkbox" name="${key}" ${checked} /> ${label}</label><div class="help">${help}</div></div>`;
  }
  if (field.widget === "file") {
    return `<div class="field"><label>${label}${field.required ? " *" : ""}</label>
      <input type="file" name="${key}" accept="${escapeAttr(field.accept || "")}" />
      <div class="help">${help}。先上传拿到 fileName，再写入 fieldValue。</div></div>`;
  }
  return `<div class="field"><label>${label}</label><textarea name="${key}">${escapeHtml(field.field_value || "")}</textarea><div class="help">${help}</div></div>`;
}

async function submitRun(event) {
  event.preventDefault();
  const tool = state.currentTool;
  const form = event.target;
  const values = {};
  for (const field of tool.fields || []) {
    if (field.hidden) continue;
    const el = form.elements[field.key];
    if (!el) continue;
    if (field.widget === "file") {
      values[field.key] = el.dataset.fileName || "";
    } else if (field.widget === "checkbox") {
      values[field.key] = el.checked ? "true" : "false";
    } else {
      values[field.key] = el.value;
    }
  }
  try {
    const task = await api("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_id: tool.id,
        values,
        instance_type: form.instance_type.value,
      }),
    });
    toast("任务已提交");
    watchTask(task.id);
    await loadAll();
  } catch (err) {
    toast(err.message, true);
  }
}

async function watchTask(taskId) {
  const box = document.querySelector("#live-outputs");
  if (!box) return;
  const tick = async () => {
    try {
      const task = await api(`/api/tasks/${taskId}`);
      box.innerHTML = `
        <div class="row">${statusPill(task.status)} <span class="muted">RH task ${task.rh_task_id || "-"}</span></div>
        ${task.error_message ? `<p class="help">${escapeHtml(task.error_message)}</p>` : ""}
        <div class="outputs">${filePreview(task.outputs || [])}</div>
      `;
      if (["success", "failed", "cancelled"].includes(task.status)) {
        clearInterval(state.pollTimer);
        await loadAll();
      }
    } catch (err) {
      box.innerHTML = `<p class="help">${escapeHtml(err.message)}</p>`;
    }
  };
  clearInterval(state.pollTimer);
  await tick();
  state.pollTimer = setInterval(tick, 2000);
}

function renderTasks() {
  if (!state.tasks.length) {
    viewEl.innerHTML = `<div class="empty"><h2>还没有任务</h2></div>`;
    return;
  }
  viewEl.innerHTML = `
    <table class="table">
      <thead><tr><th>ID</th><th>应用</th><th>状态</th><th>产物</th><th></th></tr></thead>
      <tbody>
        ${state.tasks.map((task) => `
          <tr>
            <td>${task.id}<div class="meta">${escapeHtml(task.rh_task_id || "")}</div></td>
            <td>${escapeHtml(task.display_name || task.tool_name || task.webapp_id)}</td>
            <td>${statusPill(task.status)}${task.error_message ? `<div class="help">${escapeHtml(task.error_message)}</div>` : ""}</td>
            <td><div class="outputs">${filePreview(task.outputs || [])}</div></td>
            <td>
              ${["queued", "running", "submitting"].includes(task.status) ? `<button class="ghost" data-cancel="${task.id}">取消</button>` : ""}
            </td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  viewEl.querySelectorAll("[data-cancel]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/tasks/${btn.dataset.cancel}/cancel`, { method: "POST" });
        toast("已请求取消");
        await loadAll();
        render();
      } catch (err) {
        toast(err.message, true);
      }
    };
  });
}

function renderSettings() {
  const key = state.settings.api_key || "";
  viewEl.innerHTML = `
    <div class="panel" style="padding:24px; max-width:640px">
      <label>RunningHub API Key</label>
      <input id="api-key" type="password" value="${escapeAttr(key)}" placeholder="在 runninghub.cn 控制台复制" />
      <p class="help">导入应用不要 Key。这里的 Key 只给上传文件和提交 RunningHub 任务用。</p>
      <div class="row" style="margin-top:16px">
        <button class="primary" id="save-key">保存</button>
        <button class="ghost" id="copy-sample">复制官方示例 ID</button>
      </div>
      <p class="muted" style="margin-top:18px">示例应用：${state.settings.sample_webapp_id || ""}</p>
    </div>
  `;
  document.querySelector("#save-key").onclick = async () => {
    try {
      const result = await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: document.querySelector("#api-key").value }),
      });
      toast(result.message || "已保存");
      await loadAll();
    } catch (err) {
      toast(err.message, true);
    }
  };
  document.querySelector("#copy-sample").onclick = () => copy(state.settings.sample_webapp_id || "");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value);
}

(async function boot() {
  try {
    await loadAll();
    render();
  } catch (err) {
    viewEl.innerHTML = `<div class="empty"><h2>后台没有启动成功</h2><p>${escapeHtml(err.message)}</p></div>`;
  }
})();
