import assert from "node:assert/strict";
import test from "node:test";
import { filterAndGroupSkills, type SkillInfo } from "../src/utils/skillCatalog.js";

function skill(id: string, platform: string, name: string): SkillInfo {
  return {
    id,
    platform,
    name,
    type: "domain",
    description: `${name} description`,
    triggers: [platform, name],
    version: "1.0.0",
    action: "search",
    examples: [],
    params: {},
    command_template: `${name}命令`
  };
}

test("skills are grouped by website with larger groups first", () => {
  const groups = filterAndGroupSkills([
    skill("zhihu-search", "zhihu", "知乎搜索"),
    skill("github-search", "github", "GitHub 搜索"),
    skill("zhihu-send", "zhihu", "知乎发布")
  ], "");
  assert.deepEqual(groups.map((group) => [group.label, group.skills.length]), [
    ["知乎", 2],
    ["GitHub", 1]
  ]);
});

test("skill search matches website, description, and command template", () => {
  const skills = [
    skill("zhihu-search", "zhihu", "知乎搜索"),
    skill("gmail-send", "gmail", "Gmail 发送邮件")
  ];
  assert.equal(filterAndGroupSkills(skills, "知乎")[0].skills[0].id, "zhihu-search");
  assert.equal(filterAndGroupSkills(skills, "发送邮件命令")[0].skills[0].id, "gmail-send");
  assert.deepEqual(filterAndGroupSkills(skills, "不存在"), []);
});
