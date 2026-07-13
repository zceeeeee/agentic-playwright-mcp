export interface SkillInfo {
  id: string;
  name: string;
  type: string;
  description: string;
  triggers: string[];
  version: string;
  platform: string;
  action: string;
  examples: string[];
  params: Record<string, { required?: boolean; description?: string }>;
  command_template: string;
}

export interface SkillWebsiteGroup {
  id: string;
  label: string;
  skills: SkillInfo[];
}

const PLATFORM_LABELS: Record<string, string> = {
  amazon: "Amazon",
  baidu: "百度",
  bilibili: "哔哩哔哩",
  bing: "Bing",
  doubao: "豆包",
  douyin: "抖音",
  csnd: "CSDN",
  csdn: "CSDN",
  github: "GitHub",
  gmail: "Gmail",
  google: "Google",
  outlook: "Outlook",
  taobao: "淘宝",
  wechat: "微信",
  weibo: "微博",
  wps: "WPS",
  xiaohongshu: "小红书",
  youtube: "YouTube",
  zhihu: "知乎"
};

export function platformLabel(platform: string): string {
  const normalized = platform.trim().toLowerCase();
  return PLATFORM_LABELS[normalized] || platform || "其他网站";
}

export function filterAndGroupSkills(
  skills: SkillInfo[],
  query: string
): SkillWebsiteGroup[] {
  const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
  const filtered = normalizedQuery
    ? skills.filter((skill) => [
        skill.name,
        skill.description,
        skill.platform,
        platformLabel(skill.platform),
        skill.command_template,
        ...skill.triggers
      ].some((value) => value.toLocaleLowerCase("zh-CN").includes(normalizedQuery)))
    : skills;

  const groups = new Map<string, SkillInfo[]>();
  for (const skill of filtered) {
    const platform = skill.platform.trim().toLowerCase() || "other";
    groups.set(platform, [...(groups.get(platform) || []), skill]);
  }
  return Array.from(groups, ([id, entries]) => ({
    id,
    label: platformLabel(id),
    skills: entries.sort((left, right) => left.name.localeCompare(right.name, "zh-CN"))
  })).sort((left, right) =>
    right.skills.length - left.skills.length || left.label.localeCompare(right.label, "zh-CN")
  );
}
