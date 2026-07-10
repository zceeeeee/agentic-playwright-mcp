import fs from "node:fs";
import path from "node:path";

export type PetSkinId = "classic" | "animated-cat" | "maltese";

export interface AppearancePreferences {
  version: 1;
  skinId: PetSkinId;
}

export interface ShapeRectangle {
  x: number;
  y: number;
  width: number;
  height: number;
}

const VALID_SKIN_IDS = new Set<PetSkinId>(["classic", "animated-cat", "maltese"]);

export function validateSkinId(value: unknown): PetSkinId {
  return typeof value === "string" && VALID_SKIN_IDS.has(value as PetSkinId)
    ? value as PetSkinId
    : "classic";
}

export function getDefaultAppearancePreferences(): AppearancePreferences {
  return { version: 1, skinId: "classic" };
}

export function parseAppearancePreferences(value: unknown): AppearancePreferences {
  if (!value || typeof value !== "object") return getDefaultAppearancePreferences();
  return {
    version: 1,
    skinId: validateSkinId((value as { skinId?: unknown }).skinId)
  };
}

export function readAppearancePreferences(file: string): AppearancePreferences {
  try {
    return parseAppearancePreferences(JSON.parse(fs.readFileSync(file, "utf8")));
  } catch {
    return getDefaultAppearancePreferences();
  }
}

export function writeAppearancePreferences(
  file: string,
  preferences: AppearancePreferences
): AppearancePreferences {
  const validated = parseAppearancePreferences(preferences);
  const directory = path.dirname(file);
  const temporary = path.join(
    directory,
    `.${path.basename(file)}.${process.pid}.${Date.now()}.tmp`
  );
  fs.mkdirSync(directory, { recursive: true });
  try {
    fs.writeFileSync(temporary, JSON.stringify(validated, null, 2), "utf8");
    fs.renameSync(temporary, file);
  } finally {
    if (fs.existsSync(temporary)) fs.rmSync(temporary, { force: true });
  }
  return validated;
}

export function getCompactShapeForSkin(
  skinId: PetSkinId,
  size: number
): ShapeRectangle[] {
  if (skinId !== "classic") {
    return [{ x: 0, y: 0, width: size, height: size }];
  }

  const rects: ShapeRectangle[] = [];
  for (let y = 0; y < size; y += 4) {
    const dy = y + 2 - size / 2;
    const half = Math.sqrt(Math.max(0, (size / 2) ** 2 - dy ** 2));
    rects.push({
      x: Math.round(size / 2 - half),
      y,
      width: Math.max(1, Math.round(half * 2)),
      height: Math.min(4, size - y)
    });
  }
  return rects;
}
