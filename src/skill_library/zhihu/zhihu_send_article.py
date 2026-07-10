"""Zhihu article publishing adapter."""

WRITE_URL = "https://zhuanlan.zhihu.com/write"
SIGN_URL = "https://www.zhihu.com/signin"


def _js_string(value: str) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    return f'"{text}"'


def _is_true(value) -> bool:
    text = str(value or "").strip().lower()
    return text in {
        "1",
        "true",
        "yes",
        "y",
        "on",
        "ai",
        "add-picture",
        "add_picture",
        "\u914d\u56fe",
        "\u52a0\u56fe",
        "\u52a0\u56fe\u7247",
        "\u751f\u6210\u56fe\u7247",
        "\u63d2\u5165\u56fe\u7247",
    }


def _click_center(center, label: str, wait_seconds: int = 1) -> None:
    if not center:
        raise RuntimeError(f"Zhihu AI picture {label} target not found")
    log(f"Zhihu AI picture {label} mouse click: {center}")
    mouse_click(center["x"], center["y"])
    wait(wait_seconds)


def _move_mouse_into_generated_picture():
    target = run_js(
        """(() => {
            const image = document.querySelector(
                "img[data-agentic-ai-generated-picture='1']"
            );
            if (!image) return null;

            image.scrollIntoView({ block: "center", inline: "center" });
            const rect = image.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) return null;

            const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
            const insideX = clamp(rect.left + rect.width * 0.45, 8, window.innerWidth - 8);
            const insideY = clamp(rect.top + rect.height * 0.45, 8, window.innerHeight - 8);
            return {
                outsideX: clamp(rect.left - 16, 8, window.innerWidth - 8),
                outsideY: insideY,
                insideX,
                insideY,
            };
        })()"""
    )
    if not target:
        return None

    mouse_move(target["outsideX"], target["outsideY"], 8)
    mouse_move(target["insideX"], target["insideY"], 16)
    mouse_move(target["insideX"] + 4, target["insideY"] + 2, 4)
    mouse_move(target["insideX"] - 2, target["insideY"] - 1, 4)
    return target


def _wait_until_js(script: str, timeout: int = 30, interval: float = 1):
    attempts = int(timeout / interval)
    if attempts < 1:
        attempts = 1
    for _ in range(attempts):
        result = run_js(script)
        if result:
            return result
        wait(interval)
    return None


def _require_write_editor(timeout: int = 60) -> None:
    state = _wait_until_js(
        """(() => {
            const title = document.querySelector("div.WriteIndex-pageTitle");
            const editor = document.querySelector(".DraftEditor-root");
            const titleInput = document.querySelector(
                "textarea.Input.i7cW1UcwT6ThdhTakqFm, textarea[placeholder*='100']"
            );
            if (title && editor && titleInput) {
                return {
                    ok: true,
                    url: location.href,
                    title: document.title,
                };
            }
            return null;
        })()""",
        timeout=timeout,
    )
    if not state:
        current = run_js("(() => location.href)()")
        raise RuntimeError(f"Zhihu write editor not ready; current URL: {current}")
    log(f"Zhihu write editor ready: {state}")


def _wait_for_body_image_loaded(timeout: int = 180) -> None:
    state = _wait_until_js(
        """(() => {
            const root = document.querySelector(".DraftEditor-root");
            if (!root) return null;
            const visible = (node) => {
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = window.getComputedStyle(node);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== "hidden" &&
                    style.display !== "none";
            };
            const images = Array.from(root.querySelectorAll("img")).filter(visible);
            const loaded = images.filter((img) => img.complete && img.naturalWidth > 0);
            if (loaded.length > 0) {
                return {
                    ok: true,
                    count: loaded.length,
                    firstSrc: (loaded[0].src || "").slice(0, 120),
                };
            }
            return null;
        })()""",
        timeout=timeout,
    )
    if not state:
        raise RuntimeError("Zhihu body image not loaded before publish")
    log(f"AIPIC_BODY_IMAGE_READY:{state}")


