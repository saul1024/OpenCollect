import http from "node:http";
import { readFile } from "node:fs/promises";
import { createReadStream, existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { Readable } from "node:stream";
import vm from "node:vm";

const PORT = Number(process.env.PORT || 3000);
const PUBLIC_DIR = join(process.cwd(), "public");
const XHS_HOST_RE = /(^|\.)xiaohongshu\.com$/;
const XHS_CDN_RE = /(^|\.)(xhscdn\.com|xiaohongshu\.com)$/;
const SAMPLE_MIN_IMAGES = 3;

const CONTENT_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml; charset=utf-8"
};

const browserHeaders = {
  "user-agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
  accept:
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
  "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
  "cache-control": "no-cache",
  pragma: "no-cache",
  referer: "https://www.xiaohongshu.com/explore"
};

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", `http://${req.headers.host}`);

    if (req.method === "POST" && url.pathname === "/api/collect") {
      return handleCollect(req, res);
    }

    if (req.method === "GET" && url.pathname === "/api/sample") {
      return handleSample(res);
    }

    if (req.method === "GET" && url.pathname === "/api/image") {
      return handleImageProxy(url, res);
    }

    if (req.method === "GET" && url.pathname === "/api/media") {
      return handleMediaProxy(req, url, res);
    }

    if (req.method === "GET") {
      return serveStatic(url.pathname, res);
    }

    sendJson(res, 405, { error: "METHOD_NOT_ALLOWED", message: "不支持的请求方法" });
  } catch (error) {
    sendJson(res, 500, {
      error: "SERVER_ERROR",
      message: error instanceof Error ? error.message : "服务异常"
    });
  }
});

server.listen(PORT, () => {
  console.log(`OpenCollect XHS PoC running at http://localhost:${PORT}`);
});

async function handleCollect(req, res) {
  const body = await readJson(req);
  const input = String(body.input || "").trim();

  if (!input) {
    return sendJson(res, 400, { error: "EMPTY_INPUT", message: "请粘贴rednote分享文本或链接" });
  }

  try {
    const result = await collectXiaohongshu(input);
    sendJson(res, 200, result);
  } catch (error) {
    sendJson(res, 422, {
      error: "PARSE_FAILED",
      message: error instanceof Error ? error.message : "解析失败"
    });
  }
}

async function handleMediaProxy(req, url, res) {
  const raw = url.searchParams.get("url");

  try {
    if (!raw) {
      throw new Error("缺少媒体地址");
    }

    const target = new URL(raw);
    if (!["http:", "https:"].includes(target.protocol) || !XHS_CDN_RE.test(target.hostname)) {
      throw new Error("不支持的媒体域名");
    }

    const headers = {
      "user-agent": browserHeaders["user-agent"],
      accept: "video/mp4,video/*,*/*;q=0.8",
      referer: "https://www.xiaohongshu.com/"
    };

    if (req.headers.range) {
      headers.range = req.headers.range;
    }

    const response = await fetch(target, { headers });
    if (!response.ok && response.status !== 206) {
      throw new Error(`媒体加载失败：${response.status}`);
    }

    const responseHeaders = {
      "content-type": response.headers.get("content-type") || "video/mp4",
      "cache-control": "public, max-age=3600",
      "accept-ranges": response.headers.get("accept-ranges") || "bytes"
    };

    for (const name of ["content-length", "content-range"]) {
      const value = response.headers.get(name);
      if (value) {
        responseHeaders[name] = value;
      }
    }

    res.writeHead(response.status, responseHeaders);

    if (!response.body) {
      return res.end();
    }

    Readable.fromWeb(response.body).pipe(res);
  } catch (error) {
    sendJson(res, 422, {
      error: "MEDIA_PROXY_FAILED",
      message: error instanceof Error ? error.message : "媒体代理失败"
    });
  }
}

async function handleSample(res) {
  try {
    const html = await fetchText("https://www.xiaohongshu.com/explore");
    const state = extractInitialState(html);
    const feeds = (state?.feed?.feeds || []).filter((item) => item?.id && item?.xsecToken);

    if (!feeds.length) {
      throw new Error("暂时没有拿到公开示例");
    }

    const sample = await findSampleNote(feeds);

    sendJson(res, 200, {
      input: sample.url,
      title: sample.title,
      imageCount: sample.imageCount,
      preferred: sample.imageCount >= SAMPLE_MIN_IMAGES ? "multi-image" : "fallback"
    });
  } catch (error) {
    sendJson(res, 422, {
      error: "SAMPLE_FAILED",
      message: error instanceof Error ? error.message : "示例获取失败"
    });
  }
}

