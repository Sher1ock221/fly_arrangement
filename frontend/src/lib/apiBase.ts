/**
 * 前端请求后端的 base URL。
 * 优先级：NEXT_PUBLIC_API_BASE_URL > NEXT_PUBLIC_API_URL > 当前页同机 18000 > localhost:18000
 * 在浏览器中访问时，若未配置环境变量，会使用当前页面所在主机 + 端口 18000，便于局域网其他电脑访问。
 */
export function getApiBase(): string {
  const fromEnv =
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "";
  if (fromEnv && typeof fromEnv === "string" && fromEnv.trim()) {
    return fromEnv.trim().replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:18000`;
  }
  return "http://localhost:18000";
}
