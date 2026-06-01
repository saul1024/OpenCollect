const form = document.querySelector("#collectForm");
const input = document.querySelector("#collectInput");
const sampleButton = document.querySelector("#sampleButton");
const videoSampleButton = document.querySelector("#videoSampleButton");
const clearAllButton = document.querySelector("#clearAllButton");
const syncPanel = document.querySelector("#syncPanel");
const syncStatus = document.querySelector("#syncStatus");
const syncPushButton = document.querySelector("#syncPushButton");
const syncPullButton = document.querySelector("#syncPullButton");
const syncForcePushButton = document.querySelector("#syncForcePushButton");
const list = document.querySelector("#collectionList");
const noteModal = document.querySelector("#noteModal");
const noteView = document.querySelector("#noteView");
const countBadge = document.querySelector("#countBadge");
const toast = document.querySelector("#toast");
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
const MIGRATION_KEY = "opencollect:xhs:poc:migrated:v1";
const XHS_IMAGE_STYLE_SUFFIX = "!nd_dft_wlteh_webp_3";
const XHS_VIDEO_PLAYBACK_HOSTS = ["sns-video-bd.xhscdn.com", "sns-video-hw.xhscdn.com"];
let notes = [];
let activeId = "";
let editingId = "";
let pendingUndo = null;
let renderedColumnCount = 0;
let resizeTimer = 0;
let syncState = null;
let isSyncing = false;
let currentRevision = 0;
const refreshingIds = new Set();
const tabId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
const syncChannel = "BroadcastChannel" in window ? new BroadcastChannel("opencollect-sync") : null;

render();
initialize();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = input.value.trim();
  if (!value) return;
  await collect(value);
});

sampleButton.addEventListener("click", () => {
  loadSample(sampleButton, "/api/sample", "多图示例", "示例获取失败");
});

videoSampleButton.addEventListener("click", () => {
  loadSample(videoSampleButton, "/api/sample-video", "视频示例", "视频示例获取失败");
});

clearAllButton.addEventListener("click", openClearConfirm);
syncPushButton.addEventListener("click", saveAndUpload);
syncPullButton?.addEventListener("click", pullCloudVersion);
syncForcePushButton?.addEventListener("click", () => saveAndUpload({ force: true }));

if (syncChannel) {
  syncChannel.addEventListener("message", (event) => {
    if (!event.data || event.data.source === tabId) return;
    if (!["collections-updated", "sync-state-updated", "sync-updated"].includes(event.data.type)) return;
    reloadFromBackend();
  });
}

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

noteModal.addEventListener("click", (event) => {
  if (event.target === noteModal) closeDetail();
});

document.addEventListener("error", handleImageError, true);
document.addEventListener("error", handleVideoError, true);

window.addEventListener("resize", () => {
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    if (!notes.length) return;
    const nextColumnCount = getMasonryColumnCount();
    if (nextColumnCount !== renderedColumnCount) renderList();
  }, 120);
});

window.addEventListener("beforeunload", (event) => {
  if (!hasDirtySync()) return;
  event.preventDefault();
  event.returnValue = "";
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !editorModal.classList.contains("hidden")) {
    closeEditor();
    return;
  }

  if (event.key === "Escape" && !clearConfirmModal.classList.contains("hidden")) {
    closeClearConfirm();
    return;
  }

  if (event.key === "Escape" && !noteModal.classList.contains("hidden")) {
    closeDetail();
  }
});

async function initialize() {
  try {
    await loadRemoteNotes();
    await refreshSyncState();
    await migrateLocalNotes();
  } catch (error) {
    const localNotes = loadLocalNotes();
    if (localNotes.length) {
      notes = localNotes;
      showToast("后端数据加载失败，已显示本地缓存");
    } else {
      showToast(error.message || "收藏加载失败");
    }
  } finally {
    render();
  }
}

async function loadSample(button, endpoint, idleLabel, fallbackMessage) {
  setBusy(button, true, "加载");
  try {
    const response = await fetch(endpoint);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || fallbackMessage);
    input.value = payload.input;
    await collect(payload.input);
  } catch (error) {
    showToast(error.message || fallbackMessage);
  } finally {
    setBusy(button, false, idleLabel);
  }
}

