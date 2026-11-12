// Trusted local-only layout inspection. Never accepts model code or a remote URL.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";

const [rootArg, sdk, chrome, reportPath, snapshots] = process.argv.slice(2);
const root = fs.realpathSync(rootArg);
const requireSdk = createRequire(path.join(sdk, "node_modules/hyperframes/package.json"));
const puppeteer = requireSdk("puppeteer-core");
const types = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".woff2": "font/woff2", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".mp4": "video/mp4", ".wav": "audio/wav" };
const server = http.createServer((request, response) => {
  try {
    if (!["GET", "HEAD"].includes(request.method)) throw new Error("read only");
    const url = new URL(request.url, "http://127.0.0.1");
    const name = decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname);
    if (!/^\/(index\.html|assets\/[a-zA-Z0-9_.\/-]+)$/.test(name)) throw new Error("source is not an asset");
    const target = path.resolve(root, "." + name);
    if (!target.startsWith(root + path.sep) || fs.realpathSync(target) !== target) throw new Error("asset boundary");
    const stat = fs.statSync(target);
    if (!stat.isFile()) throw new Error("not a regular asset");
    let first = 0, last = stat.size - 1;
    const range = request.headers.range;
    if (range) {
      const match = /^bytes=(\d+)-(\d*)$/.exec(range);
      if (!match) throw new Error("invalid range");
      first = Number(match[1]); last = match[2] ? Number(match[2]) : last;
      if (!Number.isSafeInteger(first) || !Number.isSafeInteger(last) || first < 0 || last < first || last >= stat.size) throw new Error("invalid range");
    }
    response.writeHead(range ? 206 : 200, { "Content-Type": types[path.extname(target)] ?? "application/octet-stream", "Content-Length": last - first + 1, "Accept-Ranges": "bytes", ...(range ? { "Content-Range": `bytes ${first}-${last}/${stat.size}` } : {}) });
    if (request.method === "HEAD") response.end();
    else fs.createReadStream(target, { start: first, end: last }).pipe(response);
  } catch { response.writeHead(404); response.end(); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-background-networking", "--disable-sync", "--disable-extensions", "--no-first-run"] });
  const page = await browser.newPage();
  const errors = [], blocked = [];
  page.on("pageerror", error => errors.push(String(error).slice(0, 500)));
  await page.setRequestInterception(true);
  page.on("request", request => {
    const url = request.url();
    if (url.startsWith(origin + "/") || url.startsWith("data:") || url.startsWith("blob:")) request.continue();
    else { blocked.push(url.slice(0, 300)); request.abort(); }
  });
  await page.goto(origin + "/index.html", { waitUntil: "networkidle0", timeout: 30000 });
  await page.evaluate(() => window.__stationReady);
  const canvas = await page.evaluate(() => { const root = document.querySelector('[data-composition-id="main"]'); return { width: Number(root.dataset.width), height: Number(root.dataset.height) }; });
  await page.setViewport({ ...canvas, deviceScaleFactor: 1 });
  const result = await page.evaluate(async () => {
    await document.fonts.ready;
    let presenter;
    const frame = document.querySelector('.presenter-frame');
    if (frame) {
      const stage = document.querySelector('.story-stage').getBoundingClientRect();
      const box = frame.getBoundingClientRect();
      const canvas = document.querySelector('#main').getBoundingClientRect();
      const clips = [...frame.querySelectorAll('video')];
      let end = 0, contiguous = true;
      for (const clip of clips) {
        if (Math.abs(Number(clip.dataset.start) - end) > 1e-6 || !(Number(clip.dataset.duration) > 0)) contiguous = false;
        end += Number(clip.dataset.duration);
      }
      if (Math.abs(end - Number(document.querySelector('#main').dataset.duration)) > 1e-6) contiguous = false;
      presenter = { reserved: stage.right <= box.left + 1 || stage.bottom <= box.top + 1,
        bounded: box.left >= 0 && box.top >= 0 && box.right <= canvas.right + 1 && box.bottom <= canvas.bottom + 1,
        muted: clips.length > 0 && clips.every(video => video.muted && video.dataset.volume === '0'),
        contiguous, clip_count: clips.length,
        width: box.width, height: box.height };
    }
    return { ...(presenter ? { presenter } : {}), layout: window.__stationLayout, fonts: [...document.fonts].filter(f => f.status !== "unloaded").map(f => ({ family: f.family, weight: f.weight, status: f.status })), text: [...document.querySelectorAll('.body,footer')].slice(0, 4).map(node => ({ content: node.textContent, font: getComputedStyle(node).font, letterSpacing: getComputedStyle(node).letterSpacing, width: node.getBoundingClientRect().width, scrollWidth: node.scrollWidth })) };
  });
  if (errors.length || blocked.length || result.fonts.some(f => f.status === "error") || !result.layout?.length || result.layout.some(item => item.overflow) || (result.presenter && (!result.presenter.reserved || !result.presenter.bounded || !result.presenter.muted || !result.presenter.contiguous))) throw new Error(JSON.stringify({ reason: "Composition quality check failed", errors, blocked, ...result }));
  if (snapshots) {
    fs.mkdirSync(snapshots, { recursive: true });
    const times = await page.evaluate(() => [...document.querySelectorAll('.scene')].map(node => Number(node.dataset.sceneStart) + Math.min(1, Number(node.dataset.sceneDuration) / 2)));
    for (let i = 0; i < times.length; i++) {
      await page.evaluate(t => {
        for (const node of document.querySelectorAll('.clip')) node.style.visibility = t >= Number(node.dataset.start) && t < Number(node.dataset.start) + Number(node.dataset.duration) ? "visible" : "hidden";
        window.__timelines.main.pause(t);
      }, times[i]);
      await page.screenshot({ path: path.join(snapshots, `scene-${i}.png`) });
    }
  }
  fs.writeFileSync(reportPath, JSON.stringify({ verified: true, ...canvas, ...result, errors, blocked }));
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
