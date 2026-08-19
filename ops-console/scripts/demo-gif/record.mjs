/**
 * Camera-rig recorder — films the ops console's built-in demo story with
 * cinematic zoom/pan, producing a webm for encode.sh to turn into the README
 * hero GIF. Fully regenerable: `node scripts/demo-gif/record.mjs` while
 * `npm run dev` serves http://localhost:8080.
 *
 * The "camera" is a CSS transform on <body>: scale + transform-origin eased
 * between beats of the scripted demo (2.2s per beat, accept outcome). Zoom
 * targets are fractions of the story-graph panel, mapped from the canvas
 * geometry in src/lib/ops-story.ts (GEO columns / lanes).
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const APP_URL = process.env.DEMO_URL ?? "http://localhost:8080";
const HERE = fileURLToPath(new URL(".", import.meta.url));
const OUT = join(HERE, "raw");
const W = 1440, H = 810;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({
    viewport: { width: W, height: H },
    recordVideo: { dir: OUT, size: { width: W, height: H } },
  });
  const page = await context.newPage();
  const videoStart = Date.now(); // recording begins with the page
  await page.goto(APP_URL, { waitUntil: "networkidle" });

  // Camera: zoom to a point expressed as fractions of the story panel.
  const cam = (fx, fy, scale, ms = 1500) =>
    page.evaluate(([fx, fy, scale, ms]) => {
      const panel = document.querySelector("section");
      if (!panel) return;
      const r = panel.getBoundingClientRect();
      const b = document.body;
      b.style.transition =
        `transform ${ms}ms cubic-bezier(.45,.05,.25,1), ` +
        `transform-origin ${ms}ms cubic-bezier(.45,.05,.25,1)`;
      b.style.transformOrigin =
        `${r.x + r.width * fx}px ${r.y + r.height * fy}px`;
      b.style.transform = `scale(${scale})`;
    }, [fx, fy, scale, ms]);

  // Switch to the scripted demo and settle on beat 0.
  await page.getByRole("button", { name: "demo", exact: true }).click();
  await sleep(900);

  await page.getByRole("button", { name: "play" }).click();

  // Beat clock: 2.2s per beat (see ops-console/src/routes/index.tsx).
  // Fractions map GEO columns (callout 100 / router 300 / prospects 520 /
  // pips 668+ / outcome ~1150 of canvas 1320) onto the panel rect.
  const timeline = [
    [300, () => cam(0.45, 0.45, 1.0, 600)],   // settle wide
    [2400, () => cam(0.10, 0.45, 1.45)],      // callout: push in on Maria
    [4700, () => cam(0.30, 0.45, 1.30)],      // scored: router + prospect column
    [6900, () => cam(0.52, 0.40, 1.35)],      // rung 1: SMS pips fire
    [9100, () => cam(0.58, 0.62, 1.33)],      // rung 2: drift to the declined lane
    [11300, () => cam(0.72, 0.28, 1.42)],     // rung 3: live call pip, top lane
    [13600, () => cam(0.55, 0.45, 1.03)],     // pull wide: lock + stand-downs
    [16200, () => cam(0.50, 0.50, 1.0, 1200)],
  ];
  const t0 = Date.now();
  for (const [at, move] of timeline) {
    await sleep(Math.max(0, at - (Date.now() - t0)));
    await move();
  }
  await sleep(2600); // hold the final wide frame

  const end = Date.now();
  const video = page.video();
  await context.close();
  const path = await video.path();
  writeFileSync(join(OUT, "meta.json"), JSON.stringify({
    video: path,
    // encode.sh trims the setup (page load + mode switch), keeping a small
    // pre-roll of the wide frame before the play click.
    startOffsetSec: Math.max(0, (t0 - videoStart) / 1000 - 0.4),
    durationSec: (end - t0) / 1000 + 0.4,
  }, null, 2));
  await browser.close();
  console.log("recorded:", path);
}

main().catch((err) => { console.error(err); process.exit(1); });
