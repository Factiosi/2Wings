/**
 * Generate raster assets from SVG sources in assets/icons/.
 * Usage: cd tools && npm install && node generate_icons.mjs
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { Resvg } from "@resvg/resvg-js";
import pngToIco from "png-to-ico";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const ICONS = join(ROOT, "assets", "icons");

function rasterize(svgPath, size) {
  const svg = readFileSync(svgPath, "utf8");
  const resvg = new Resvg(svg, {
    fitTo: { mode: "width", value: size },
  });
  return resvg.render().asPng();
}

async function writePng(svgRel, pngRel, size) {
  const png = rasterize(join(ICONS, svgRel), size);
  const out = join(ICONS, pngRel);
  writeFileSync(out, png);
  console.log(`OK ${pngRel}`);
}

async function writeIco(svgRel, icoRel) {
  const sizes = [16, 32, 48, 64, 128, 256];
  const pngs = sizes.map((size) => rasterize(join(ICONS, svgRel), size));
  const ico = await pngToIco(pngs);
  writeFileSync(join(ICONS, icoRel), ico);
  console.log(`OK ${icoRel}`);
}

await writePng("tray-active.svg", "tray-active.png", 64);
await writePng("tray-idle.svg", "tray-idle.png", 64);
await writeIco("app.svg", "app.ico");
await writePng("mark-dark.svg", "mark-dark.png", 160);

// Tray menu: Lucide icons in the text colours of the native dark and light menus.
mkdirSync(join(ICONS, "menu"), { recursive: true });
for (const name of ["app-window", "play", "square", "power"]) {
  const source = readFileSync(join(ICONS, "lucide", `${name}.svg`), "utf8");
  for (const [theme, color] of [["dark", "#ffffff"], ["light", "#1a1a1a"]]) {
    const resvg = new Resvg(source.replaceAll("currentColor", color), { fitTo: { mode: "width", value: 32 } });
    writeFileSync(join(ICONS, "menu", `${name}-${theme}.png`), resvg.render().asPng());
    console.log(`OK menu/${name}-${theme}.png`);
  }
}
