export const ALL_VALUE = "all";

export const TYPE_OPTIONS = [
  { value: ALL_VALUE, label: "全部类型" },
  { value: "normal", label: "图文" },
  { value: "video", label: "视频" }
];

export const SORT_OPTIONS = [
  { value: "collected-desc", label: "收藏时间 新到旧" },
  { value: "collected-asc", label: "收藏时间 旧到新" },
  { value: "source-desc", label: "发布时间 新到旧" },
  { value: "source-asc", label: "发布时间 旧到新" }
];

const URL_RE = /https?:\/\/[^\s"'<>）)]+/g;

export function createViewState(overrides = {}) {
  return normalizeViewState({
    query: "",
    platform: ALL_VALUE,
    type: ALL_VALUE,
    tag: "",
    sort: "collected-desc",
    ...overrides
  });
}

export function normalizeViewState(state = {}) {
  const sortValues = new Set(SORT_OPTIONS.map((option) => option.value));
  const typeValues = new Set(TYPE_OPTIONS.map((option) => option.value));
  return {
    query: String(state.query || "").trim(),
    platform: normalizeSelectValue(state.platform),
    type: typeValues.has(state.type) ? state.type : ALL_VALUE,
    tag: normalizeTag(state.tag || ""),
    sort: sortValues.has(state.sort) ? state.sort : "collected-desc"
  };
}

export function getCollectionView(notes, state = createViewState()) {
  const normalizedState = normalizeViewState(state);
  const source = Array.isArray(notes) ? notes : [];
  const filtered = source.filter((note) => matchesView(note, normalizedState));
  const items = sortNotes(filtered, normalizedState.sort);

  return {
    items,
    state: normalizedState,
    total: source.length,
    visible: items.length,
    hasFilters: hasActiveFilters(normalizedState),
    platforms: getAvailablePlatforms(source),
    tags: getAvailableTags(source)
  };
}

export function hasActiveFilters(state = {}) {
  const normalizedState = normalizeViewState(state);
  return Boolean(normalizedState.query) || normalizedState.platform !== ALL_VALUE || normalizedState.type !== ALL_VALUE || Boolean(normalizedState.tag);
}

export function matchesView(note, state) {
  return matchesSearch(note, state.query) && matchesPlatform(note, state.platform) && matchesType(note, state.type) && matchesTag(note, state.tag);
}

export function matchesSearch(note, query) {
  const terms = tokenizeQuery(query);
  if (!terms.length) return true;
  const haystack = normalizeSearchText(
    [
      note?.title,
      note?.content,
      note?.author?.name,
      ...(Array.isArray(note?.tags) ? note.tags : [])
    ].join(" ")
  );
  return terms.every((term) => haystack.includes(term));
}

export function matchesPlatform(note, platform) {
  const value = normalizeSelectValue(platform);
  if (value === ALL_VALUE) return true;
  return getPlatformMeta(note).key === value;
}

export function matchesType(note, type) {
  const value = normalizeSelectValue(type);
  if (value === ALL_VALUE) return true;
  return getNoteType(note) === value;
}

export function matchesTag(note, tag) {
  const normalizedTag = normalizeTag(tag);
  if (!normalizedTag) return true;
  return normalizeTags(note?.tags || []).includes(normalizedTag);
}

export function sortNotes(notes, sort = "collected-desc") {
  const [field, direction] = String(sort || "collected-desc").split("-");
  const decorated = (Array.isArray(notes) ? notes : []).map((note, index) => ({ note, index }));
  decorated.sort((left, right) => {
    const leftTime = getSortTime(left.note, field);
    const rightTime = getSortTime(right.note, field);

    if (leftTime.valid !== rightTime.valid) return leftTime.valid ? -1 : 1;
    if (leftTime.valid && rightTime.valid && leftTime.value !== rightTime.value) {
      return direction === "asc" ? leftTime.value - rightTime.value : rightTime.value - leftTime.value;
    }
    return left.index - right.index;
  });
  return decorated.map((item) => item.note);
}

export function getAvailablePlatforms(notes) {
  const seen = new Set();
  const platforms = [];
  for (const note of Array.isArray(notes) ? notes : []) {
    const platform = getPlatformMeta(note);
    if (seen.has(platform.key)) continue;
    seen.add(platform.key);
    platforms.push(platform);
  }
  return platforms.sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
}

export function getAvailableTags(notes) {
  const seen = new Set();
  const tags = [];
  for (const note of Array.isArray(notes) ? notes : []) {
    for (const tag of normalizeTags(note?.tags || [])) {
      if (seen.has(tag)) continue;
      seen.add(tag);
      tags.push(tag);
    }
  }
  return tags.sort((left, right) => left.localeCompare(right, "zh-CN"));
}

export function parseTags(value) {
  if (Array.isArray(value)) return normalizeTags(value);
  return normalizeTags(String(value || "").split(/[\s,，、]+/));
}

export function normalizeTags(tags) {
  const result = [];
  const seen = new Set();
  for (const tag of Array.isArray(tags) ? tags : []) {
    const value = normalizeTag(tag);
    if (!value || seen.has(value)) continue;
    seen.add(value);
    result.push(value);
  }
  return result;
}

export function normalizeTag(value) {
  return String(value || "")
    .trim()
    .replace(/^#+/, "")
    .replace(/#+$/, "")
    .replace(/\[话题\]$/, "")
    .trim();
}

export function getPlatformMeta(note) {
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

export function normalizePlatformKey(value) {
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

export function inferPlatformFromUrl(rawUrl) {
  try {
    const host = new URL(rawUrl).hostname.toLowerCase();
    if (host.includes("xiaohongshu.com") || host.includes("xhslink.com")) return "xiaohongshu";
    if (host.includes("douyin.com")) return "douyin";
    if (host.includes("bilibili.com") || host.includes("b23.tv")) return "bilibili";
    if (host.includes("youtube.com") || host.includes("youtu.be")) return "youtube";
    if (host.includes("instagram.com")) return "instagram";
    if (host.includes("tiktok.com")) return "tiktok";
    if (host.includes("weixin.qq.com") || host.includes("mp.weixin.qq.com")) return "wechat";
  } catch {
    return "";
  }
  return "";
}

export function getNoteType(note) {
  return note?.type === "video" || Boolean(note?.video?.url) ? "video" : "normal";
}

export function getMediaAspectRatio(note) {
  const dimensions = getPrimaryMediaDimensions(note);
  if (!dimensions) return 0.75;
  return clampRatio(dimensions.width / dimensions.height);
}

export function extractUrls(inputText) {
  const matches = String(inputText || "").match(URL_RE) || [];
  return matches.map(normalizeExtractedUrl).filter(Boolean);
}

export function createBatchImportPlan(inputText, options = {}) {
  const limit = Number.isFinite(Number(options.limit)) && Number(options.limit) > 0 ? Number(options.limit) : 20;
  const urls = extractUrls(inputText);
  const limitedUrls = urls.slice(0, limit);
  const seen = new Map();
  const results = limitedUrls.map((url, index) => {
    const key = normalizeBatchUrlKey(url);
    const firstIndex = seen.get(key);
    if (firstIndex !== undefined) {
      return {
        id: `input-${index + 1}`,
        url,
        index: index + 1,
        status: "duplicate-input",
        duplicateOf: firstIndex + 1,
        message: "本批次重复链接，已跳过"
      };
    }
    seen.set(key, index);
    return {
      id: `input-${index + 1}`,
      url,
      index: index + 1,
      status: "pending",
      message: "等待导入"
    };
  });

  return {
    totalExtracted: urls.length,
    total: limitedUrls.length,
    overflow: Math.max(0, urls.length - limitedUrls.length),
    queued: results.filter((result) => result.status === "pending").length,
    results
  };
}

function normalizeExtractedUrl(rawUrl) {
  return String(rawUrl || "").trim().replace(/[，。,.;；、!！]+$/g, "");
}

function normalizeBatchUrlKey(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    parsed.hash = "";
    return parsed.toString();
  } catch {
    return rawUrl;
  }
}

function getPrimaryMediaDimensions(note) {
  const videoWidth = Number(note?.video?.width || 0);
  const videoHeight = Number(note?.video?.height || 0);
  if (getNoteType(note) === "video" && videoWidth > 0 && videoHeight > 0) {
    return { width: videoWidth, height: videoHeight };
  }

  const image = Array.isArray(note?.images) ? note.images[0] : null;
  const imageWidth = Number(image?.width || 0);
  const imageHeight = Number(image?.height || 0);
  if (imageWidth > 0 && imageHeight > 0) {
    return { width: imageWidth, height: imageHeight };
  }

  if (videoWidth > 0 && videoHeight > 0) {
    return { width: videoWidth, height: videoHeight };
  }

  return null;
}

function clampRatio(value) {
  if (!Number.isFinite(value) || value <= 0) return 0.75;
  return Math.min(1.35, Math.max(0.72, value));
}

function tokenizeQuery(query) {
  return normalizeSearchText(query)
    .split(/\s+/)
    .filter(Boolean);
}

function normalizeSearchText(value) {
  return String(value || "").trim().toLocaleLowerCase("zh-CN");
}

function normalizeSelectValue(value) {
  return String(value || ALL_VALUE).trim() || ALL_VALUE;
}

function getSortTime(note, field) {
  const candidates =
    field === "source"
      ? [note?.sourceCreatedAt, note?.createdAt]
      : [note?.collectedAt, note?.updatedAt, note?.createdAt, note?.sourceCreatedAt];
  for (const candidate of candidates) {
    const timestamp = Date.parse(candidate || "");
    if (Number.isFinite(timestamp)) return { valid: true, value: timestamp };
  }
  return { valid: false, value: 0 };
}