async function findSampleNote(feeds) {
  let fallback = null;

  for (const feed of feeds.slice(0, 24)) {
    const url = buildFeedNoteUrl(feed);

    try {
      const result = await collectXiaohongshu(url);
      const sample = {
        url,
        title: result.note.title || feed.noteCard?.displayTitle || "公开示例",
        imageCount: result.note.images.length
      };

      if (!fallback || (fallback.imageCount < 2 && sample.imageCount > fallback.imageCount)) {
        fallback = sample;
      }

      if (sample.imageCount >= SAMPLE_MIN_IMAGES) {
        return sample;
      }
    } catch {
      // 公开 feed 里的部分笔记可能过期或受限，继续尝试下一条。
    }
  }

  if (fallback) return fallback;

  const first = feeds[0];
  return {
    url: buildFeedNoteUrl(first),
    title: first.noteCard?.displayTitle || "公开示例",
    imageCount: 0
  };
}

function buildFeedNoteUrl(feed) {
  return `https://www.xiaohongshu.com/explore/${feed.id}?xsec_token=${encodeURIComponent(
    feed.xsecToken
  )}&xsec_source=pc_feed`;
}

async function handleImageProxy(url, res) {
  const raw = url.searchParams.get("url");

  try {
    if (!raw) {
      throw new Error("缺少图片地址");
    }

    const target = new URL(raw);
    if (!["http:", "https:"].includes(target.protocol) || !XHS_CDN_RE.test(target.hostname)) {
      throw new Error("不支持的图片域名");
    }

    const response = await fetch(target, {
      headers: {
        "user-agent": browserHeaders["user-agent"],
        accept: "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        referer: "https://www.xiaohongshu.com/"
      }
    });

    if (!response.ok) {
      throw new Error(`图片加载失败：${response.status}`);
    }

    const contentType = response.headers.get("content-type") || "image/jpeg";
    const buffer = Buffer.from(await response.arrayBuffer());

    res.writeHead(200, {
      "content-type": contentType,
      "cache-control": "public, max-age=3600"
    });
    res.end(buffer);
  } catch (error) {
    sendJson(res, 422, {
      error: "IMAGE_PROXY_FAILED",
      message: error instanceof Error ? error.message : "图片代理失败"
    });
  }
}

async function collectXiaohongshu(input) {
  const extractedUrl = extractFirstUrl(input);

  if (!extractedUrl) {
    throw new Error("没有识别到链接，请粘贴rednote分享文本或 URL");
  }

  const finalUrl = await resolveShareUrl(extractedUrl);
  const parsedUrl = new URL(finalUrl);

  if (!XHS_HOST_RE.test(parsedUrl.hostname)) {
    throw new Error("当前 PoC 仅支持rednote链接");
  }

  const noteId = extractNoteId(finalUrl);
  if (!noteId) {
    throw new Error("没有识别到rednote笔记 ID");
  }

  const html = await fetchText(finalUrl);
  const state = extractInitialState(html);
  const detail = findNoteDetail(state, noteId);

  if (!detail) {
    const hasXsecToken = parsedUrl.searchParams.has("xsec_token");
    throw new Error(
      hasXsecToken
        ? "页面没有返回完整笔记数据，可能已失效、需登录或被平台限制访问"
        : "链接缺少 xsec_token，裸笔记链接通常拿不到完整内容。请使用rednote App 分享出来的完整链接或短链"
    );
  }

  const note = normalizeNote(detail.note, finalUrl);
  return {
    source: {
      input,
      extractedUrl,
      finalUrl
    },
    note
  };
}

function extractFirstUrl(input) {
  const match = input.match(/https?:\/\/[^\s"'<>）)]+/i);
  if (!match) return "";
  return match[0].replace(/[，。,.]+$/g, "");
}

async function resolveShareUrl(rawUrl) {
  const url = new URL(rawUrl);

  if (!XHS_HOST_RE.test(url.hostname) && !/(^|\.)xhslink\.com$/.test(url.hostname)) {
    return rawUrl;
  }

  const response = await fetch(url, {
    redirect: "follow",
    headers: browserHeaders
  });

  return response.url || rawUrl;
}

function extractNoteId(rawUrl) {
  const url = new URL(rawUrl);
  const explore = url.pathname.match(/\/explore\/([a-zA-Z0-9]+)/);
  if (explore) return explore[1];

  const discovery = url.pathname.match(/\/discovery\/item\/([a-zA-Z0-9]+)/);
  if (discovery) return discovery[1];

  return "";
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: browserHeaders
  });
  const text = await response.text();

  if (!text.includes("window.__INITIAL_STATE__") && !response.ok) {
    throw new Error(`rednote页面请求失败：${response.status}`);
  }

  return text;
}

function extractInitialState(html) {
  const match = html.match(/<script>window\.__INITIAL_STATE__=(.*?)<\/script>/s);
  if (!match) {
    throw new Error("页面中没有找到 SSR 数据");
  }

  const sandbox = { window: {} };
  vm.runInNewContext(`window.__INITIAL_STATE__=${match[1]}`, sandbox, {
    timeout: 1000,
    contextName: "xhs-initial-state"
  });

  return sandbox.window.__INITIAL_STATE__;
}

