/**
 * Eval Lab camera rig — films a REAL regression on http://localhost:8080/evals
 * with cinematic zoom/pan, producing a webm for encode-evals.sh.
 *
 * Prereqs (both must already be running):
 *   make eval-server            # eval API on :8321 (talks to the EVAL db only)
 *   cd ops-console && npm run dev
 *
 * Unlike record.mjs (fixed beat clock), this rig is milestone-driven: it
 * clicks the actual "check regression" button, then waits on DOM milestones
 * (pytest chips, first persona/agent bubbles, tool call, verdict) and marks
 * their timestamps. encode-evals.sh cuts those marks into a short GIF, so a
 * multi-minute run compresses honestly — every frame is real footage.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const APP_URL = process.env.DEMO_URL ?? "http://localhost:8080/evals";
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
  const videoStart = Date.now();
  const marks = {};
  const mark = (name) => { marks[name] = (Date.now() - videoStart) / 1000; };

  await page.goto(APP_URL, { waitUntil: "networkidle" });
  await page.getByText("Current scorecards").waitFor({ timeout: 30_000 });

  // Camera: zoom toward the center of the first element matching `selector`
  // whose text includes `contains` (optional). scale 1 resets the rig.
  const cam = (selector, contains, scale, ms = 1400, fy = 0.5) =>
    page.evaluate(([selector, contains, scale, ms, fy]) => {
      const el = [...document.querySelectorAll(selector)].find(
        (n) => !contains || n.textContent?.includes(contains));
      const b = document.body;
      b.style.transition =
        `transform ${ms}ms cubic-bezier(.45,.05,.25,1), ` +
        `transform-origin ${ms}ms cubic-bezier(.45,.05,.25,1)`;
      if (!el || scale === 1) { b.style.transform = "scale(1)"; return; }
      const r = el.getBoundingClientRect();
      b.style.transformOrigin =
        `${r.x + r.width / 2}px ${r.y + r.height * fy}px`;
      b.style.transform = `scale(${scale})`;
    }, [selector, contains, scale, ms, fy]);

  // ---- beat 1: the reference grid, wide → push in on the merge headline
  mark("wide");
  await sleep(1600);
  await cam("section.clay-panel", "suite", 1.3, 1200, 0.35);
  await sleep(2100);
  await cam("body", null, 1, 900);
  await sleep(1000);

  // ---- beat 2: press the real button
  mark("click");
  await page.getByRole("button", { name: "check regression" }).first().click();
  await page.getByText("Simulation running").waitFor({ timeout: 20_000 });
  await cam("section.clay-panel", "Simulation running", 1.24, 1200, 0.4);

  // ---- beat 3: pytest layers stream by (L1 → L2)
  await page.getByText("L1+oracle+scorecard").waitFor({ timeout: 60_000 });
  mark("pytest");
  await page.getByText("L2 components").waitFor({ timeout: 240_000 });
  mark("l2");

  // ---- beat 4: the first live trial — persona ↔ real OfferAgent
  await page.getByText("nurse (persona)").first().waitFor({ timeout: 300_000 });
  mark("turns");
  await cam(".dot-grid", null, 1.3, 1300, 0.45);
  try {
    await page.getByText("accept_this_shift").first().waitFor({ timeout: 120_000 });
    mark("tool");
  } catch { /* encoder just skips this cut */ }
  try {
    await page.getByText("CONFIRMED_CORRECT").first().waitFor({ timeout: 180_000 });
    mark("verdict");
    await sleep(2200);
  } catch { await sleep(4000); }

  // ---- beat 5: browse the evidence while trials keep running behind
  await cam("body", null, 1, 900);
  await sleep(1100);
  mark("browse");
  const deck = page.getByRole("button", { name: /pass\^k/ }).first();
  await deck.scrollIntoViewIfNeeded();
  await sleep(900);
  await deck.click();
  await sleep(2600);                                    // suite popup fanned out
  await page.mouse.click(24, 405);                      // backdrop closes it
  await sleep(700);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await sleep(900);
  await page.getByRole("button", { name: "transcripts" }).first().click();
  await page.getByText("every trial, straight from the evidence").waitFor({ timeout: 20_000 });
  await sleep(600);
  await cam(".clay-panel", "LLM judge", 1.12, 1100, 0.45);
  await sleep(2800);                                    // judge quotes on screen
  await cam("body", null, 1, 800);
  await page.getByLabel("Close transcripts").click();
  await sleep(1600);
  mark("end");

  const video = page.video();
  await context.close();
  const path = await video.path();
  writeFileSync(join(OUT, "meta-evals.json"),
    JSON.stringify({ video: path, marks }, null, 2));
  await browser.close();
  console.log("recorded:", path);
  console.log("marks:", JSON.stringify(marks));
}

main().catch((err) => { console.error(err); process.exit(1); });
