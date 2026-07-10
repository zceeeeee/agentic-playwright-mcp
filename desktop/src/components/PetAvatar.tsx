import { useEffect, useRef, useState } from "react";
import { getAgentStateLabel, PET_SKINS } from "../skins/skinRegistry";
import type { AgentVisualState, PetSkinId } from "../types";

interface PetAvatarProps {
  skinId: PetSkinId;
  state: AgentVisualState;
  variant: "compact" | "mini" | "preview";
  className?: string;
}

export function PetAvatar({ skinId, state, variant, className = "" }: PetAvatarProps) {
  const skin = PET_SKINS[skinId] ?? PET_SKINS.classic;
  const [isHovered, setIsHovered] = useState(false);
  const [failedSources, setFailedSources] = useState<Set<string>>(() => new Set());
  const [forceClassic, setForceClassic] = useState(false);
  const warned = useRef(new Set<string>());

  useEffect(() => {
    setFailedSources(new Set());
    setForceClassic(false);
    setIsHovered(false);
  }, [skinId]);

  const renderClassic = skin.renderer === "classic-css" || forceClassic;
  if (renderClassic) {
    return (
      <span
        className={`pet-avatar classic-pet skin-${skin.id} state-${state} pet-avatar-${variant} ${className}`}
        aria-label={getAgentStateLabel(state)}
      >
        <span className="pet-core" />
        <span className="pet-ring" />
      </span>
    );
  }

  const defaultSrc = skin.stateAssets?.[state] ?? skin.fallbackAsset ?? "";
  const hoverSrc = variant === "compact" && state === "idle" && isHovered
    ? skin.interactionAssets?.hover ?? defaultSrc
    : defaultSrc;
  const src = failedSources.has(hoverSrc) ? skin.fallbackAsset ?? "" : hoverSrc;

  function handleImageError() {
    if (import.meta.env.DEV && !warned.current.has(src)) {
      warned.current.add(src);
      console.warn(`Pet skin asset failed to load: ${src}`);
    }
    if (!src || src === skin.fallbackAsset) {
      setForceClassic(true);
      return;
    }
    setFailedSources((current) => new Set(current).add(src));
  }

  return (
    <span
      className={`pet-avatar animated-pet skin-${skin.id} state-${state} pet-avatar-${variant} ${className}`}
      aria-label={getAgentStateLabel(state)}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <img
        key={`${skin.id}:${state}:${isHovered ? "hover" : "default"}:${src}`}
        src={src}
        alt=""
        draggable={false}
        className="animated-pet-image"
        onError={handleImageError}
      />
      {state === "waiting_confirmation" ? (
        <span className="confirmation-glow" aria-hidden="true" />
      ) : null}
    </span>
  );
}
