/**
 * Generate raster assets. app.ico and updater.ico are drawn by hand and not generated.
 * Usage: cd tools && npm install && node generate_icons.mjs
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { Resvg } from "@resvg/resvg-js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BRAND = join(ROOT, "assets", "brand");
const ICONS = join(ROOT, "assets", "icons");

function writePng(svg, pngRel, size) {
  const png = new Resvg(svg, { fitTo: { mode: "width", value: size } }).render().asPng();
  writeFileSync(join(ICONS, pngRel), png);
  console.log(`OK ${pngRel}`);
}

writePng(readFileSync(join(BRAND, "2wings.svg"), "utf8"), "tray.png", 64);
writePng(readFileSync(join(BRAND, "2wings-updater.svg"), "utf8"), "updater-mark.png", 160);

// Tray menu: Lucide icons in the text colours of the native dark and light menus.
mkdirSync(join(ICONS, "menu"), { recursive: true });
for (const name of ["app-window", "play", "square", "power"]) {
  const source = readFileSync(join(ICONS, "lucide", `${name}.svg`), "utf8");
  for (const [theme, color] of [["dark", "#ffffff"], ["light", "#1a1a1a"]]) {
    writePng(source.replaceAll("currentColor", color), join("menu", `${name}-${theme}.png`), 32);
  }
}
