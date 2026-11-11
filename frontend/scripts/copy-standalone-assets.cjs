/**
 * After `next build` with output: "standalone", copy static assets into standalone tree
 * so `node server.js` can serve them. See Next.js standalone deployment.
 */
const fs = require("fs");
const path = require("path");

const frontendRoot = path.join(__dirname, "..");
const nextDir = path.join(frontendRoot, ".next");
const standaloneDir = path.join(nextDir, "standalone");
const serverJs = path.join(standaloneDir, "server.js");

function cpDir(src, dest) {
  if (!fs.existsSync(src)) {
    throw new Error(`copy-standalone-assets: missing ${src}`);
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.cpSync(src, dest, { recursive: true });
}

if (!fs.existsSync(serverJs)) {
  console.warn(
    "[copy-standalone-assets] skip: .next/standalone/server.js not found (build standalone first)."
  );
  process.exit(0);
}

const staticSrc = path.join(nextDir, "static");
const staticDest = path.join(standaloneDir, ".next", "static");
if (fs.existsSync(staticSrc)) {
  console.log("[copy-standalone-assets] copy", staticSrc, "->", staticDest);
  fs.rmSync(staticDest, { recursive: true, force: true });
  cpDir(staticSrc, staticDest);
}

const publicSrc = path.join(frontendRoot, "public");
const publicDest = path.join(standaloneDir, "public");
if (fs.existsSync(publicSrc)) {
  console.log("[copy-standalone-assets] copy", publicSrc, "->", publicDest);
  fs.rmSync(publicDest, { recursive: true, force: true });
  cpDir(publicSrc, publicDest);
}

console.log("[copy-standalone-assets] done");
