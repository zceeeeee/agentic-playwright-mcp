"""Direct GitHub login skill test using ScriptEngine."""

import os

from src.core.browser_manager import get_browser_manager
from src.core.script_engine import ScriptEngine
from src.layer_2.controls import get_controls_exports
from src.skill_library.others.github_login import run as github_login

TEST_USERNAME = os.getenv("GITHUB_USERNAME", "feitianduowen")
TEST_PASSWORD = os.getenv("GITHUB_PASSWORD", "xxxxxxxx")


def run_github_login_direct():
    """Run the GitHub login skill directly from the script sandbox."""
    print("开始测试 GitHub 登录...")
    print(f"用户名: {TEST_USERNAME}")
    print(f"密码: {'*' * len(TEST_PASSWORD)}")

    browser_manager = get_browser_manager()
    browser_manager.launch(headless=False)

    try:
        engine = ScriptEngine(browser_manager)
        engine.register_functions(get_controls_exports())
        engine.register_function("github_login", github_login)

        script = f'''
result = github_login("{TEST_USERNAME}", "{TEST_PASSWORD}")
log(f"GitHub 登录返回: {{result}}")

wait(3)
url = get_url()
title = get_title()

log(f"当前 URL: {{url}}")
log(f"页面标题: {{title}}")

screenshot("github_login_result.png")
log("截图已保存: github_login_result.png")
'''

        print("\n=== 执行登录脚本 ===")
        result = engine.execute(script)

        print("\n=== 执行结果 ===")
        print(f"成功: {result.success}")
        if result.output:
            print(f"输出:\n{result.output}")
        if result.error:
            print(f"错误: {result.error}")

        input("\n登录完成，请查看浏览器页面。按回车退出...")

    finally:
        browser_manager.close()
        print("浏览器已关闭")


if __name__ == "__main__":
    run_github_login_direct()
