#!/usr/bin/env node
// Screenshots and video of a web UI (a Vite dev server, a bench page, or a running WebView2 app over CDP) for devlog media.
//
//   node capture_web.mjs --url http://127.0.0.1:5173/ --out media/home.png
//   node capture_web.mjs --url http://127.0.0.1:5173/bench/app.html --video media/flow.webm --steps steps.json
//   node capture_web.mjs --cdp http://127.0.0.1:9222 --out media/app.png          (attach to a running app)
//
// --steps is a JSON array run in order, e.g.
//   [{"click":"text=Generate"},{"fill":["#prompt","a rusty oil drum"]},{"press":"Enter"},
//    {"waitFor":".option-tile"},{"wait":1500},{"shot":"after-generate.png"},{"wheel":[700,500,900]}]
// "shot" files are written next to --out/--video. Other flags: --width 1280 --height 800 --wait <ms before the
// final shot> --full (full-page shot) --pw <node_modules dir that has playwright-core> --browser <exe path>.
//
// Uses playwright-core from a project's node_modules (Forge/ui has it) and the installed Microsoft Edge, so it
// needs no browser download. Video needs Playwright's ffmpeg once: node <pw>/playwright-core/cli.js install ffmpeg
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i < 0 ? dflt : args[i + 1];
};
const has = (name) => args.includes(`--${name}`);
const workspace = process.env.GAMEDEV_ROOT || "D:\\Game Dev";

function findPlaywright() {
  const cands = [opt("pw")].filter(Boolean);
  for (const d of fs.readdirSync(workspace, { withFileTypes: true })) {
    if (!d.isDirectory()) continue;
    cands.push(path.join(workspace, d.name, "ui", "node_modules"), path.join(workspace, d.name, "node_modules"));
  }
  for (const nm of cands) {
    if (fs.existsSync(path.join(nm, "playwright-core"))) return createRequire(path.join(nm, "noop.js"))("playwright-core");
    if (fs.existsSync(path.join(nm, "playwright"))) return createRequire(path.join(nm, "noop.js"))("playwright");
  }
  throw new Error("playwright-core not found; pass --pw <node_modules dir> (Forge: run `npm run setup` in D:\\Game Dev\\Forge)");
}

const { chromium } = findPlaywright();
const out = opt("out");
const video = opt("video");
if (!out && !video) throw new Error("pass --out <png> and/or --video <webm|mp4>");
const outDir = path.dirname(path.resolve(out || video));
fs.mkdirSync(outDir, { recursive: true });
const viewport = { width: +opt("width", 1280), height: +opt("height", 800) };

let browser, context, page;
if (opt("cdp")) {
  browser = await chromium.connectOverCDP(opt("cdp"));
  context = browser.contexts()[0];
  page = context.pages()[0];
} else {
  const exe = opt("browser") || process.env.CHROMIUM_PATH;
  const launch = { headless: !has("headed"), args: ["--ignore-gpu-blocklist", "--enable-unsafe-webgpu"] };
  try {
    browser = await chromium.launch(exe ? { ...launch, executablePath: exe } : { ...launch, channel: "msedge" });
  } catch {
    browser = await chromium.launch(launch);
  }
  const tmpVideo = video ? fs.mkdtempSync(path.join(outDir, ".rec-")) : null;
  context = await browser.newContext({ viewport, deviceScaleFactor: 1, ...(video ? { recordVideo: { dir: tmpVideo, size: viewport } } : {}) });
  context._tmpVideo = tmpVideo;
  page = await context.newPage();
}
page.on("console", (m) => m.type() === "error" && console.error("page:", m.text()));
if (opt("url")) await page.goto(opt("url"), { waitUntil: "networkidle" }).catch(() => page.waitForLoadState("load"));

const steps = opt("steps") ? JSON.parse(fs.readFileSync(opt("steps"), "utf8")) : [];
for (const s of steps) {
  if (s.goto) await page.goto(s.goto, { waitUntil: "networkidle" });
  if (s.click) await page.click(s.click);
  if (s.fill) await page.fill(s.fill[0], s.fill[1]);
  if (s.press) await page.keyboard.press(s.press);
  if (s.type) await page.keyboard.type(s.type, { delay: 40 });
  if (s.hover) await page.hover(s.hover);
  if (s.wheel) {  // [x, y, deltaY]: scroll whatever is under the point, iframes included
    await page.mouse.move(s.wheel[0], s.wheel[1]);
    for (let left = s.wheel[2]; Math.abs(left) > 0; left -= Math.sign(left) * Math.min(Math.abs(left), 120)) {
      await page.mouse.wheel(0, Math.sign(left) * Math.min(Math.abs(left), 120));
      await page.waitForTimeout(30);
    }
  }
  if (s.waitFor) await page.waitForSelector(s.waitFor, { timeout: s.timeout || 120_000 });
  if (s.eval) await page.evaluate(s.eval);
  if (s.wait) await page.waitForTimeout(s.wait);
  if (s.shot) {
    await page.screenshot({ path: path.join(outDir, s.shot), fullPage: !!s.full });
    console.log(path.join(outDir, s.shot));
  }
}
if (has("full")) {
  // Full-page shots include content below the fold, which lazy images never load on their own.
  await page.evaluate(() => document.querySelectorAll("img[loading=lazy]").forEach((i) => (i.loading = "eager")));
  await page.waitForFunction(() => [...document.images].every((i) => i.complete), null, { timeout: 15_000 }).catch(() => {});
}
await page.waitForTimeout(+opt("wait", 500));
if (out) {
  await page.screenshot({ path: path.resolve(out), fullPage: has("full") });
  console.log(path.resolve(out));
}
if (video && context._tmpVideo) {
  const v = page.video();
  await context.close();
  await v.saveAs(path.resolve(video));
  fs.rmSync(context._tmpVideo, { recursive: true, force: true });
  console.log(path.resolve(video));
}
await browser.close();
