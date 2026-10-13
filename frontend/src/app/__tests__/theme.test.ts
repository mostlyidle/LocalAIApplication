import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/app/globals.css", "utf8");

function luminance(hex: string) {
  return [0.2126, 0.7152, 0.0722].reduce((sum, weight, index) => {
    const channel = parseInt(hex.slice(1 + index * 2, 3 + index * 2), 16) / 255;
    return sum + weight * (channel <= 0.04045
      ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  }, 0);
}

function contrast(foreground: string, background: string) {
  const [low, high] = [luminance(foreground), luminance(background)].sort((a, b) => a - b);
  return (high + 0.05) / (low + 0.05);
}

describe.each([":root", ".dark"])("%s theme", (theme) => {
  const section = css.split(`${theme} {`)[1].split("}")[0];
  const colors = Object.fromEntries(
    [...section.matchAll(/--([\w-]+): (#[0-9a-f]{6});/g)].map((match) => [match[1], match[2]]),
  );

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
