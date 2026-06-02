import {
  ALL_VALUE,
  SORT_OPTIONS,
  TYPE_OPTIONS,
  createBatchImportPlan,
  createViewState,
  getCollectionView,
  getMediaAspectRatio,
  getPlatformMeta,
  normalizeImportDataFile,
  parseTags
} from "./view-model.js";

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
const exportJsonButton = document.querySelector("#exportJsonButton");
const importJsonButton = document.querySelector("#importJsonButton");
const importJsonInput = document.querySelector("#importJsonInput");
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
const collectionSearch = document.querySelector("#collectionSearch");
const platformFilter = document.querySelector("#platformFilter");
const typeFilter = document.querySelector("#typeFilter");
const tagFilter = document.querySelector("#tagFilter");
const sortSelect = document.querySelector("#sortSelect");
const clearViewButton = document.querySelector("#clearViewButton");
const batchImportPanel = document.querySelector("#batchImportPanel");
const batchImportSummary = document.querySelector("#batchImportSummary");
const batchImportSafety = document.querySelector("#batchImportSafety");
const batchImportProgress = document.querySelector("#batchImportProgress");
const batchImportResults = document.querySelector("#batchImportResults");

const STORE_KEY = "opencollect:xhs:poc";
const MIGRATION_KEY = "opencollect:xhs:poc:migrated:v1";
const XHS_IMAGE_STYLE_SUFFIX = "!nd_dft_wlteh_webp_3";
const XHS_VIDEO_PLAYBACK_HOSTS = ["sns-video-bd.xhscdn.com", "sns-video-hw.xhscdn.com"];
const BATCH_IMPORT_LIMIT = 20;
const DEFAULT_BATCH_IMPORT_DELAY_MS = 2000;
let notes = [];
let activeId = "";
let editingId = "";
let pendingUndo = null;
let renderedColumnCount = 0;
let resizeTimer = 0;
let syncState = null;
let isSyncing = false;
let batchImport = null;
let currentRevision = 0;
let viewState = createViewState();
let openCardMenuId = "";
const refreshingIds = new Set();
const tabId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
const syncChannel = "BroadcastChannel" in window ? new BroadcastChannel("opencollect-sync") : null;

render();
initialize();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = input.value.trim();
  if (!value) return;
  const plan = createBatchImportPlan(value, { limit: BATCH_IMPORT_LIMIT });
  if (plan.totalExtracted > 1) {
    await collectBatch(value, plan);
    return;
  }
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
exportJsonButton?.addEventListener("click", exportCollectionsJson);
importJsonButton?.addEventListener("click", () => importJsonInput?.click());
importJsonInput?.addEventListener("change", importCollectionsJsonFile);
collectionSearch?.addEventListener("input", () => {
  viewState = createViewState({ ...viewState, query: collectionSearch.value });
  render();
});
platformFilter?.addEventListener("change", () => {
  viewState = createViewState({ ...viewState, platform: platformFilter.value });
  render();
});
typeFilter?.addEventListener("change", () => {
  viewState = createViewState({ ...viewState, type: typeFilter.value });
  render();
});
tagFilter?.addEventListener("change", () => {
  viewState = createViewState({ ...viewState, tag: tagFilter.value });
  render();
});
sortSelect?.addEventListener("change", () => {
  viewState = createViewState({ ...viewState, sort: sortSelect.value });
  render();
});
clearViewButton?.addEventListener("click", () => {
  viewState = createViewState();
  render();
});

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