def _wait_for_ai_picture_textarea(timeout: int = 20) -> bool:
    for _ in range(timeout):
        ready = run_js(
            """(() => {
                const visible = (node) => {
                    if (!node) return false;
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== "hidden" &&
                        style.display !== "none";
                };
                const textOf = (node) => (node && node.textContent || "").replace(/\\s+/g, "");
                const textareaSelector = [
                    "textarea[maxlength='150']",
                    "textarea[placeholder*='\\u914d\\u56fe']",
                    "textarea[placeholder*='\\u63cf\\u8ff0']",
                    "textarea[placeholder*='\\u5185\\u5bb9']",
                    "textarea[placeholder*='\\u56fe']",
                ].join(",");
                const panels = Array.from(document.querySelectorAll("div,section,aside"))
                    .filter((node) => visible(node) && /AI\\u914d\\u56fe|\\u914d\\u56fe/.test(textOf(node)));
                for (const panel of panels) {
                    if (Array.from(panel.querySelectorAll(textareaSelector)).some(visible)) {
                        return true;
                    }
                }
                return Array.from(document.querySelectorAll(textareaSelector)).some(visible);
            })()"""
        )
        if ready:
            return True
        wait(1)
    return False


def _ai_picture_debug_snapshot():
    return run_js(
        """(() => {
            const visible = (node) => {
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = window.getComputedStyle(node);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== "hidden" &&
                    style.display !== "none";
            };
            const textOf = (node) => (node && node.textContent || "").replace(/\\s+/g, "");
            const textareas = Array.from(document.querySelectorAll("textarea"))
                .filter(visible)
                .map((node) => ({
                    placeholder: node.getAttribute("placeholder") || "",
                    maxlength: node.getAttribute("maxlength") || "",
                    value: (node.value || "").slice(0, 30),
                }));
            const labels = Array.from(document.querySelectorAll("button,[role='button'],div,span"))
                .filter((node) => visible(node) && /AI|\\u914d\\u56fe|\\u751f\\u6210\\u56fe\\u7247|\\u63d2\\u5165\\u6b63\\u6587/.test(textOf(node)))
                .slice(0, 30)
                .map((node) => ({
                    tag: node.tagName,
                    text: textOf(node).slice(0, 80),
                    cls: node.className || "",
                }));
            return {
                url: location.href,
                title: document.title,
                textareas,
                labels,
            };
        })()"""
    )


