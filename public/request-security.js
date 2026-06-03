export function withRequestSecurity(options = {}, cookieString = globalThis.document?.cookie || "") {
  const next = { ...options };
  const method = String(next.method || "GET").toUpperCase();
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrfToken = readCookie("opencollect_csrf", cookieString);
    if (csrfToken) {
      const headers = new Headers(next.headers || {});
      headers.set("X-CSRF-Token", csrfToken);
      next.headers = headers;
    }
  }
  return next;
}

export function readCookie(name, cookieString = globalThis.document?.cookie || "") {
  const prefix = `${name}=`;
  return cookieString
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(prefix))
    ?.slice(prefix.length) || "";
}
