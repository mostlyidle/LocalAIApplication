import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const tokens = readFileSync("src/app/tokens.css", "utf8");

function luminance(color: string | undefined) {
  if (!color) throw new Error("Missing color token used by contrast check");
  const match = color.match(/oklch\((\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)/);
  if (!match) throw new Error(`Unsupported color token: ${color}`);
  const [, lightness, chroma, hue] = match;
  const L = Number(lightness) / 100;
  const C = Number(chroma);
  const angle = Number(hue) * Math.PI / 180;
  const a = C * Math.cos(angle);
  const b = C * Math.sin(angle);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  const channels = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
  ].map((channel) => {
    const bounded = Math.min(1, Math.max(0, channel));
    return (bounded <= 0.0031308 ? 12.92 * bounded : 1.055 * bounded ** (1 / 2.4) - 0.055) * 255;
  }).map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(foreground: string | undefined, background: string | undefined) {
  const [low, high] = [luminance(foreground), luminance(background)].sort((a, b) => a - b);
  return (high + 0.05) / (low + 0.05);
}

describe.each([":root", ".dark"])("%s theme", (theme) => {
  const section = theme === ":root"
    ? tokens.split(":root {")[1].split("}")[0]
    : tokens.split(".dark {")[1].split("}")[0];
  const colors = Object.fromEntries(
    [...section.matchAll(/--([\w-]+): (oklch\([^;]+\));/g)].map((match) => [match[1], match[2]]),
  );
  const aliases: Record<string, string> = {
    background: "color-paper",
    foreground: "color-ink",
    "card-foreground": "color-ink",
    card: "color-paper-2",
    "muted-foreground": "color-muted",
    muted: "color-paper-2",
    "primary-foreground": "color-accent-ink",
    primary: "color-accent",
    "destructive-foreground": "color-error-ink",
    destructive: "color-error",
    "sidebar-foreground": "color-ink",
    sidebar: "color-paper-2",
    "sidebar-accent-foreground": "color-ink",
    "sidebar-accent": "color-paper-3",
    input: "color-rule-2",
  };
  for (const [name, token] of Object.entries(aliases)) colors[name] = colors[token];

  it("keeps normal text and colored labels at AA contrast", () => {
    const pairs = [
      ["foreground", "background"], ["card-foreground", "card"],
      ["muted-foreground", "background"], ["muted-foreground", "card"],
      ["muted-foreground", "muted"], ["primary-foreground", "primary"],
      ["destructive-foreground", "destructive"], ["destructive", "background"],
      ["sidebar-foreground", "sidebar"], ["sidebar-accent-foreground", "sidebar-accent"],
      ...["violet", "peach", "mint", "sky", "rose"].map((tone) => [`${tone}-ink`, `${tone}-soft`]),
    ];
    for (const [foreground, background] of pairs) {
      expect(contrast(colors[foreground], colors[background]), `${foreground} on ${background}`)
        .toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps input boundaries visible against surfaces", () => {
    for (const background of ["background", "card"]) {
      expect(contrast(colors.input, colors[background]), `input on ${background}`)
        .toBeGreaterThanOrEqual(3);
    }
  });
});