def _insert_ai_picture(title: str) -> None:
    """Generate a Zhihu AI picture and insert it into the article body."""
    log("AIPIC_MOUSE:v1")

    click_result = click("text=AI 配图", "text=AI配图")
    log(f"AIPIC_TEXT_CLICK:{click_result}")
    if _wait_for_ai_picture_textarea(timeout=3):
        log("AIPIC_TEXTAREA_OK_BY_TEXT_CLICK")
    else:
        log(f"AIPIC_AFTER_TEXT_CLICK:{_ai_picture_debug_snapshot()}")

    open_targets = run_js(
        """(() => {
            const label = "AI\\u914d\\u56fe";
            const visible = (node) => {
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = window.getComputedStyle(node);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== "hidden" &&
                    style.display !== "none";
            };
            const textOf = (node) => (node && node.textContent || "").replace(/\\s+/g, "");
            const centerOf = (node, name) => {
                if (!node) return null;
                node.scrollIntoView({ block: "center", inline: "center" });
                const rect = node.getBoundingClientRect();
                return {
                    name,
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2,
                    width: rect.width,
                    height: rect.height,
                    text: textOf(node).slice(0, 40),
                };
            };
            const pushUnique = (list, item) => {
                if (!item) return;
                const key = `${Math.round(item.x)}:${Math.round(item.y)}`;
                if (!list.some((old) => `${Math.round(old.x)}:${Math.round(old.y)}` === key)) {
                    list.push(item);
                }
            };
            const textarea = Array.from(document.querySelectorAll(
                "textarea[placeholder*='\\u914d\\u56fe'], textarea[placeholder*='\\u56fe'], textarea[maxlength='150']"
            )).find(visible);
            if (textarea) return [{ name: "already-open", x: -1, y: -1, width: 0, height: 0 }];

            const targets = [];
            const candidates = Array.from(document.querySelectorAll("button,[role='button'],div,span"))
                .filter((node) => visible(node) && textOf(node).includes(label));
            for (const seed of candidates) {
                pushUnique(targets, centerOf(seed, "ai-picture-label"));
                let card = seed;
                for (let i = 0; card && i < 8; i += 1, card = card.parentElement) {
                    if (!textOf(card).includes(label)) continue;
                    const arrow = Array.from(card.querySelectorAll(
                        "svg.ZDI--ArrowRight16, svg[class*='ArrowRight'], svg"
                    )).find(visible);
                    pushUnique(targets, centerOf(arrow, "ai-picture-arrow"));
                    pushUnique(targets, centerOf(card, "ai-picture-card"));
                }
            }
            return targets;
        })()"""
    )
    log(f"AIPIC_OPEN_TARGETS:{open_targets}")
    if not open_targets:
        raise RuntimeError("Zhihu AI picture entry not found")
    already_open = False
    for target in open_targets:
        if target.get("name") == "already-open":
            already_open = True
            break
    if not already_open:
        for target in open_targets[:8]:
            _click_center(target, f"open panel:{target.get('name')}")
            if _wait_for_ai_picture_textarea(timeout=3):
                break

    if not _wait_for_ai_picture_textarea():
        snapshot = _ai_picture_debug_snapshot()
        log(f"AIPIC_FAIL_SNAPSHOT:{snapshot}")
        raise RuntimeError(
            f"Zhihu AI picture textarea not found after opening panel: {snapshot}"
        )
    log("AIPIC_TEXTAREA_OK")

    mark_input_result = run_js(
        """(() => {
            const visible = (node) => {
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = window.getComputedStyle(node);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== "hidden" &&
                    style.display !== "none";
            };
            const textarea = Array.from(document.querySelectorAll(
                "textarea[maxlength='150'], textarea[placeholder*='\\u914d\\u56fe'], textarea[placeholder*='\\u63cf\\u8ff0'], textarea[placeholder*='\\u5185\\u5bb9'], textarea[placeholder*='\\u56fe']"
            )).find(visible);
            if (!textarea) return "AIPIC_MARK_INPUT_FAIL:no-textarea";
            textarea.setAttribute("data-agentic-ai-picture-input", "1");
            textarea.scrollIntoView({ block: "center", inline: "center" });
            return {
                ok: true,
                placeholder: textarea.getAttribute("placeholder") || "",
                value: textarea.value || "",
            };
        })()"""
    )
    log(f"AIPIC_MARK_INPUT:{mark_input_result}")

    ai_picture_input = "textarea[data-agentic-ai-picture-input='1']"
    click(ai_picture_input)
    fill(ai_picture_input, title)

    prompt_text = _js_string(title)
    fill_result = run_js(
        f"""(() => {{
            const prompt = {prompt_text};
            const textarea = document.querySelector("textarea[data-agentic-ai-picture-input='1']");
            if (!textarea) return "AIPIC_FILL_FAIL:no-marked-textarea";
            textarea.focus();
            const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
            if ((textarea.value || "") !== prompt) {{
                setter.call(textarea, prompt);
            }}
            textarea.setSelectionRange(prompt.length, prompt.length);
            if (typeof CompositionEvent === "function") {{
                textarea.dispatchEvent(new CompositionEvent("compositionstart", {{
                    bubbles: true,
                    data: "",
                }}));
                textarea.dispatchEvent(new CompositionEvent("compositionupdate", {{
                    bubbles: true,
                    data: prompt,
                }}));
                textarea.dispatchEvent(new CompositionEvent("compositionend", {{
                    bubbles: true,
                    data: prompt,
                }}));
            }}
            textarea.dispatchEvent(new InputEvent("beforeinput", {{
                bubbles: true,
                cancelable: true,
                inputType: "insertText",
                data: prompt,
            }}));
            textarea.dispatchEvent(new InputEvent("input", {{
                bubbles: true,
                cancelable: true,
                inputType: "insertText",
                data: prompt,
            }}));
            textarea.dispatchEvent(new KeyboardEvent("keyup", {{
                bubbles: true,
                cancelable: true,
                key: prompt.slice(-1) || "Process",
            }}));
            textarea.dispatchEvent(new Event("change", {{ bubbles: true }}));
            textarea.blur();
            textarea.focus();
            return {{
                ok: true,
                value: textarea.value || "",
                active: document.activeElement === textarea,
            }};
        }})()"""
    )
    log(f"AIPIC_FILL_RESULT:{fill_result}")
    wait(1)

    generate_result = run_js(
        """(() => {
            const label = "\\u751f\\u6210\\u56fe\\u7247";
            const panelLabel = "AI\\u914d\\u56fe";
            const visible = (node) => {
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = window.getComputedStyle(node);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== "hidden" &&
                    style.display !== "none";
            };
            const textOf = (node) => (node && node.textContent || "").replace(/\\s+/g, "");
            const centerOf = (node, name) => {
                if (!node) return null;
                node.scrollIntoView({ block: "center", inline: "center" });
                const rect = node.getBoundingClientRect();
                return {
                    name,
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2,
                    width: rect.width,
                    height: rect.height,
                    text: textOf(node).slice(0, 40),
                };
            };
            const dispatchFullClick = (node) => {
                if (!node) return { success: false, reason: "no-node" };
                node.scrollIntoView({ block: "center", inline: "center" });
                const rect = node.getBoundingClientRect();
                const x = rect.left + rect.width / 2;
                const y = rect.top + rect.height / 2;
                const options = {
                    bubbles: true,
                    cancelable: true,
                    composed: true,
                    view: window,
                    clientX: x,
                    clientY: y,
                    button: 0,
                    buttons: 1,
                };
                node.focus && node.focus();
                node.dispatchEvent(new PointerEvent("pointerover", options));
                node.dispatchEvent(new MouseEvent("mouseover", options));
                node.dispatchEvent(new PointerEvent("pointerenter", options));
                node.dispatchEvent(new MouseEvent("mouseenter", options));
                node.dispatchEvent(new PointerEvent("pointermove", options));
                node.dispatchEvent(new MouseEvent("mousemove", options));
                node.dispatchEvent(new PointerEvent("pointerdown", options));
                node.dispatchEvent(new MouseEvent("mousedown", options));
                node.dispatchEvent(new PointerEvent("pointerup", {...options, buttons: 0}));
                node.dispatchEvent(new MouseEvent("mouseup", {...options, buttons: 0}));
                node.dispatchEvent(new MouseEvent("click", {...options, buttons: 0}));
                if (typeof node.click === "function") node.click();
                return {
                    success: true,
                    x,
                    y,
                    tag: node.tagName,
                    cls: node.className || "",
                    text: textOf(node).slice(0, 40),
                };
            };
            const panel = Array.from(document.querySelectorAll("aside,section,div"))
                .filter((node) => visible(node) && textOf(node).includes(panelLabel))
                .sort((a, b) => {
                    const ar = a.getBoundingClientRect();
                    const br = b.getBoundingClientRect();
                    return (ar.width * ar.height) - (br.width * br.height);
                })[0] || document;
            const exactTextNode = Array.from(panel.querySelectorAll(
                "button,[role='button'],div.css-177mpcg,div[class*='177mpcg'],div,span"
            )).find((node) => visible(node) && textOf(node) === label);
            const button =
                (exactTextNode && exactTextNode.closest("div.css-g1ywwj,div[class*='g1ywwj'],button,[role='button']")) ||
                (exactTextNode && exactTextNode.parentElement) ||
                Array.from(panel.querySelectorAll("button,[role='button'],div.css-g1ywwj,div[class*='g1ywwj'],div,span"))
                    .find((node) => visible(node) && textOf(node) === label) ||
                Array.from(document.querySelectorAll("button,[role='button'],div.css-g1ywwj,div[class*='g1ywwj'],div,span"))
                    .find((node) => visible(node) && textOf(node) === label);
            const dispatched = dispatchFullClick(button);
            return {
                dispatched,
                center: centerOf(button, "generate-picture"),
            };
        })()"""
    )
    log(f"AIPIC_GENERATE_DISPATCH:{generate_result}")
    generate_center = generate_result.get("center") if generate_result else None
    if generate_center:
        _click_center(generate_center, "generate picture fallback", wait_seconds=2)
    else:
        wait(2)

    image_ready = False
    for wait_index in range(300):
        image_ready = run_js(
            """(() => {
                const visible = (node) => {
                    if (!node) return false;
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== "hidden" &&
                        style.display !== "none";
                };
                const images = Array.from(document.querySelectorAll("img"))
                    .filter((img) => visible(img) &&
                        /pic-private\\.zhihu\\.com|editor_ai_image|sceneCode=editor_ai_image/.test(img.src || ""));
                return {
                    ready: images.length > 0,
                    count: images.length,
                    firstSrc: images[0] ? (images[0].src || "").slice(0, 120) : "",
                };
            })()"""
        )
        if image_ready and image_ready.get("ready"):
            break
        if wait_index % 15 == 0:
            log(f"AIPIC_WAIT_IMAGE:{wait_index}s {image_ready}")
        wait(1)
    if not image_ready or not image_ready.get("ready"):
        raise RuntimeError(f"Zhihu generated AI picture not found after waiting: {image_ready}")
    log(f"AIPIC_IMAGE_OK:{image_ready}")

    image_center = run_js(
        """(() => {
            const visible = (node) => {
                if (!node) return false;
                const rect = node.getBoundingClientRect();
                const style = window.getComputedStyle(node);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== "hidden" &&
                    style.display !== "none";
            };
            const centerOf = (node, name) => {
                if (!node) return null;
                node.scrollIntoView({ block: "center", inline: "center" });
                const rect = node.getBoundingClientRect();
                return {
                    name,
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2,
                    width: rect.width,
                    height: rect.height,
                    src: (node.getAttribute("src") || "").slice(0, 120),
                };
            };
            const image = Array.from(document.querySelectorAll("img"))
                .find((img) => visible(img) &&
                    /pic-private\\.zhihu\\.com|editor_ai_image|sceneCode=editor_ai_image/.test(img.src || ""));
            if (image) {
                image.setAttribute("data-agentic-ai-generated-picture", "1");
            }
            return centerOf(image, "generated-picture");
        })()"""
    )
    if not image_center:
        raise RuntimeError("Zhihu generated AI picture click target not found")
    click("img[data-agentic-ai-generated-picture='1']")
    log(f"AIPIC_IMAGE_SELECTED:{image_center}")

    insert_target = None
    for _ in range(60):
        mouse_target = _move_mouse_into_generated_picture()
        if not mouse_target:
            wait(1)
            continue
        wait(0.4)
        insert_target = run_js(
            """(() => {
                const label = "\\u63d2\\u5165\\u6b63\\u6587";
                const visible = (node) => {
                    if (!node) return false;
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== "hidden" &&
                        style.display !== "none";
                };
                const textOf = (node) => (node && node.textContent || "").replace(/\\s+/g, "");
                const mark = (node, name) => {
                    if (!node) return null;
                    node.setAttribute("data-agentic-ai-insert-picture", "1");
                    node.scrollIntoView({ block: "center", inline: "center" });
                    const rect = node.getBoundingClientRect();
                    return {
                        name,
                        tag: node.tagName,
                        className: String(node.className || "").slice(0, 80),
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                        width: rect.width,
                        height: rect.height,
                        text: textOf(node).slice(0, 40),
                    };
                };
                document.querySelectorAll("[data-agentic-ai-insert-picture='1']")
                    .forEach((node) => node.removeAttribute("data-agentic-ai-insert-picture"));

                const selectedImage = document.querySelector("img[data-agentic-ai-generated-picture='1']");
                const selectedCard = selectedImage && (
                    selectedImage.closest("div[class*='diy6qb']") ||
                    selectedImage.closest("div")
                );
                const scopedButton = selectedCard && Array.from(selectedCard.querySelectorAll("button,[role='button'],div,span"))
                    .find((node) => visible(node) && textOf(node).includes(label));
                if (scopedButton) return mark(scopedButton, "insert-picture-scoped");

                const globalButton = Array.from(document.querySelectorAll("button,[role='button'],div,span"))
                    .find((node) => visible(node) && textOf(node).includes(label));
                return mark(globalButton, "insert-picture-global");
            })()"""
        )
        if insert_target:
            break
        wait(1)
    if not insert_target:
        raise RuntimeError("Zhihu insert-picture button not found after generated image selected")
    log(f"AIPIC_INSERT_TARGET:{insert_target}")
    click("[data-agentic-ai-insert-picture='1']")
    wait(2)
    log("AIPIC_INSERT_DONE")