document.addEventListener("click", (event) => {
  if (!openCardMenuId) return;
  if (event.target instanceof Element && event.target.closest(".card-menu")) return;
  openCardMenuId = "";
  renderList();
});

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
    const payload = await submitCollect(value);
    if (payload.duplicated) {
      activeId = payload.existingId || payload.note?.id || "";
      viewState = createViewState();
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

async function submitCollect(value) {
  const payload = await requestJson("/api/collect", {
    method: "POST",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({ input: value, baseRevision: currentRevision })
  });
  updateRevisionFromPayload(payload);
  upsertNote(payload.note);
  return payload;
}

async function collectBatch(value, plan = createBatchImportPlan(value, { limit: BATCH_IMPORT_LIMIT })) {
  const submit = form.querySelector("button[type='submit']");
  const duplicateInputCount = plan.results.filter((item) => item.status === "duplicate-input").length;
  batchImport = {
    active: true,
    paused: false,
    total: plan.total,
    totalExtracted: plan.totalExtracted,
    overflow: plan.overflow,
    completed: duplicateInputCount,
    success: 0,
    failed: 0,
    duplicated: duplicateInputCount,
    results: plan.results.map((item) => ({ ...item }))
  };
  recomputeBatchImportStats();
  renderBatchImport();

  if (!plan.total) {
    batchImport.active = false;
    showToast("没有识别到链接，请粘贴rednote分享文本或 URL");
    renderBatchImport();
    return;
  }

  setBusy(submit, true, "导入中");
  sampleButton.disabled = true;
  videoSampleButton.disabled = true;

  let consecutiveNetworkFailures = 0;
  let changed = false;
  try {
    for (const result of batchImport.results) {
      if (result.status !== "pending") continue;

      result.status = "running";
      result.message = "解析中";
      renderBatchImport();

      try {
        const payload = await submitCollect(result.url);
        changed = applyBatchSuccess(result, payload) || changed;
        consecutiveNetworkFailures = 0;
        await refreshSyncState();
        viewState = createViewState();
        render();
      } catch (error) {
        applyBatchFailure(result, error);
        consecutiveNetworkFailures = result.reason === "NETWORK_FAILED" ? consecutiveNetworkFailures + 1 : 0;
        renderBatchImport();

        if (await handleConflict(error)) {
          pauseRemainingBatchResults("数据已更新，已暂停剩余导入");
          break;
        }

        if (shouldPauseBatch(result.reason, consecutiveNetworkFailures)) {
          batchImport.paused = true;
          pauseRemainingBatchResults("平台或网络限制，已暂停剩余导入");
          break;
        }
      }

      if (!batchImport.active || batchImport.paused) break;
      if (hasPendingBatchResults()) {
        await delay(getBatchImportDelayMs());
      }
    }
  } finally {
    batchImport.active = false;
    await refreshSyncState();
    render();
    if (changed) broadcastUpdate("collections-updated");
    input.value = "";
    setBusy(submit, false, "收藏");
    sampleButton.disabled = false;
    videoSampleButton.disabled = false;
    showToast(batchImportSummaryText());
  }
}

function applyBatchSuccess(result, payload) {
  result.noteId = payload.note?.id || "";
  result.title = payload.note?.title || "";
  result.reason = "";
  if (payload.duplicated) {
    result.status = "duplicate";
    result.existingId = payload.existingId || payload.note?.id || "";
    result.message = "已收藏过";
    recomputeBatchImportStats();
    return false;
  }

  result.status = "success";
  result.message = "已收藏";
  recomputeBatchImportStats();
  return true;
}

function applyBatchFailure(result, error) {
  result.status = "failed";
  result.reason = error.reason || "";
  result.message = error.message || "解析失败";
  recomputeBatchImportStats();
}

function recomputeBatchImportStats() {
  if (!batchImport) return;
  const results = batchImport.results || [];
  batchImport.completed = results.filter((result) => !["pending", "running"].includes(result.status)).length;
  batchImport.success = results.filter((result) => result.status === "success").length;
  batchImport.failed = results.filter((result) => result.status === "failed").length;
  batchImport.duplicated = results.filter((result) => result.status === "duplicate" || result.status === "duplicate-input").length;
  batchImport.paused = results.some((result) => result.status === "paused");
}

async function retryBatchResult(resultId) {
  if (!batchImport) return;
  if (batchImport.active) {
    showToast("已有导入任务进行中");
    return;
  }
  const result = batchImport.results.find((item) => item.id === resultId);
  if (!result || !["failed", "paused"].includes(result.status)) return;

  batchImport.active = true;
  result.status = "running";
  result.message = "解析中";
  result.reason = "";
  recomputeBatchImportStats();
  renderBatchImport();

  let changed = false;
  try {
    const payload = await submitCollect(result.url);
    changed = applyBatchSuccess(result, payload);
    await refreshSyncState();
    viewState = createViewState();
    render();
  } catch (error) {
    applyBatchFailure(result, error);
    renderBatchImport();
    await refreshSyncState();
    if (await handleConflict(error)) {
      result.status = "failed";
      result.message = error.message || "数据已更新，请重新确认后重试";
      result.reason = error.reason || "CONFLICT";
    }
  } finally {
    batchImport.active = false;
    recomputeBatchImportStats();
    await refreshSyncState();
    render();
    if (changed) broadcastUpdate("collections-updated");
    showToast(batchImportSummaryText());
  }
}

function shouldPauseBatch(reason, consecutiveNetworkFailures) {
  return reason === "PLATFORM_BLOCKED" || reason === "PARSE_SCHEMA_CHANGED" || consecutiveNetworkFailures >= 2;
}

function hasPendingBatchResults() {
  return Boolean(batchImport?.results?.some((result) => result.status === "pending"));
}

function pauseRemainingBatchResults(message) {
  if (!batchImport) return;
  for (const result of batchImport.results) {
    if (result.status !== "pending") continue;
    result.status = "paused";
    result.message = message;
  }
  recomputeBatchImportStats();
  renderBatchImport();
}

function getBatchImportDelayMs() {
  const override = Number(window.OPENCOLLECT_BATCH_DELAY_MS);
  if (Number.isFinite(override) && override >= 0) return override;
  return DEFAULT_BATCH_IMPORT_DELAY_MS;
}

function delay(ms) {
  if (ms <= 0) return Promise.resolve();
  return new Promise((resolve) => window.setTimeout(resolve, ms));
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
  const view = getCollectionView(notes, viewState);
  countBadge.textContent = view.hasFilters ? `${view.visible}/${view.total}` : String(view.total);
  countBadge.title = view.hasFilters ? `当前结果 ${view.visible} 条，全部收藏 ${view.total} 条` : `全部收藏 ${view.total} 条`;
  clearAllButton.hidden = notes.length === 0;
  renderViewControls(view);
  renderSyncState();
  renderBatchImport();
  renderList(view);
  renderActiveNote();
}

function renderViewControls(view) {
  if (collectionSearch && collectionSearch.value !== view.state.query) {
    collectionSearch.value = view.state.query;
  }

  updateSelectOptions(
    platformFilter,
    [{ value: ALL_VALUE, label: "全部平台" }, ...view.platforms.map((platform) => ({ value: platform.key, label: platform.label }))],
    view.state.platform
  );
  updateSelectOptions(typeFilter, TYPE_OPTIONS, view.state.type);
  updateSelectOptions(tagFilter, [{ value: "", label: "全部标签" }, ...view.tags.map((tag) => ({ value: tag, label: `#${tag}` }))], view.state.tag);
  updateSelectOptions(sortSelect, SORT_OPTIONS, view.state.sort);

  if (clearViewButton) {
    clearViewButton.hidden = !view.hasFilters && view.state.sort === "collected-desc";
  }
}

function updateSelectOptions(select, options, selectedValue) {
  if (!select) return;
  const normalizedOptions = options.some((option) => option.value === selectedValue) || selectedValue === ""
    ? options
    : [...options, { value: selectedValue, label: `#${selectedValue}` }];
  const nextHtml = normalizedOptions
    .map((option) => `<option value="${escapeAttr(option.value)}">${escapeHtml(option.label)}</option>`)
    .join("");
  if (select.innerHTML !== nextHtml) {
    select.innerHTML = nextHtml;
  }
  select.value = selectedValue;
}

function applyTagFilter(tag, options = {}) {
  viewState = createViewState({ ...viewState, tag });
  if (options.closeActive) {
    activeId = "";
  }
  render();
}

function renderList(view = getCollectionView(notes, viewState)) {
  if (!notes.length) {
    list.classList.add("empty");
    list.style.removeProperty("--masonry-columns");
    list.innerHTML = renderStateCard({
      tone: "empty",
      title: "暂无收藏",
      message: "粘贴rednote分享链接，或加载一个示例。"
    });
    return;
  }

  if (!view.items.length) {
    list.classList.add("empty");
    list.style.removeProperty("--masonry-columns");
    list.innerHTML = renderStateCard({
      tone: "filtered",
      title: "没有匹配收藏",
      message: "换个关键词，或清除当前筛选。"
    });
    return;
  }

  list.classList.remove("empty");
  renderedColumnCount = getMasonryColumnCount();
  list.style.setProperty("--masonry-columns", String(renderedColumnCount));
  const columns = Array.from({ length: renderedColumnCount }, () => []);

  view.items.forEach((note, index) => {
    columns[index % renderedColumnCount].push(renderCollectionCard(note));
  });

  list.innerHTML = columns
    .map((items, index) => `<div class="masonry-column" data-column="${index + 1}">${items.join("")}</div>`)
    .join("");

  list.querySelectorAll('[data-action="open-note"]').forEach((button) => {
    button.addEventListener("click", () => {
      openCardMenuId = "";
      activeId = button.dataset.id;
      render();
      noteView.focus({ preventScroll: true });
    });
  });

  list.querySelectorAll('[data-action="edit-note"]').forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.id;
      openCardMenuId = "";
      renderList();
      openEditor(id);
    });
  });

  list.querySelectorAll('[data-action="delete-note"]').forEach((button) => {
    button.addEventListener("click", () => {
      openCardMenuId = "";
      deleteNote(button.dataset.id);
    });
  });

  list.querySelectorAll('[data-action="refresh-note"]').forEach((button) => {
    button.addEventListener("click", () => {
      openCardMenuId = "";
      refreshNote(button.dataset.id);
    });
  });

  list.querySelectorAll('[data-action="filter-tag"]').forEach((button) => {
    button.addEventListener("click", () => {
      openCardMenuId = "";
      applyTagFilter(button.dataset.tag || "");
    });
  });

  list.querySelectorAll('[data-action="toggle-card-menu"]').forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const id = button.dataset.id || "";
      openCardMenuId = openCardMenuId === id ? "" : id;
      renderList();
    });
  });
}

