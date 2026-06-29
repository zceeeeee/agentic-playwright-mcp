"""Simple GitHub login test."""

import os

from src.core.browser_manager import get_browser_manager
from src.core.script_engine import ScriptEngine
from src.layer_2.controls import get_controls_exports
from src.skill_library.others.github_login import run as github_login

TEST_USERNAME = os.getenv("GITHUB_USERNAME", "feitianduowen")
TEST_PASSWORD = os.getenv("GITHUB_PASSWORD", "xxxxxxxx")


def run_simple_login():
    """Run the GitHub login flow in a visible browser."""
    print("=== GitHub 登录测试 ===")
    print(f"用户名: {TEST_USERNAME}")
    print(f"密码: {'*' * len(TEST_PASSWORD)}\n")

    browser_manager = get_browser_manager()
    browser_manager.launch(headless=False)

    try:
        engine = ScriptEngine(browser_manager)
        engine.register_functions(get_controls_exports())
        engine.register_function("github_login", github_login)

        script = f'''
result = github_login(
    "{TEST_USERNAME}",
    "{TEST_PASSWORD}",
)

log(f"登录结果: {{result}}")
wait(2)

url = get_url()
title = get_title()
log(f"当前 URL: {{url}}")
log(f"页面标题: {{title}}")

screenshot("github_login_test.png")
log("截图已保存: github_login_test.png")
'''

        print("开始执行登录...\n")
        result = engine.execute(script)

        print("=== 执行结果 ===")
        print(f"成功: {result.success}")
        if result.output:
            print(f"\n输出:\n{result.output}")
        if result.error:
            print(f"\n错误:\n{result.error}")

        print("\n登录流程完成。")
        print("请查看浏览器窗口确认登录状态。")
        print("截图保存在: github_login_test.png")

        input("\n按回车关闭浏览器...")

    finally:
        browser_manager.close()
        print("测试完成")


if __name__ == "__main__":
    run_simple_login()