async function collect(value) {
  const submit = form.querySelector("button[type='submit']");
  setBusy(submit, true, "解析中");

  try {
    const payload = await requestJson("/api/collect", {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({ input: value, baseRevision: currentRevision })
    });
    updateRevisionFromPayload(payload);

    upsertNote(payload.note);
    if (payload.duplicated) {
      activeId = payload.existingId || payload.note?.id || "";
      await refreshSyncState();
      render();
      focusCollectionCard(activeId);
      showToast("已收藏过，已定位到原收藏");
      return;
    }

    activeId = "";
    await refreshSyncState();
    render();
    broadcastUpdate("collections-updated");
    showToast("已收藏");
  } catch (error) {
    if (await handleConflict(error)) return;
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

async function clearAllNotes() {
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
  try {
    const payload = await requestJson(`/api/collections?baseRevision=${encodeURIComponent(currentRevision)}`, { method: "DELETE" });
    notes = payload.collections || [];
    updateRevisionFromPayload(payload);
    await refreshSyncState();
    render();
    broadcastUpdate("collections-updated");
    showUndoToast("已清空收藏", async () => {
      await importCollections(previousNotes);
      activeId = previousActiveId;
      render();
      showToast("已恢复收藏");
    });
  } catch (error) {
    notes = previousNotes;
    activeId = previousActiveId;
    render();
    if (await handleConflict(error)) return;
    showToast(error.message || "清空失败");
  }
}

async function deleteNote(id) {
  const index = notes.findIndex((item) => item.id === id);
  const note = notes[index];
  if (!note) return;

  const deletedNote = cloneValue(note);
  const previousActiveId = activeId;

  notes.splice(index, 1);
  if (activeId === id) activeId = "";
  if (editingId === id) closeEditor();
  try {
    const payload = await requestJson(`/api/collections/${encodeURIComponent(id)}?baseRevision=${encodeURIComponent(currentRevision)}`, { method: "DELETE" });
    notes = payload.collections || notes;
    updateRevisionFromPayload(payload);
    await refreshSyncState();
    render();
    broadcastUpdate("collections-updated");
    showUndoToast("已删除收藏", async () => {
      await importCollections([deletedNote]);
      activeId = previousActiveId === deletedNote.id ? deletedNote.id : activeId;
      render();
      showToast("已恢复收藏");
    });
  } catch (error) {
    notes.splice(Math.min(index, notes.length), 0, deletedNote);
    activeId = previousActiveId;
    render();
    if (await handleConflict(error)) return;
    showToast(error.message || "删除失败");
  }
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

async function saveEditor() {
  const index = notes.findIndex((item) => item.id === editingId);
  if (index < 0) {
    closeEditor();
    return;
  }

  const nextTitle = editTitle.value.trim();
  const nextContent = editContent.value.trim();
  const nextSourceUrl = editSourceUrl.value.trim();

  try {
    const payload = await requestJson(`/api/collections/${encodeURIComponent(editingId)}`, {
      method: "PATCH",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({
        title: nextTitle,
        content: nextContent,
        tags: parseTags(editTags.value),
        sourceUrl: nextSourceUrl || notes[index].sourceUrl,
        baseRevision: currentRevision
      })
    });
    notes[index] = payload.collection;
    updateRevisionFromPayload(payload);
    closeEditor();
    await refreshSyncState();
    render();
    broadcastUpdate("collections-updated");
    showToast("已保存");
  } catch (error) {
    if (await handleConflict(error, { keepEditor: true })) return;
    showToast(error.message || "保存失败");
  }
}

function render() {
  countBadge.textContent = String(notes.length);
  clearAllButton.hidden = notes.length === 0;
  renderSyncState();
  renderList();
  renderActiveNote();
}

function renderList() {
  if (!notes.length) {
    list.classList.add("empty");
    list.style.removeProperty("--masonry-columns");
    list.innerHTML = `
      <div class="feed-empty">
        <span class="empty-cover" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </span>
        <strong>暂无收藏</strong>
        <small>粘贴rednote分享链接，或加载一个多图示例</small>
      </div>
    `;
    return;
  }

  list.classList.remove("empty");
  renderedColumnCount = getMasonryColumnCount();
  list.style.setProperty("--masonry-columns", String(renderedColumnCount));
  const columns = Array.from({ length: renderedColumnCount }, () => []);

  notes.forEach((note, index) => {
    columns[index % renderedColumnCount].push(renderCollectionCard(note, index));
  });

  list.innerHTML = columns
    .map((items, index) => `<div class="masonry-column" data-column="${index + 1}">${items.join("")}</div>`)
    .join("");

  list.querySelectorAll('[data-action="open-note"]').forEach((button) => {
    button.addEventListener("click", () => {
      activeId = button.dataset.id;
      render();
      noteView.focus({ preventScroll: true });
    });
  });

  list.querySelectorAll('[data-action="edit-note"]').forEach((button) => {
    button.addEventListener("click", () => openEditor(button.dataset.id));
  });

  list.querySelectorAll('[data-action="delete-note"]').forEach((button) => {
    button.addEventListener("click", () => deleteNote(button.dataset.id));
  });

  list.querySelectorAll('[data-action="refresh-note"]').forEach((button) => {
    button.addEventListener("click", () => refreshNote(button.dataset.id));
  });
}

function renderCollectionCard(note, index) {
  const coverUrls = getImageProxyUrls(note.images);
  const cover = coverUrls[0] || "";
  const avatar = note.author?.avatar ? imageProxy(note.author.avatar) : "";
  const authorName = note.author?.name || "未知作者";
  const isActive = note.id === activeId ? " active" : "";
  const isVideo = Boolean(note.video?.url);
  const title = note.title || note.content || "无标题笔记";
  const platform = getPlatformMeta(note);
  const ratioClass = getCardRatioClass(index);

  return `
    <article class="collection-item${isActive}${isVideo ? " video-card" : ""}${ratioClass ? ` ${ratioClass}` : ""}" data-id="${escapeAttr(note.id)}">
      <button type="button" class="card-open" data-action="open-note" data-id="${escapeAttr(note.id)}">
        <span class="card-media">
          ${cover ? `<img src="${escapeAttr(cover)}" alt="" loading="lazy"${renderImageFallbackAttrs(coverUrls.slice(1))} />` : `<span class="thumb-fallback"></span>`}
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
        <button type="button" data-action="refresh-note" data-id="${escapeAttr(note.id)}" ${refreshingIds.has(note.id) ? "disabled" : ""}>${refreshingIds.has(note.id) ? "刷新中" : "刷新"}</button>
        <button type="button" data-action="edit-note" data-id="${escapeAttr(note.id)}">编辑</button>
        <button type="button" class="danger" data-action="delete-note" data-id="${escapeAttr(note.id)}">删除</button>
      </span>
    </article>
  `;
}

function getMasonryColumnCount() {
  const width = list.getBoundingClientRect().width || document.documentElement.clientWidth || window.innerWidth;
  const minCardWidth = width <= 560 ? 158 : width <= 920 ? 180 : 230;
  const gap = width <= 560 ? 12 : 18;
  const count = Math.floor((width + gap) / (minCardWidth + gap));
  return Math.max(1, Math.min(7, count || 1));
}

function getCardRatioClass(index) {
  if (index % 4 === 1) return "ratio-medium";
  if (index % 4 === 2) return "ratio-square";
  return "";
}

function renderActiveNote() {
  const note = notes.find((item) => item.id === activeId);

  if (!note) {
    noteModal.classList.add("hidden");
    noteView.replaceChildren();
    updateModalLock();
    return;
  }

  noteModal.classList.remove("hidden");
  updateModalLock();

  const media = renderMedia(note);
  const authorName = note.author?.name || "未知作者";
  const authorAvatar = note.author?.avatar ? imageProxy(note.author.avatar) : "";
  const platform = getPlatformMeta(note);
  const isRefreshing = refreshingIds.has(note.id);

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
        <button type="button" class="note-tool" data-action="refresh-active" ${isRefreshing ? "disabled" : ""}>${isRefreshing ? "刷新中" : "重新抓取"}</button>
        <button type="button" class="note-tool" data-action="edit-active">编辑</button>
        <button type="button" class="note-tool danger" data-action="delete-active">删除</button>
        <button type="button" class="detail-close" data-action="collapse-detail" aria-label="关闭详情" title="关闭详情">×</button>
      </div>
    </header>

    ${media}

    <div class="note-copy">
      <h2 id="noteDetailTitle">${escapeHtml(note.title || "无标题笔记")}</h2>
      <p>${formatContent(note.content)}</p>
      ${renderFetchNotice(note)}
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
    closeDetail();
  });

  noteView.querySelector('[data-action="edit-active"]')?.addEventListener("click", () => {
    openEditor(note.id);
  });

  noteView.querySelector('[data-action="refresh-active"]')?.addEventListener("click", () => {
    refreshNote(note.id);
  });

  noteView.querySelector('[data-action="delete-active"]')?.addEventListener("click", () => {
    deleteNote(note.id);
  });

  setupCarousel();
  setupVideoPlayers();
}

function closeDetail() {
  activeId = "";
  noteModal.classList.add("hidden");
  noteView.replaceChildren();
  renderList();
  updateModalLock();
}

function renderMedia(note) {
  if (note.video?.url) {
    const poster = note.video.poster || note.images?.[0]?.url || "";
    const posterUrls = getImageProxyCandidates(poster);
    const videoUrls = getVideoProxyCandidates(note.video);
    return `
      <div class="video-viewer" data-video-player>
        <video
          playsinline
          preload="metadata"
          ${posterUrls.length ? `poster="${escapeAttr(posterUrls[0])}"` : ""}
          src="${escapeAttr(videoUrls[0] || mediaProxy(note.video.url))}"
          ${renderFallbackAttrs(videoUrls.slice(1))}
        ></video>
        <div class="video-controls" aria-label="视频控制">
          <button type="button" class="video-toggle" data-video-toggle aria-label="播放">▶</button>
          <input class="video-progress" data-video-progress type="range" min="0" max="1000" step="1" value="0" aria-label="视频进度" />
          <span class="video-time" data-video-time>0:00 / 0:00</span>
        </div>
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

  const imageUrlSets = getImageProxyUrlSets(note.images);

  return `
    <div class="media-viewer ${note.images.length === 1 ? "single" : ""}" ${note.images.length > 1 ? 'tabindex="0"' : ""}>
      <div class="media-track">
        ${note.images
          .map((image, index) => {
            const currentUrls = imageUrlSets[index] || [];
            const fallbackUrls = [
              ...currentUrls.slice(1),
              ...imageUrlSets.flatMap((urls, imageIndex) => (imageIndex === index ? [] : urls))
            ];
            return `
              <figure>
                <img
                  src="${escapeAttr(currentUrls[0] || imageProxy(image.url))}"
                  alt="${escapeAttr(note.title)} 图片 ${index + 1}"
                  loading="lazy"
                  ${renderImageFallbackAttrs(fallbackUrls)}
                />
                ${note.images.length > 1 ? `<span class="slide-count">${index + 1} / ${note.images.length}</span>` : ""}
              </figure>
            `;
          })
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

function renderFetchNotice(note) {
  const state = note.fetch || {};
  if (state.lastStatus !== "failed") return "";
  const message = state.lastErrorMessage || parseFailureMessage(state.lastErrorReason) || "最近一次抓取失败";
  return `<div class="fetch-notice">最近抓取失败：${escapeHtml(message)}</div>`;
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

function setupVideoPlayers() {
  noteView.querySelectorAll("[data-video-player]").forEach((player) => {
    const video = player.querySelector("video");
    const toggle = player.querySelector("[data-video-toggle]");
    const progress = player.querySelector("[data-video-progress]");
    const time = player.querySelector("[data-video-time]");
    if (!(video instanceof HTMLVideoElement) || !toggle || !(progress instanceof HTMLInputElement) || !time) return;

    let isSeeking = false;

    const update = () => {
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      const current = Number.isFinite(video.currentTime) ? video.currentTime : 0;
      if (!isSeeking) {
        progress.value = duration > 0 ? String(Math.round((current / duration) * Number(progress.max))) : "0";
      }
      time.textContent = `${formatVideoTime(current)} / ${formatVideoTime(duration)}`;
      toggle.textContent = video.paused ? "▶" : "Ⅱ";
      toggle.setAttribute("aria-label", video.paused ? "播放" : "暂停");
    };

    const seek = () => {
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      if (duration <= 0) return;
      video.currentTime = (Number(progress.value) / Number(progress.max)) * duration;
    };

    toggle.addEventListener("click", () => toggleVideoPlayback(video));
    video.addEventListener("click", () => toggleVideoPlayback(video));
    video.addEventListener("loadedmetadata", update);
    video.addEventListener("durationchange", update);
    video.addEventListener("timeupdate", update);
    video.addEventListener("play", update);
    video.addEventListener("pause", update);
    video.addEventListener("ended", update);
    progress.addEventListener("input", () => {
      isSeeking = true;
      seek();
      update();
    });
    progress.addEventListener("change", () => {
      seek();
      isSeeking = false;
      update();
    });
    progress.addEventListener("pointerup", () => {
      isSeeking = false;
      update();
    });

    update();
  });
}

function toggleVideoPlayback(video) {
  if (video.paused) {
    video.play().catch(() => {});
  } else {
    video.pause();
  }
}

function formatVideoTime(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0:00";
  const wholeSeconds = Math.floor(seconds);
  const minutes = Math.floor(wholeSeconds / 60);
  const remainingSeconds = String(wholeSeconds % 60).padStart(2, "0");
  return `${minutes}:${remainingSeconds}`;
}

function imageProxy(url) {
  return `/api/image?url=${encodeURIComponent(normalizeXhsImageUrl(url))}`;
}

function mediaProxy(url) {
  return `/api/media?url=${encodeURIComponent(url)}`;
}

function getVideoProxyCandidates(video) {
  if (!video) return [];
  const rawUrls = [];
  if (video.url) rawUrls.push(video.url);
  (video.streams || []).forEach((stream) => {
    if (stream?.url) rawUrls.push(stream.url);
    (stream?.backupUrls || []).forEach((url) => rawUrls.push(url));
  });
  return uniqueValues(rawUrls.flatMap((url) => getXhsVideoUrlCandidates(url))).map((candidate) => mediaProxy(candidate));
}

function getImageProxyUrls(images) {
  return getImageProxyUrlSets(images).flat();
}

function getImageProxyUrlSets(images) {
  return (images || []).map((image) => getImageProxyCandidates(image?.url));
}

function getImageProxyCandidates(url) {
  if (!url) return [];

  const candidates = [normalizeXhsImageUrl(url)];
  const spectrumUrl = getXhsSpectrumImageUrl(candidates[0]);
  if (spectrumUrl && spectrumUrl !== candidates[0]) candidates.push(spectrumUrl);

  return uniqueValues(candidates).map((candidate) => imageProxy(candidate));
}

function normalizeXhsImageUrl(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    if (!host.endsWith(".xhscdn.com")) return url;

    const resourceId = getXhsImageResourceId(parsed.pathname);
    if (!resourceId) return url;
    const pathPrefix = hasXhsSpectrumPath(parsed.pathname) ? "spectrum/" : "";

    if (host.startsWith("sns-webpic-")) {
      return `https://${host.replace("sns-webpic-", "sns-img-")}/${pathPrefix}${resourceId}${XHS_IMAGE_STYLE_SUFFIX}`;
    }

    if (host.startsWith("sns-img-") && !parsed.pathname.includes("!")) {
      return `https://${host}/${pathPrefix}${resourceId}${XHS_IMAGE_STYLE_SUFFIX}`;
    }
  } catch {
    return url;
  }

  return url;
}

function getXhsSpectrumImageUrl(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    if (!host.startsWith("sns-img-") || !host.endsWith(".xhscdn.com")) return "";
    if (hasXhsSpectrumPath(parsed.pathname)) return "";

    const resourceId = getXhsImageResourceId(parsed.pathname);
    if (!resourceId) return "";
    return `https://${host}/spectrum/${resourceId}${XHS_IMAGE_STYLE_SUFFIX}`;
  } catch {
    return "";
  }
}

function hasXhsSpectrumPath(pathname) {
  return pathname.split("/").includes("spectrum");
}

function getXhsImageResourceId(pathname) {
  return pathname.split("/").filter(Boolean).pop()?.split("!")[0] || "";
}

function uniqueValues(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

function getXhsVideoUrlCandidates(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    if (!isXhsVideoHost(host) || !parsed.pathname.includes("/stream/") || !parsed.pathname.toLowerCase().endsWith(".mp4")) {
      return [url];
    }

    const hosts = XHS_VIDEO_PLAYBACK_HOSTS.includes(host)
      ? [host, ...XHS_VIDEO_PLAYBACK_HOSTS.filter((candidate) => candidate !== host)]
      : XHS_VIDEO_PLAYBACK_HOSTS;

    return uniqueValues(
      hosts.map((candidateHost) => {
        const candidate = new URL(url);
        candidate.protocol = "https:";
        candidate.hostname = candidateHost;
        candidate.search = "";
        candidate.hash = "";
        return candidate.toString();
      })
    );
  } catch {
    return [url];
  }
}

function isXhsVideoHost(host) {
  return host.startsWith("sns-video-") && host.endsWith(".xhscdn.com");
}

function renderImageFallbackAttrs(urls) {
  return renderFallbackAttrs(urls);
}

function renderFallbackAttrs(urls) {
  if (!urls.length) return "";
  return ` data-fallback-srcs="${escapeAttr(JSON.stringify(urls))}"`;
}

function handleImageError(event) {
  const image = event.target;
  if (!(image instanceof HTMLImageElement)) return;

  const fallbackUrls = parseImageFallbacks(image.dataset.fallbackSrcs);
  const fallbackIndex = Number(image.dataset.fallbackIndex || 0);
  if (fallbackIndex < fallbackUrls.length) {
    image.dataset.fallbackIndex = String(fallbackIndex + 1);
    image.src = fallbackUrls[fallbackIndex];
    return;
  }

  image.classList.add("image-load-failed");
  image.closest(".card-media, figure")?.classList.add("media-load-failed");
}

function parseImageFallbacks(value) {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
  } catch {
    return [];
  }
}

function handleVideoError(event) {
  const video = event.target;
  if (!(video instanceof HTMLVideoElement)) return;

  const fallbackUrls = parseImageFallbacks(video.dataset.fallbackSrcs);
  const fallbackIndex = Number(video.dataset.fallbackIndex || 0);
  if (fallbackIndex >= fallbackUrls.length) return;

  const wasPlaying = !video.paused;
  video.dataset.fallbackIndex = String(fallbackIndex + 1);
  video.src = fallbackUrls[fallbackIndex];
  video.load();
  if (wasPlaying) {
    video.play().catch(() => {});
  }
}

function renderSyncState() {
  if (!syncPanel || !syncStatus || !syncPushButton) return;

  const enabled = Boolean(readSyncField("enabled"));
  syncPanel.hidden = !enabled;
  if (!enabled) return;

  const dirty = hasDirtySync();
  const status = String(readSyncField("status") || "");
  const remoteConflict = status === "remote_conflict";
  const failed = status === "push_failed" || (dirty && Boolean(getSyncError(syncState)));
  const lastPushAt = readSyncField("last_push_at") || readSyncField("lastPushAt");

  syncPanel.classList.toggle("is-dirty", dirty && !failed);
  syncPanel.classList.toggle("is-failed", failed);
  syncPanel.classList.toggle("is-syncing", isSyncing);
  syncPanel.classList.toggle("is-conflict", remoteConflict);

  if (isSyncing) {
    syncStatus.textContent = "上传中";
  } else if (remoteConflict) {
    syncStatus.textContent = "云端冲突";
  } else if (failed) {
    syncStatus.textContent = "上传失败";
  } else if (dirty) {
    syncStatus.textContent = "有本地更改";
  } else if (lastPushAt) {
    syncStatus.textContent = `已同步 ${formatSyncTime(lastPushAt)}`;
  } else {
    syncStatus.textContent = "已同步";
  }

  syncPushButton.hidden = remoteConflict;
  syncPushButton.disabled = isSyncing || !dirty;
  syncPushButton.textContent = isSyncing ? "上传中" : "保存并上传";
  if (syncPullButton) {
    syncPullButton.hidden = !remoteConflict;
    syncPullButton.disabled = isSyncing;
  }
  if (syncForcePushButton) {
    syncForcePushButton.hidden = !remoteConflict;
    syncForcePushButton.disabled = isSyncing;
  }
}

function hasDirtySync() {
  if (!syncState || !readSyncField("enabled")) return false;
  const pendingRevision = Number(readSyncField("pending_revision") || readSyncField("pendingRevision") || 0);
  return Boolean(readSyncField("dirty")) || pendingRevision > 0;
}

function readSyncField(name) {
  if (!syncState) return undefined;
  if (Object.prototype.hasOwnProperty.call(syncState, name)) return syncState[name];
  const camelName = name.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
  return syncState[camelName];
}

function getSyncError(state) {
  if (!state) return "";
  return state.last_error || state.lastError || "";
}

function formatSyncTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function broadcastUpdate(type) {
  if (!syncChannel) return;
  syncChannel.postMessage({ type, source: tabId, at: Date.now() });
}

async function loadRemoteNotes() {
  const payload = await requestJson("/api/collections");
  notes = Array.isArray(payload.collections) ? payload.collections : [];
  updateRevisionFromPayload(payload);
  return notes;
}

async function refreshSyncState() {
  try {
    syncState = await requestJson("/api/sync/status");
  } catch {
    syncState = { enabled: false, status: "unavailable" };
  }
  return syncState;
}

async function saveAndUpload(options = {}) {
  if (!hasDirtySync() || isSyncing) return;

  isSyncing = true;
  renderSyncState();
  try {
    const payload = await requestJson("/api/sync/push", {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({ force: Boolean(options.force) })
    });
    syncState = payload.sync || payload;
    if (syncState.status === "synced_auto_merged" || syncState.status === "synced_overwrote_remote") {
      await loadRemoteNotes();
    }
    renderSyncState();
    broadcastUpdate("sync-state-updated");
    if (syncState.status === "remote_conflict") {
      showToast("云端已有新版本，请选择拉取云端或覆盖云端");
    } else if (hasDirtySync()) {
      showToast(getSyncError(syncState) || "上传失败，请重试");
    } else if (syncState.status === "synced_auto_merged") {
      showToast("已合并云端新增并上传");
    } else if (syncState.status === "synced_overwrote_remote") {
      showToast("已覆盖云端并上传");
    } else {
      showToast("已保存并上传");
    }
  } catch (error) {
    await refreshSyncState();
    renderSyncState();
    showToast(error.message || "上传失败，请重试");
  } finally {
    isSyncing = false;
    renderSyncState();
  }
}

async function pullCloudVersion() {
  if (isSyncing) return;
  isSyncing = true;
  renderSyncState();
  try {
    const payload = await requestJson("/api/sync/pull", { method: "POST" });
    syncState = payload.sync || payload;
    notes = Array.isArray(payload.collections) ? payload.collections : notes;
    updateRevisionFromPayload(payload);
    render();
    broadcastUpdate("sync-updated");
    showToast(syncState.local_backup_path ? "已拉取云端，本地更改已备份" : "已拉取云端");
  } catch (error) {
    await refreshSyncState();
    renderSyncState();
    showToast(error.message || "拉取云端失败");
  } finally {
    isSyncing = false;
    renderSyncState();
  }
}

async function refreshNote(id) {
  if (!id || refreshingIds.has(id)) return;
  const existing = notes.find((note) => note.id === id);
  if (!existing) return;

  refreshingIds.add(id);
  render();
  try {
    const payload = await requestJson(`/api/collections/${encodeURIComponent(id)}/refresh`, {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({ baseRevision: currentRevision })
    });
    if (payload.collection) {
      upsertNote(payload.collection);
      activeId = payload.collection.id;
    }
    updateRevisionFromPayload(payload);
    await refreshSyncState();
    render();
    broadcastUpdate("collections-updated");
    if (payload.refreshed) {
      showToast("已重新抓取");
    } else {
      showToast(payload.message || parseFailureMessage(payload.reason) || "重新抓取失败");
    }
  } catch (error) {
    await refreshSyncState();
    render();
    if (await handleConflict(error)) return;
    showToast(error.message || "重新抓取失败");
  } finally {
    refreshingIds.delete(id);
    render();
  }
}

async function reloadFromBackend() {
  try {
    await loadRemoteNotes();
    await refreshSyncState();
    render();
  } catch (error) {
    showToast(error.message || "数据刷新失败");
  }
}

async function migrateLocalNotes() {
  if (localStorage.getItem(MIGRATION_KEY) === "true") return;

  const localNotes = loadLocalNotes();
  if (!localNotes.length) {
    localStorage.setItem(MIGRATION_KEY, "true");
    return;
  }

  await importCollections(localNotes);
  localStorage.setItem(MIGRATION_KEY, "true");
}

async function importCollections(collections) {
  const payload = await requestJson("/api/collections/import-local", {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({ collections, baseRevision: currentRevision })
  });
  notes = Array.isArray(payload.collections) ? payload.collections : [];
  updateRevisionFromPayload(payload);
  await refreshSyncState();
  broadcastUpdate("collections-updated");
  return notes;
}

async function handleConflict(error, options = {}) {
  if (error?.payload?.error !== "CONFLICT") return false;
  const draft = options.keepEditor
    ? {
        title: editTitle.value,
        content: editContent.value,
        tags: editTags.value,
        sourceUrl: editSourceUrl.value
      }
    : null;
  await reloadFromBackend();
  if (draft) {
    editTitle.value = draft.title;
    editContent.value = draft.content;
    editTags.value = draft.tags;
    editSourceUrl.value = draft.sourceUrl;
  }
  showToast(error.payload.message || "数据已在其他页面更新，请重新确认");
  return true;
}

function updateRevisionFromPayload(payload) {
  const revision = Number(payload?.revision);
  if (Number.isFinite(revision)) {
    currentRevision = revision;
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const error = new Error(payload.message || "请求失败");
    error.payload = payload;
    error.reason = payload.reason || payload.error || "";
    throw error;
  }
  return payload;
}

function focusCollectionCard(id) {
  if (!id) return;
  window.requestAnimationFrame(() => {
    const card = list.querySelector(`[data-id="${cssEscape(id)}"]`);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
  });
}

function parseFailureMessage(reason) {
  const messages = {
    INVALID_LINK: "链接无效或暂不支持",
    MISSING_XSEC_TOKEN: "链接缺少 xsec_token，请使用rednote App 分享链接",
    NETWORK_FAILED: "网络异常，请重试",
    PLATFORM_BLOCKED: "rednote限制了本次访问，请稍后重试",
    CONTENT_NOT_FOUND: "链接无效、笔记不存在或不可见",
    PARSE_SCHEMA_CHANGED: "页面结构变化，暂时无法解析",
    UNKNOWN: "未知错误"
  };
  return messages[reason] || "";
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

function loadLocalNotes() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
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
    xiaohongshu: { key: "xiaohongshu", label: "rednote" },
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
  if (["xiaohongshu", "xhs", "red", "rednote"].includes(text)) return "xiaohongshu";
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
  const hasOpenModal =
    !editorModal.classList.contains("hidden") ||
    !clearConfirmModal.classList.contains("hidden") ||
    !noteModal.classList.contains("hidden");
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
      if (undo) {
        Promise.resolve(undo()).catch((error) => showToast(error.message || "撤销失败"));
      }
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