function findNoteDetail(state, noteId) {
  const map = state?.note?.noteDetailMap || {};
  const direct = map[noteId];
  if (direct?.note?.noteId || direct?.note?.title || direct?.note?.desc) {
    return direct;
  }

  return Object.values(map).find((item) => {
    const note = item?.note;
    return note?.noteId === noteId || note?.id === noteId || note?.title || note?.desc;
  });
}

function normalizeNote(note, sourceUrl) {
  const images = Array.isArray(note.imageList)
    ? note.imageList
        .map((image) => ({
          width: image.width || 0,
          height: image.height || 0,
          url: normalizeAssetUrl(
            image.urlDefault ||
              image.urlPre ||
              image.url ||
              image.infoList?.find((item) => item?.url)?.url ||
              ""
          ),
          livePhoto: Boolean(image.livePhoto)
        }))
        .filter((image) => image.url)
    : [];

  const tags = Array.isArray(note.tagList)
    ? note.tagList.map((tag) => tag.name).filter(Boolean)
    : extractHashTags(note.desc || "");
  const video = normalizeVideo(note.video, images);

  return {
    id: note.noteId || extractNoteId(sourceUrl),
    platform: "xiaohongshu",
    type: note.type || "normal",
    title: note.title || "未命名笔记",
    content: note.desc || "",
    author: {
      id: note.user?.userId || "",
      name: note.user?.nickname || note.user?.nickName || "rednote用户",
      avatar: normalizeAssetUrl(note.user?.avatar || "")
    },
    images,
    video,
    tags,
    stats: {
      likes: note.interactInfo?.likedCount || "0",
      collects: note.interactInfo?.collectedCount || "0",
      comments: note.interactInfo?.commentCount || "0",
      shares: note.interactInfo?.shareCount || "0"
    },
    createdAt: note.time ? new Date(note.time).toISOString() : "",
    updatedAt: note.lastUpdateTime ? new Date(note.lastUpdateTime).toISOString() : "",
    sourceUrl,
    collectedAt: new Date().toISOString()
  };
}

function normalizeVideo(rawVideo, images) {
  if (!rawVideo) return null;

  const mediaV2 = parseJson(rawVideo.mediaV2);
  const streams = [
    ...extractVideoStreams(rawVideo.media?.stream),
    ...extractVideoStreams(mediaV2?.stream)
  ];
  const selected =
    streams.find((stream) => Boolean(stream.defaultStream || stream.default_stream)) ||
    streams.find((stream) => getVideoStreamUrl(stream)) ||
    null;
  const url = selected ? normalizeAssetUrl(getVideoStreamUrl(selected)) : "";

  if (!url) return null;

  const rawDuration =
    selected.duration ||
    selected.videoDuration ||
    selected.video_duration ||
    rawVideo.media?.video?.duration ||
    mediaV2?.video?.duration ||
    rawVideo.capa?.duration ||
    0;

  return {
    url,
    poster: images[0]?.url || "",
    width: selected.width || mediaV2?.video?.width || 0,
    height: selected.height || mediaV2?.video?.height || 0,
    duration: rawDuration > 1000 ? Math.round(rawDuration / 1000) : rawDuration,
    format: selected.format || "mp4",
    codec: selected.videoCodec || selected.video_codec || "h264"
  };
}

function extractVideoStreams(streamMap) {
  if (!streamMap) return [];
  return ["h264", "h265", "h266", "av1"].flatMap((name) =>
    Array.isArray(streamMap[name]) ? streamMap[name] : []
  );
}

function getVideoStreamUrl(stream) {
  return (
    stream.masterUrl ||
    stream.master_url ||
    stream.url ||
    stream.backupUrls?.[0] ||
    stream.backup_urls?.[0] ||
    ""
  );
}

function parseJson(value) {
  if (!value || typeof value !== "string") return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function normalizeAssetUrl(url) {
  if (!url) return "";
  if (url.startsWith("//")) return `https:${url}`;
  if (url.startsWith("http://")) return `https://${url.slice("http://".length)}`;
  return url;
}

function extractHashTags(text) {
  const tags = [];
  const re = /#([^#\[\]\s]+)(?:\[话题\])?#/g;
  let match;
  while ((match = re.exec(text))) {
    tags.push(match[1]);
  }
  return tags;
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

async function serveStatic(pathname, res) {
  const safePath = pathname === "/" ? "/index.html" : pathname;
  const filePath = normalize(join(PUBLIC_DIR, safePath));

  if (!filePath.startsWith(PUBLIC_DIR) || !existsSync(filePath)) {
    sendJson(res, 404, { error: "NOT_FOUND", message: "页面不存在" });
    return;
  }

  const type = CONTENT_TYPES[extname(filePath)] || "application/octet-stream";
  res.writeHead(200, { "content-type": type });
  createReadStream(filePath).pipe(res);
}

function sendJson(res, status, payload) {
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8"
  });
  res.end(JSON.stringify(payload));
}
