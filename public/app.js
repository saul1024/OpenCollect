const form = document.querySelector("#collectForm");
const input = document.querySelector("#collectInput");
const sampleButton = document.querySelector("#sampleButton");
const clearAllButton = document.querySelector("#clearAllButton");
const list = document.querySelector("#collectionList");
const noteView = document.querySelector("#noteView");
const emptyState = document.querySelector("#emptyState");
const countBadge = document.querySelector("#countBadge");
const toast = document.querySelector("#toast");
const pageShell = document.querySelector(".page-shell");
const editorModal = document.querySelector("#editorModal");
const editForm = document.querySelector("#editForm");
const editTitle = document.querySelector("#editTitle");
const editContent = document.querySelector("#editContent");
const editTags = document.querySelector("#editTags");
const editSourceUrl = document.querySelector("#editSourceUrl");
const clearConfirmModal = document.querySelector("#clearConfirmModal");
const clearConfirmMessage = document.querySelector("#clearConfirmMessage");
const clearConfirmSubmit = document.querySelector("#clearConfirmSubmit");

const STORE_KEY = "opencollect:xhs:poc";
let notes = loadNotes();
let activeId = "";
let editingId = "";
let pendingUndo = null;

render();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = input.value.trim();
  if (!value) return;
  await collect(value);
});

sampleButton.addEventListener("click", async () => {
  setBusy(sampleButton, true, "加载");
  try {
    const response = await fetch("/api/sample");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "示例获取失败");
    input.value = payload.input;
    await collect(payload.input);
  } catch (error) {
    showToast(error.message || "示例获取失败");
  } finally {
    setBusy(sampleButton, false, "多图示例");
  }
});

clearAllButton.addEventListener("click", openClearConfirm);

editForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveEditor();
});

editorModal.addEventListener("click", (event) => {
  if (event.target === editorModal) closeEditor();
});

editorModal.querySelectorAll("[data-editor-close]").forEach((button) => {
  button.addEventListener("click", closeEditor);
});

clearConfirmSubmit.addEventListener("click", clearAllNotes);

clearConfirmModal.addEventListener("click", (event) => {
  if (event.target === clearConfirmModal) closeClearConfirm();
});

clearConfirmModal.querySelectorAll("[data-clear-confirm-close]").forEach((button) => {
  button.addEventListener("click", closeClearConfirm);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !editorModal.classList.contains("hidden")) {
    closeEditor();
    return;
  }

  if (event.key === "Escape" && !clearConfirmModal.classList.contains("hidden")) {
    closeClearConfirm();
  }
});