function renderCollectionCard(note) {
  const coverUrls = getImageProxyUrls(note.images);
  const cover = coverUrls[0] || "";
  const avatar = note.author?.avatar ? imageProxy(note.author.avatar) : "";
  const authorName = note.author?.name || "未知作者";
  const isActive = note.id === activeId ? " active" : "";
  const isVideo = Boolean(note.video?.url);
  const title = note.title || note.content || "无标题笔记";
  const platform = getPlatformMeta(note);
  const mediaRatio = getMediaAspectRatio(note).toFixed(3);
  const isMenuOpen = openCardMenuId === note.id;

  return `
    <article class="collection-item${isActive}${isVideo ? " video-card" : ""}" data-id="${escapeAttr(note.id)}" style="--media-ratio: ${escapeAttr(mediaRatio)};">
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
      ${renderCardTags(note)}
      ${renderCardMenu(note, isMenuOpen)}
    </article>
  `;
}

function renderCardTags(note) {
  const tags = (note.tags || []).slice(0, 3);
  if (!tags.length) return "";
  return `
    <span class="card-tags" aria-label="标签">
      ${tags.map((tag) => `<button type="button" data-action="filter-tag" data-tag="${escapeAttr(tag)}">#${escapeHtml(tag)}</button>`).join("")}
    </span>
  `;
}

function renderCardMenu(note, isOpen) {
  return `
    <span class="card-menu${isOpen ? " open" : ""}" aria-label="收藏操作">
      <button
        type="button"
        class="card-menu-toggle"
        data-action="toggle-card-menu"
        data-id="${escapeAttr(note.id)}"
        aria-label="打开收藏操作"
        aria-expanded="${isOpen ? "true" : "false"}"
      >...</button>
      <span class="card-menu-popover" ${isOpen ? "" : "hidden"}>
        <button type="button" data-action="refresh-note" data-id="${escapeAttr(note.id)}" ${refreshingIds.has(note.id) ? "disabled" : ""}>${refreshingIds.has(note.id) ? "刷新中" : "重新抓取"}</button>
        <button type="button" data-action="edit-note" data-id="${escapeAttr(note.id)}">编辑</button>
        <button type="button" class="danger" data-action="delete-note" data-id="${escapeAttr(note.id)}">删除</button>
      </span>
    </span>
  `;
}

function renderStateCard({ tone = "neutral", title, message, compact = false }) {
  return `
    <div class="state-card state-card-${escapeAttr(tone)}${compact ? " compact" : ""}">
      <span class="state-visual" aria-hidden="true">
        <span></span>
        <span></span>
        <span></span>
      </span>
      <strong>${escapeHtml(title)}</strong>
      ${message ? `<small>${escapeHtml(message)}</small>` : ""}
    </div>
  `;
}

function renderBatchImport() {
  if (!batchImportPanel || !batchImportSummary || !batchImportProgress || !batchImportResults) return;
  if (!batchImport) {
    batchImportPanel.classList.add("hidden");
    return;
  }

  const total = Math.max(1, batchImport.total || 0);
  const completed = Math.min(batchImport.completed || 0, total);
  const percent = Math.round((completed / total) * 100);
  batchImportPanel.classList.remove("hidden");
  batchImportPanel.classList.toggle("is-active", Boolean(batchImport.active));
  batchImportPanel.classList.toggle("is-paused", Boolean(batchImport.paused));
  batchImportSummary.textContent = batchImportSummaryText();
  if (batchImportSafety) {
    batchImportSafety.textContent = batchImport.paused ? "已暂停" : batchImport.active ? "保守串行" : "已完成";
  }
  batchImportProgress.style.width = `${percent}%`;
  batchImportResults.innerHTML = batchImport.results.map(renderBatchResult).join("");
  batchImportResults.querySelectorAll("[data-batch-locate]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.getAttribute("data-batch-locate") || "";
      if (!id) return;
      activeId = id;
      viewState = createViewState();
      render();
      focusCollectionCard(id);
    });
  });
  batchImportResults.querySelectorAll("[data-batch-retry]").forEach((button) => {
    button.addEventListener("click", () => {
      retryBatchResult(button.getAttribute("data-batch-retry") || "");
    });
  });
}

function batchImportSummaryText() {
  if (!batchImport) return "等待开始";
  const pieces = [
    `${batchImport.completed}/${batchImport.total} 完成`,
    `成功 ${batchImport.success}`,
    `重复 ${batchImport.duplicated}`,
    `失败 ${batchImport.failed}`
  ];
  if (batchImport.overflow > 0) pieces.push(`超出 ${batchImport.overflow} 条未导入`);
  if (batchImport.paused) pieces.push("已暂停");
  return pieces.join(" · ");
}

function renderBatchResult(result) {
  const status = batchStatusMeta(result.status);
  const title = result.title || result.url;
  const locateId = result.existingId || (result.status === "success" ? result.noteId : "");
  const canRetry = ["failed", "paused"].includes(result.status);
  const reasonMessage = parseFailureMessage(result.reason) || result.reason || "";
  const detailMessage = [result.message || status.label, reasonMessage]
    .filter((message, index, messages) => message && messages.indexOf(message) === index)
    .join(" · ");
  return `
    <li class="batch-result status-${escapeAttr(result.status)}">
      <span class="batch-result-index">${escapeHtml(result.index)}</span>
      <span class="batch-result-main">
        <strong>${escapeHtml(title)}</strong>
        <small>${escapeHtml(detailMessage)}</small>
      </span>
      <span class="batch-result-status">${escapeHtml(status.label)}</span>
      ${locateId ? `<button type="button" class="batch-locate" data-batch-locate="${escapeAttr(locateId)}">定位</button>` : ""}
      ${canRetry ? `<button type="button" class="batch-retry" data-batch-retry="${escapeAttr(result.id)}" ${batchImport?.active ? "disabled" : ""}>重试</button>` : ""}
    </li>
  `;
}

function batchStatusMeta(status) {
  const labels = {
    pending: "等待",
    running: "解析中",
    success: "成功",
    duplicate: "重复",
    "duplicate-input": "重复",
    failed: "失败",
    paused: "暂停"
  };
  return { label: labels[status] || "未知" };
}

function getMasonryColumnCount() {
  const width = list.getBoundingClientRect().width || document.documentElement.clientWidth || window.innerWidth;
  const minCardWidth = width <= 560 ? 158 : width <= 920 ? 180 : 230;
  const gap = width <= 560 ? 12 : 18;
  const count = Math.floor((width + gap) / (minCardWidth + gap));
  return Math.max(1, Math.min(7, count || 1));
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
  const collectedAt = formatDate(note.collectedAt || note.createdAt);
  const sourceCreatedAt = note.sourceCreatedAt ? formatDate(note.sourceCreatedAt) : "";

  noteView.innerHTML = `
    <header class="note-header">
      <div class="author">
        ${authorAvatar ? `<img src="${escapeAttr(authorAvatar)}" alt="" />` : `<span class="avatar-fallback"></span>`}
        <div>
          <strong>${escapeHtml(authorName)}</strong>
          <small><span class="detail-platform platform-${escapeAttr(platform.key)}">${escapeHtml(platform.label)}</span>${collectedAt}</small>
        </div>
      </div>
      <button type="button" class="detail-close" data-action="collapse-detail" aria-label="关闭详情" title="关闭详情">×</button>
    </header>

    ${media}

    <div class="note-copy">
      <div class="detail-meta-row" aria-label="笔记来源和时间">
        <span class="detail-platform platform-${escapeAttr(platform.key)}">${escapeHtml(platform.label)}</span>
        <span>收藏于 ${collectedAt}</span>
        ${sourceCreatedAt ? `<span>发布于 ${sourceCreatedAt}</span>` : ""}
      </div>
      <article class="note-article">
        <h2 id="noteDetailTitle">${escapeHtml(note.title || "无标题笔记")}</h2>
        <div class="note-text">${formatContent(note.content || "这条收藏暂时没有正文。")}</div>
      </article>
      ${renderFetchNotice(note)}
      ${note.tags?.length ? `<div class="tags detail-tags" aria-label="标签">${note.tags.map((tag) => `<button type="button" data-action="filter-tag" data-tag="${escapeAttr(tag)}">#${escapeHtml(tag)}</button>`).join("")}</div>` : ""}
    </div>

    <footer class="detail-footer">
      ${renderDetailStats(note)}
      <div class="note-actions">
        ${note.sourceUrl ? `<a class="source-link" href="${escapeAttr(note.sourceUrl)}" target="_blank" rel="noreferrer">原文</a>` : ""}
        <button type="button" class="note-tool" data-action="refresh-active" ${isRefreshing ? "disabled" : ""}>${isRefreshing ? "刷新中" : "重新抓取"}</button>
        <button type="button" class="note-tool" data-action="edit-active">编辑</button>
        <button type="button" class="note-tool danger" data-action="delete-active">删除</button>
      </div>
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

  noteView.querySelectorAll('[data-action="filter-tag"]').forEach((button) => {
    button.addEventListener("click", () => applyTagFilter(button.dataset.tag || "", { closeActive: true }));
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
        ${renderStateCard({
          tone: "media",
          title: "缺少视频地址",
          message: "请重新抓取或重新收藏原链接。"
        })}
      </div>
    `;
  }

  if (!note.images?.length) {
    return `
      <div class="media-empty">
        ${renderStateCard({
          tone: "media",
          title: "暂无媒体",
          message: "这条收藏没有可展示的图片内容。"
        })}
      </div>
    `;
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
  return renderStateCard({
    tone: "warning",
    title: "最近抓取失败",
    message,
    compact: true
  });
}

function renderDetailStats(note) {
  return `
    <div class="stats" aria-label="互动数据">
      <span><strong>${escapeHtml(note.stats?.likes || "0")}</strong>赞</span>
      <span><strong>${escapeHtml(note.stats?.collects || "0")}</strong>收藏</span>
      <span><strong>${escapeHtml(note.stats?.comments || "0")}</strong>评论</span>
      <span><strong>${escapeHtml(note.stats?.shares || "0")}</strong>分享</span>
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

async function exportCollectionsJson() {
  if (!exportJsonButton) return;
  setBusy(exportJsonButton, true, "导出中");
  try {
    const payload = await requestJson("/api/collections/export");
    downloadJson(payload);
    showToast(`已导出 ${Array.isArray(payload.collections) ? payload.collections.length : 0} 条收藏`);
  } catch (error) {
    showToast(error.message || "导出失败");
  } finally {
    setBusy(exportJsonButton, false, "导出 JSON");
  }
}

async function importCollectionsJsonFile(event) {
  const file = event.target?.files?.[0];
  if (!file || !importJsonButton) return;

  setBusy(importJsonButton, true, "导入中");
  try {
    const text = await file.text();
    const data = parseImportJson(text);
    const payload = await requestJson("/api/collections/import-json", {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({ ...data, baseRevision: currentRevision })
    });
    notes = Array.isArray(payload.collections) ? payload.collections : [];
    updateRevisionFromPayload(payload);
    await refreshSyncState();
    viewState = createViewState();
    render();
    broadcastUpdate("collections-updated");
    showToast(`已导入 ${payload.imported || 0} 条，更新 ${payload.updated || 0} 条`);
  } catch (error) {
    if (await handleConflict(error)) return;
    showToast(error.message || "导入失败");
  } finally {
    setBusy(importJsonButton, false, "导入 JSON");
    event.target.value = "";
  }
}

function parseImportJson(text) {
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error("导入文件不是合法 JSON");
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("不支持的导入文件");
  }
  return normalizeImportDataFile(payload);
}

function downloadJson(payload) {
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = `opencollect-collections-rev${Number(payload?.revision || 0)}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
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
