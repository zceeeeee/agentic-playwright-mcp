import { Check } from "lucide-react";
import { PET_SKINS } from "../skins/skinRegistry";
import { useAppearanceStore } from "../stores/appearanceStore";
import type { PetSkinId } from "../types";
import { PetAvatar } from "./PetAvatar";

const skinIds: PetSkinId[] = ["classic", "animated-cat", "maltese"];

export function AppearanceSettings() {
  const skinId = useAppearanceStore((state) => state.skinId);
  const saving = useAppearanceStore((state) => state.saving);
  const error = useAppearanceStore((state) => state.error);
  const lastSavedAt = useAppearanceStore((state) => state.lastSavedAt);
  const setSkinId = useAppearanceStore((state) => state.setSkinId);

  return (
    <div className="page-view appearance-view">
      <header className="page-heading">
        <h1>外观与皮肤</h1>
        <p>选择桌面宠物的外观，修改会立即同步到所有窗口。</p>
      </header>
      <div className="skin-grid" role="radiogroup" aria-label="宠物皮肤">
        {skinIds.map((id) => {
          const skin = PET_SKINS[id];
          const selected = skinId === id;
          return (
            <button
              type="button"
              role="radio"
              aria-checked={selected}
              className={`skin-card ${selected ? "selected" : ""}`}
              key={id}
              disabled={saving}
              onClick={() => void setSkinId(id)}
            >
              <span className="skin-preview">
                <PetAvatar skinId={id} state="idle" variant="preview" />
              </span>
              <span className="skin-card-copy">
                <strong>{skin.name}</strong>
                <span>{skin.description}</span>
                {skin.attribution ? (
                  <small>素材来源：{skin.attribution}</small>
                ) : null}
              </span>
              {selected ? (
                <span className="skin-selected"><Check size={14} />当前使用</span>
              ) : null}
            </button>
          );
        })}
      </div>
      <p className={`appearance-save-status ${error ? "error" : ""}`} role="status">
        {saving ? "正在保存……" : error ? `${error}，请选择皮肤重新尝试。` : lastSavedAt ? "已保存到本机" : "设置保存在本机，应用重启后会自动恢复。"}
      </p>
    </div>
  );
}