def run(title: str, keyword: str, add_picture=False):
    """Open Zhihu writer, fill article title/body, optionally add AI picture, and publish."""
    if not ensure_auth("zhihu", SIGN_URL):
        log("Zhihu login state not confirmed; skip article publish")
        return

    goto(WRITE_URL)
    _require_write_editor(timeout=90)

    fill(
        "textarea.Input.i7cW1UcwT6ThdhTakqFm",
        title,
        "textarea[placeholder*='100']",
    )
    wait(1)

    _require_write_editor(timeout=30)
    body_text = _js_string(keyword)
    run_js(
        f"""(() => {{
            const text = {body_text};
            const root = document.querySelector(".DraftEditor-root");
            if (!root) return "DraftEditor root not found";

            const editor =
                root.querySelector("[contenteditable='true']") ||
                root.querySelector(".public-DraftEditor-content");
            if (!editor) return "DraftEditor content not found";

            editor.focus();
            const offsetSpan = editor.querySelector(
                "div[data-contents='true'] .Editable-unstyled " +
                "div[data-offset-key] > span[data-offset-key]"
            );
            if (!offsetSpan) return "DraftEditor offset span not found";

            const offsetKey = offsetSpan.getAttribute("data-offset-key") || "";
            offsetSpan.innerHTML = "";

            const textSpan = document.createElement("span");
            textSpan.setAttribute("data-text", "true");
            if (offsetKey) {{
                textSpan.setAttribute("data-offset-key", offsetKey);
            }}
            textSpan.textContent = text;
            offsetSpan.appendChild(textSpan);

            editor.dispatchEvent(new InputEvent("input", {{
                bubbles: true,
                cancelable: true,
                inputType: "insertText",
                data: text,
            }}));
            editor.dispatchEvent(new Event("change", {{ bubbles: true }}));
            return textSpan.outerHTML;
        }})()"""
    )
    wait(1)

    if _is_true(add_picture):
        _insert_ai_picture(title)
        _wait_for_body_image_loaded(timeout=180)

    wait_for_element("button.Button--primary", timeout=15)
    click("button.Button--primary")
    wait(2)

    log(f"Zhihu article publish clicked: {title}")
