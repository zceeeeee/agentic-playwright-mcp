import type { AgentVisualState, PetSkinId } from "../types";

export interface PetSkinDefinition {
  id: PetSkinId;
  name: string;
  description: string;
  renderer: "classic-css" | "animated-gif";
  stateAssets?: Partial<Record<AgentVisualState, string>>;
  interactionAssets?: { hover?: string };
  fallbackAsset?: string;
  attribution?: string;
}

export const AGENT_STATE_LABELS: Record<AgentVisualState, string> = {
  idle: "空闲",
  running: "正在执行",
  waiting_confirmation: "等待确认",
  success: "已完成",
  error: "执行失败"
};

export const PET_SKINS: Record<PetSkinId, PetSkinDefinition> = {
  classic: {
    id: "classic",
    name: "经典模式",
    description: "使用颜色和动画表达 Agent 当前状态。",
    renderer: "classic-css"
  },
  "animated-cat": {
    id: "animated-cat",
    name: "月薪猫",
    description: "使用月薪猫动画表达 Agent 当前状态。",
    renderer: "animated-gif",
    stateAssets: {
      idle: "./skins/animated-cat/idle.gif",
      running: "./skins/animated-cat/running.gif",
      waiting_confirmation: "./skins/animated-cat/review.gif",
      success: "./skins/animated-cat/jumping.gif",
      error: "./skins/animated-cat/failed.gif"
    },
    interactionAssets: {
      hover: "./skins/animated-cat/waving.gif"
    },
    fallbackAsset: "./skins/animated-cat/idle.gif",
    attribution: "Lumi-arta/desktop_cat"
  },
  maltese: {
    id: "maltese",
    name: "线条小狗",
    description: "使用线条小狗动画表达 Agent 当前状态。",
    renderer: "animated-gif",
    stateAssets: {
      idle: "./skins/maltese/idle.gif",
      running: "./skins/maltese/running.gif",
      waiting_confirmation: "./skins/maltese/review.gif",
      success: "./skins/maltese/jumping.gif",
      error: "./skins/maltese/failed.gif"
    },
    interactionAssets: {
      hover: "./skins/maltese/waving.gif"
    },
    fallbackAsset: "./skins/maltese/idle.gif",
    attribution: "https://www.sigstick.com/pack/eUPOUOsTgo9hY5ynsVjN-%E5%B0%8F%E5%A5%B6%E7%8B%97"
  }
};

export function getAgentStateLabel(state: AgentVisualState): string {
  return AGENT_STATE_LABELS[state];
}