async function collect(value) {
  const submit = form.querySelector("button[type='submit']");
  setBusy(submit, true, "解析中");

  try {
    const response = await fetch("/api/collect", {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({ input: value })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "解析失败");

    upsertNote(payload.note);
    activeId = "";
    saveNotes();
    render();
    showToast("已收藏");
  } catch (error) {
    showToast(error.message || "解析失败");
  } finally {
    setBusy(submit, false, "收藏");
  }
}

function upsertNote(note) {
  const index = notes.findIndex((item) => item.id === note.id);
  if (index >= 0) {
    notes[index] = note;
  } else {
    notes.unshift(note);
  }
}

function openClearConfirm() {
  if (!notes.length) {
    showToast("暂无收藏");
    return;
  }

  closeEditor();
  clearConfirmMessage.textContent = `将移除当前 ${notes.length} 条收藏，清空后可在提示条中撤销。`;
  clearConfirmModal.classList.remove("hidden");
  updateModalLock();
  clearConfirmSubmit.focus();
}

function closeClearConfirm() {
  clearConfirmModal.classList.add("hidden");
  updateModalLock();
}

function clearAllNotes() {
  if (!notes.length) {
    closeClearConfirm();
    showToast("暂无收藏");
    return;
  }

  const previousNotes = notes.map((note) => cloneValue(note));
  const previousActiveId = activeId;

  notes = [];
  activeId = "";
  closeEditor();
  closeClearConfirm();
  saveNotes();
  render();
  showUndoToast("已清空收藏", () => {
    notes = previousNotes;
    activeId = previousActiveId;
    saveNotes();
    render();
    showToast("已恢复收藏");
  });
}

function deleteNote(id) {
  const index = notes.findIndex((item) => item.id === id);
  const note = notes[index];
  if (!note) return;

  const deletedNote = cloneValue(note);
  const previousActiveId = activeId;

  notes.splice(index, 1);
  if (activeId === id) activeId = "";
  if (editingId === id) closeEditor();
  saveNotes();
  render();
  showUndoToast("已删除收藏", () => {
    if (notes.some((item) => item.id === deletedNote.id)) return;

    const insertIndex = Math.min(index, notes.length);
    notes.splice(insertIndex, 0, deletedNote);
    activeId = previousActiveId === deletedNote.id ? deletedNote.id : activeId;
    saveNotes();
    render();
    showToast("已恢复收藏");
  });
}

function openEditor(id) {
  const note = notes.find((item) => item.id === id);
  if (!note) return;

  editingId = id;
  editTitle.value = note.title || "";
  editContent.value = note.content || "";
  editTags.value = note.tags?.join(" ") || "";
  editSourceUrl.value = note.sourceUrl || "";
  editorModal.classList.remove("hidden");
  updateModalLock();
  editTitle.focus();
}

function closeEditor() {
  editingId = "";
  editForm.reset();
  editorModal.classList.add("hidden");
  updateModalLock();
}

function saveEditor() {
  const index = notes.findIndex((item) => item.id === editingId);
  if (index < 0) {
    closeEditor();
    return;
  }

  const nextTitle = editTitle.value.trim();
  const nextContent = editContent.value.trim();
  const nextSourceUrl = editSourceUrl.value.trim();

  notes[index] = {
    ...notes[index],
    title: nextTitle,
    content: nextContent,
    tags: parseTags(editTags.value),
    sourceUrl: nextSourceUrl || notes[index].sourceUrl,
    updatedAt: new Date().toISOString()
  };

  saveNotes();
  closeEditor();
  render();
  showToast("已保存");
}

function render() {
  countBadge.textContent = String(notes.length);
  clearAllButton.hidden = notes.length === 0;
  pageShell.classList.toggle("detail-open", Boolean(notes.find((item) => item.id === activeId)));
  renderList();
  renderActiveNote();
}

function renderList() {
  if (!notes.length) {
    list.classList.add("empty");
    list.innerHTML = `
      <div class="feed-empty">
        <span class="empty-cover" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </span>
        <strong>暂无收藏</strong>
        <small>粘贴小红书分享链接，或加载一个多图示例</small>
      </div>
    `;
    return;
  }

  list.classList.remove("empty");
  list.innerHTML = notes
    .map((note) => {
      const cover = note.images?.[0]?.url ? imageProxy(note.images[0].url) : "";
      const avatar = note.author?.avatar ? imageProxy(note.author.avatar) : "";
      const authorName = note.author?.name || "未知作者";
      const isActive = note.id === activeId ? " active" : "";
      const isVideo = Boolean(note.video?.url);
      const title = note.title || note.content || "无标题笔记";
      const platform = getPlatformMeta(note);
      return `
        <article class="collection-item${isActive}${isVideo ? " video-card" : ""}" data-id="${escapeAttr(note.id)}">
          <button type="button" class="card-open" data-action="open-note" data-id="${escapeAttr(note.id)}">
            <span class="card-media">
              ${cover ? `<img src="${escapeAttr(cover)}" alt="" loading="lazy" />` : `<span class="thumb-fallback"></span>`}
              <span class="media-badges">
                <span class="platform-badge platform-${escapeAttr(platform.key)}">${escapeHtml(platform.label)}</span>
                ${isVideo ? `<span class="play-badge" aria-label="视频">▶</span>` : ""}
              </span>
            </span>
            <span class="card-content">
              <strong class="card-title">${escapeHtml(title)}</strong>
              <span class="card-meta">
                ${avatar ? `<img src="${escapeAttr(avatar)}" alt="" loading="lazy" />` : `<span class="avatar-mini"></span>`}
                <span class="card-author">${escapeHtml(authorName)}</span>
                <span class="card-like">${escapeHtml(note.stats?.likes || "0")} 赞</span>
              </span>
            </span>
          </button>
          <span class="card-tools" aria-label="收藏操作">
            <button type="button" data-action="edit-note" data-id="${escapeAttr(note.id)}">编辑</button>
            <button type="button" class="danger" data-action="delete-note" data-id="${escapeAttr(note.id)}">删除</button>
          </span>
        </article>
      `;
    })
    .join("");

  list.querySelectorAll('[data-action="open-note"]').forEach((button) => {
    button.addEventListener("click", () => {
      activeId = button.dataset.id;
      render();
      noteView.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  list.querySelectorAll('[data-action="edit-note"]').forEach((button) => {
    button.addEventListener("click", () => openEditor(button.dataset.id));
  });

  list.querySelectorAll('[data-action="delete-note"]').forEach((button) => {
    button.addEventListener("click", () => deleteNote(button.dataset.id));
  });
}

function renderActiveNote() {
  const note = notes.find((item) => item.id === activeId);

  if (!note) {
    noteView.classList.add("hidden");
    emptyState.classList.toggle("hidden", notes.length > 0);
    return;
  }

  emptyState.classList.add("hidden");
  noteView.classList.remove("hidden");

  const media = renderMedia(note);
  const authorName = note.author?.name || "未知作者";
  const authorAvatar = note.author?.avatar ? imageProxy(note.author.avatar) : "";
  const platform = getPlatformMeta(note);

  noteView.innerHTML = `
    <header class="note-header">
      <div class="author">
        ${authorAvatar ? `<img src="${escapeAttr(authorAvatar)}" alt="" />` : `<span class="avatar-fallback"></span>`}
        <div>
          <strong>${escapeHtml(authorName)}</strong>
          <small><span class="detail-platform platform-${escapeAttr(platform.key)}">${escapeHtml(platform.label)}</span>${formatDate(note.createdAt)}</small>
        </div>
      </div>
      <div class="note-actions">
        <a class="source-link" href="${escapeAttr(note.sourceUrl)}" target="_blank" rel="noreferrer">原文</a>
        <button type="button" class="note-tool" data-action="edit-active">编辑</button>
        <button type="button" class="note-tool danger" data-action="delete-active">删除</button>
        <button type="button" class="detail-close" data-action="collapse-detail" aria-label="关闭详情" title="关闭详情">×</button>
      </div>
    </header>

    ${media}

    <div class="note-copy">
      <h2>${escapeHtml(note.title || "无标题笔记")}</h2>
      <p>${formatContent(note.content)}</p>
      ${note.tags?.length ? `<div class="tags">${note.tags.map((tag) => `<span>#${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
    </div>

    <footer class="stats">
      <span><strong>${escapeHtml(note.stats?.likes || "0")}</strong>赞</span>
      <span><strong>${escapeHtml(note.stats?.collects || "0")}</strong>收藏</span>
      <span><strong>${escapeHtml(note.stats?.comments || "0")}</strong>评论</span>
      <span><strong>${escapeHtml(note.stats?.shares || "0")}</strong>分享</span>
    </footer>
  `;

  noteView.querySelector('[data-action="collapse-detail"]')?.addEventListener("click", () => {
    activeId = "";
    render();
    list.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  noteView.querySelector('[data-action="edit-active"]')?.addEventListener("click", () => {
    openEditor(note.id);
  });

  noteView.querySelector('[data-action="delete-active"]')?.addEventListener("click", () => {
    deleteNote(note.id);
  });

  setupCarousel();
}

function renderMedia(note) {
  if (note.video?.url) {
    const poster = note.video.poster || note.images?.[0]?.url || "";
    return `
      <div class="video-viewer">
        <video
          controls
          playsinline
          preload="metadata"
          ${poster ? `poster="${escapeAttr(imageProxy(poster))}"` : ""}
          src="${escapeAttr(mediaProxy(note.video.url))}"
        ></video>
      </div>
    `;
  }

  if (note.type === "video") {
    return `
      <div class="media-empty">
        <span>这个视频收藏缺少播放地址，请重新收藏原链接</span>
      </div>
    `;
  }

  if (!note.images?.length) {
    return `<div class="media-empty">无图片内容</div>`;
  }

  return `
    <div class="media-viewer ${note.images.length === 1 ? "single" : ""}" ${note.images.length > 1 ? 'tabindex="0"' : ""}>
      <div class="media-track">
        ${note.images
          .map(
            (image, index) => `
              <figure>
                <img src="${escapeAttr(imageProxy(image.url))}" alt="${escapeAttr(note.title)} 图片 ${index + 1}" loading="lazy" />
                ${note.images.length > 1 ? `<span class="slide-count">${index + 1} / ${note.images.length}</span>` : ""}
              </figure>
            `
          )
          .join("")}
      </div>
      ${
        note.images.length > 1
          ? `
            <button type="button" class="carousel-control prev" data-carousel="prev" aria-label="上一张">‹</button>
            <button type="button" class="carousel-control next" data-carousel="next" aria-label="下一张">›</button>
            <div class="carousel-dots" aria-label="图片分页">
              ${note.images.map((_, index) => `<button type="button" data-slide="${index}" aria-label="第 ${index + 1} 张"></button>`).join("")}
            </div>
          `
          : ""
      }
    </div>
  `;
}

function setupCarousel() {
  const viewer = noteView.querySelector(".media-viewer");
  if (!viewer) return;

  const track = viewer.querySelector(".media-track");
  const figures = Array.from(viewer.querySelectorAll("figure"));
  const dots = Array.from(viewer.querySelectorAll(".carousel-dots button"));
  if (figures.length <= 1) return;

  let activeIndex = 0;

  const setActive = (index) => {
    activeIndex = (index + figures.length) % figures.length;
    track.style.transform = `translateX(${-activeIndex * 100}%)`;
    updateDots();
  };

  const updateDots = () => {
    dots.forEach((dot, index) => {
      dot.classList.toggle("active", index === activeIndex);
      dot.setAttribute("aria-current", index === activeIndex ? "true" : "false");
    });
  };

  viewer.querySelector('[data-carousel="prev"]')?.addEventListener("click", () => setActive(activeIndex - 1));
  viewer.querySelector('[data-carousel="next"]')?.addEventListener("click", () => setActive(activeIndex + 1));

  dots.forEach((dot, index) => {
    dot.addEventListener("click", () => setActive(index));
  });

  viewer.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") setActive(activeIndex - 1);
    if (event.key === "ArrowRight") setActive(activeIndex + 1);
  });

  setActive(0);
}

function imageProxy(url) {
  return `/api/image?url=${encodeURIComponent(url)}`;
}

function mediaProxy(url) {
  return `/api/media?url=${encodeURIComponent(url)}`;
}

function loadNotes() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveNotes() {
  localStorage.setItem(STORE_KEY, JSON.stringify(notes));
}

function parseTags(value) {
  return value
    .split(/[\s,，、]+/)
    .map((tag) => tag.trim().replace(/^#/, "").replace(/\[话题\]$/, "").replace(/#$/, ""))
    .filter(Boolean);
}

function getPlatformMeta(note) {
  const key = normalizePlatformKey(note?.platform || inferPlatformFromUrl(note?.sourceUrl));
  const platforms = {
    xiaohongshu: { key: "xiaohongshu", label: "小红书" },
    douyin: { key: "douyin", label: "抖音" },
    bilibili: { key: "bilibili", label: "B站" },
    youtube: { key: "youtube", label: "YouTube" },
    instagram: { key: "instagram", label: "Instagram" },
    tiktok: { key: "tiktok", label: "TikTok" },
    wechat: { key: "wechat", label: "微信" }
  };

  return platforms[key] || { key: "unknown", label: "来源" };
}

function normalizePlatformKey(value) {
  const text = String(value || "").toLowerCase();
  if (["xiaohongshu", "xhs", "red", "小红书"].includes(text)) return "xiaohongshu";
  if (["douyin", "抖音"].includes(text)) return "douyin";
  if (["bilibili", "b站", "哔哩哔哩"].includes(text)) return "bilibili";
  if (["youtube", "yt"].includes(text)) return "youtube";
  if (["instagram", "ig"].includes(text)) return "instagram";
  if (["tiktok"].includes(text)) return "tiktok";
  if (["wechat", "weixin", "微信"].includes(text)) return "wechat";
  return text.replace(/[^a-z0-9-]/g, "") || "xiaohongshu";
}

function inferPlatformFromUrl(value) {
  try {
    const hostname = new URL(value).hostname.toLowerCase();
    if (hostname.includes("xiaohongshu.com") || hostname.includes("xhslink.com")) return "xiaohongshu";
    if (hostname.includes("douyin.com")) return "douyin";
    if (hostname.includes("bilibili.com") || hostname.includes("b23.tv")) return "bilibili";
    if (hostname.includes("youtube.com") || hostname.includes("youtu.be")) return "youtube";
    if (hostname.includes("instagram.com")) return "instagram";
    if (hostname.includes("tiktok.com")) return "tiktok";
    if (hostname.includes("weixin.qq.com") || hostname.includes("mp.weixin.qq.com")) return "wechat";
  } catch {
    return "xiaohongshu";
  }

  return "xiaohongshu";
}

function cloneValue(value) {
  if (typeof structuredClone === "function") {
    return structuredClone(value);
  }

  return JSON.parse(JSON.stringify(value));
}

function updateModalLock() {
  const hasOpenModal = !editorModal.classList.contains("hidden") || !clearConfirmModal.classList.contains("hidden");
  document.body.classList.toggle("modal-open", hasOpenModal);
}

function setBusy(button, busy, label) {
  button.disabled = busy;
  button.textContent = label;
}

function showUndoToast(message, onUndo) {
  pendingUndo = onUndo;
  showToast(message, {
    actionLabel: "撤销",
    duration: 5200,
    onAction: () => {
      const undo = pendingUndo;
      pendingUndo = null;
      if (undo) undo();
    }
  });
}

function showToast(message, options = {}) {
  const { actionLabel = "", onAction = null, duration = 2800 } = options;
  window.clearTimeout(showToast.timer);
  if (!actionLabel) pendingUndo = null;
  toast.replaceChildren();

  const text = document.createElement("span");
  text.className = "toast-message";
  text.textContent = message;
  toast.append(text);

  if (actionLabel && onAction) {
    const action = document.createElement("button");
    action.type = "button";
    action.className = "toast-action";
    action.textContent = actionLabel;
    action.addEventListener("click", () => {
      window.clearTimeout(showToast.timer);
      hideToast();
      onAction();
    });
    toast.append(action);
  }

  toast.classList.remove("hidden");

  if (duration > 0) {
    showToast.timer = window.setTimeout(() => {
      pendingUndo = null;
      hideToast();
    }, duration);
  }
}

function hideToast() {
  toast.classList.add("hidden");
  toast.replaceChildren();
}

function formatDate(value) {
  if (!value) return "未知时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知时间";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(date);
}

function formatContent(value) {
  return escapeHtml(value || "")
    .replace(/\n/g, "<br />")
    .replace(/#([^#<]+?)(?:\[话题\])?#/g, '<span class="topic">#$1</span>');
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}
