import json

from test_ui import browser, ui_service, page_for, create, connect


def ready(page):
    page.wait_for_function("()=>!document.querySelector('#editor').readOnly && document.querySelector('#editingMessage').textContent.includes('正在本端编辑')")


def test_two_clients_block_same_allow_different_and_load_latest(ui_service, browser):
    _, url = ui_service
    contexts = []
    try:
        pc, first, errors1 = page_for(browser, url)
        contexts.append(pc)
        create(first, "交接演示")
        first.locator("#editor").fill("电脑最新版")
        connect(first)
        ready(first)
        phone, second, errors2 = page_for(browser, url, True)
        contexts.append(phone)
        connect(second)
        second.locator("#toggleLibrary").click()
        second.locator(".project").filter(has_text="交接演示").click()
        second.wait_for_function("()=>document.querySelector('#editingMessage').textContent.includes('电脑端')")
        assert second.locator("#editor").is_disabled()
        first.locator("#endEditing").click()
        first.wait_for_function("()=>document.querySelector('#editingMessage').textContent.includes('本端已结束')")
        ready(second)
        assert second.locator("#editor").input_value() == "电脑最新版"
        second.locator("#editor").fill("手机接着写")
        first.locator("#newButton").click()
        first.locator("#dialogContent input").first.fill("不同大纲")
        first.locator("#dialogConfirm").click()
        ready(first)
        first.locator("#editor").fill("电脑写另一份")
        assert not second.locator("#editor").evaluate("e=>e.readOnly")
        assert errors1 == errors2 == []
    finally:
        for context in contexts: context.close()


def test_offline_cloud_editor_freezes_and_preserves_draft(ui_service, browser):
    _, url = ui_service
    context, page, errors = page_for(browser, url, True)
    try:
        create(page, "断网演示")
        connect(page)
        ready(page)
        page.locator("#editor").fill("已经输入的内容")
        page.evaluate("window.flushProjectMap()")
        context.set_offline(True)
        page.wait_for_function("()=>document.querySelector('#editor').readOnly")
        assert page.locator("#editor").input_value() == "已经输入的内容"
        context.set_offline(False)
        page.locator("#resumeEditing").click()
        ready(page)
        assert page.locator("#editor").input_value() == "已经输入的内容"
        assert errors == []
    finally: context.close()


def test_closed_browser_releases_and_waiting_phone_automatically_resumes(ui_service, browser):
    _, url = ui_service
    pc, first, _ = page_for(browser, url)
    phone, second, errors = page_for(browser, url, True)
    try:
        create(first, "关闭窗口接力")
        first.locator("#editor").fill("关闭之前已经同步的正文")
        connect(first)
        ready(first)
        connect(second)
        second.locator("#toggleLibrary").click()
        second.locator(".project").filter(has_text="关闭窗口接力").click()
        second.wait_for_function("()=>document.querySelector('#editingMessage').textContent.includes('电脑端')")
        first.close()
        ready(second)
        assert second.locator("#editor").input_value() == "关闭之前已经同步的正文"
        assert errors == []
    finally:
        pc.close()
        phone.close()
