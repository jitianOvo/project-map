import json
import shutil
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from server.auth import initialize, password_hash
from server.http import CloudServer


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ui_service(tmp_path):
    shutil.copytree(ROOT / "server/public", tmp_path / "server/public")
    initialize(tmp_path)
    salt = "00" * 16
    (tmp_path / ".secrets/account.json").write_text(json.dumps({"username":"owner","salt":salt,"hash":password_hash("ui-test-only",salt)}))
    service=CloudServer(("127.0.0.1",0),tmp_path)
    thread=threading.Thread(target=service.serve_forever,daemon=True)
    thread.start()
    yield service,f"http://127.0.0.1:{service.server_port}/"
    service.shutdown();thread.join();service.server_close()


@pytest.fixture
def browser():
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",headless=True)
        yield browser
        browser.close()


def page_for(browser,url,mobile=False):
    context=browser.new_context(viewport={"width":390 if mobile else 1400,"height":844 if mobile else 900},is_mobile=mobile,has_touch=mobile)
    page=context.new_page()
    page.add_init_script("localStorage.setItem('project-map-preferences',JSON.stringify({endpoint:"+json.dumps(url)+"}));")
    errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
    page.goto(url,wait_until="networkidle")
    page.wait_for_function("()=>document.querySelector('#projectCount').textContent.includes('项目')")
    return context,page,errors


def create(page,title):
    page.locator("#emptyNew").click()
    page.locator("#dialogContent input").first.fill(title)
    page.locator("#dialogContent input").first.press("Enter")
    page.wait_for_function("()=>!document.querySelector('#editor').disabled")


def connect(page):
    page.locator("#accountButton").click()
    page.locator("#dialogContent input[type=password]").fill("ui-test-only")
    try:
        page.locator("#dialogConfirm").click(timeout=5000)
    except Exception:
        page.screenshot(path=str(ROOT/'.state/login-error.png'))
        print(page.evaluate("()=>[...document.querySelectorAll('#dialog,#dialogForm,#dialogContent,#dialogConfirm')].map(x=>({id:x.id,rect:x.getBoundingClientRect().toJSON()}))"))
        raise
    try:
        page.wait_for_function("()=>document.querySelector('#accountButton').textContent==='账户'",timeout=10000)
    except Exception:
        print('登录诊断',page.locator('#toast').inner_text(),page.locator('#dialog').inner_text())
        page.screenshot(path=str(ROOT/'.state/login-error.png'))
        raise
    page.locator("#syncButton").click()
    page.wait_for_function("()=>document.querySelector('#syncStatus').textContent.startsWith('已同步')",timeout=15000)


def test_desktop_preview_scroll_and_images(ui_service,browser):
    _service,url=ui_service
    context,page,errors=page_for(browser,url)
    try:
        create(page,"公开测试大纲")
        content="# 测试\n\n"+"\n\n".join(f"第 {n} 段：这是用于验证预览位置的公开内容。" for n in range(160))
        page.locator("#editor").fill(content)
        page.wait_for_timeout(350)
        page.locator("[data-mode=split]").last.click() if False else None
        page.evaluate("document.querySelector('#preview').scrollTop=1200")
        before=page.evaluate("document.querySelector('#preview').scrollTop")
        page.locator("#editor").press("Control+End")
        page.locator("#editor").press("End")
        page.locator("#editor").type(" 增加内容")
        page.wait_for_timeout(300)
        after=page.evaluate("document.querySelector('#preview').scrollTop")
        assert abs(after-before)<=2
        connect(page)
        png=bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082')
        page.locator('#imageInput').set_input_files({"name":"test.png","mimeType":"image/png","buffer":png})
        page.wait_for_function("()=>{let i=document.querySelector('#preview img');return i&&i.complete&&i.naturalWidth>0}")
        assert 'Media/' in page.locator('#editor').input_value()
        first=page.locator('#preview img').bounding_box()
        page.locator('#preview').hover();page.keyboard.down('Control');page.mouse.wheel(0,-120);page.keyboard.up('Control');page.wait_for_timeout(150)
        second=page.locator('#preview img').bounding_box()
        assert second['width']>first['width']
        page.screenshot(path=str(ROOT/'.state/desktop-test.png'))
        assert errors==[]
    finally:context.close()


def test_mobile_layout_and_offline(ui_service,browser):
    _service,url=ui_service
    context,page,errors=page_for(browser,url,True)
    try:
        create(page,'手机测试')
        page.locator('#editor').fill('1. 手机工作\n2. 下一步')
        page.locator('#editor').press('Control+End');page.locator('#editor').press('Enter')
        assert page.locator('#editor').input_value().endswith('\n3. ')
        page.locator('.mode-buttons [data-mode=preview]').click();page.wait_for_timeout(200)
        assert page.locator('#preview').bounding_box()['width']>300
        assert page.evaluate('document.body.scrollWidth<=innerWidth')
        page.screenshot(path=str(ROOT/'.state/mobile-test.png'))
        page.locator('.mode-buttons [data-mode=edit]').click()
        context.set_offline(True);page.locator('#editor').type('离线修改');page.wait_for_timeout(250);context.set_offline(False)
        page.reload(wait_until='networkidle');page.wait_for_function("()=>!document.querySelector('#editor').disabled")
        assert '离线修改' in page.locator('#editor').input_value()
        assert errors==[]
    finally:context.close()


def test_two_clients_require_handoff_and_keep_latest(ui_service,browser):
    service,url=ui_service
    first,page1,errors1=page_for(browser,url)
    second,page2,errors2=page_for(browser,url,True)
    try:
        create(page1,'两端协作测试');page1.locator('#editor').fill('第一行\n第二行\n第三行');connect(page1);connect(page2)
        page2.locator('#toggleLibrary').click();page2.locator('.project').first.click()
        page2.wait_for_function("()=>document.querySelector('#editingMessage').textContent.includes('电脑端')")
        assert page2.locator('#editor').is_disabled()
        page1.locator('#endEditing').click()
        page1.wait_for_function("()=>document.querySelector('#editingMessage').textContent.includes('本端已结束')")
        page2.locator('.project').first.click()
        page2.wait_for_function("()=>document.querySelector('#editor').value.includes('第一行')")
        page2.wait_for_function("()=>!document.querySelector('#editor').readOnly")
        page2.locator('#editor').fill('第一行\n第二行\n手机改第三行')
        page2.locator('#endEditing').click()
        page2.wait_for_function("()=>document.querySelector('#editingMessage').textContent.includes('本端已结束')")
        page1.locator('#resumeEditing').click()
        page1.wait_for_function("()=>!document.querySelector('#editor').readOnly && document.querySelector('#editor').value.includes('手机改第三行')")
        page1.locator('#editor').fill('电脑改第一行\n第二行\n手机改第三行')
        page1.locator('#endEditing').click()
        page1.wait_for_function("()=>document.querySelector('#editingMessage').textContent.includes('本端已结束')")
        page2.locator('#resumeEditing').click()
        page2.wait_for_function("()=>!document.querySelector('#editor').readOnly && document.querySelector('#editor').value.includes('电脑改第一行')")
        assert len(service.storage.changes(0)['documents'])==1
        assert service.storage.changes(0)['documents'][0]['content']=='电脑改第一行\n第二行\n手机改第三行'
        assert errors1+errors2==[]
    finally:first.close();second.close()


def test_format_toggle_find_and_sanitized_preview(ui_service,browser):
    _service,url=ui_service
    context,page,errors=page_for(browser,url)
    try:
        create(page,'格式测试')
        page.locator('#editor').fill('**测试**\n第二行\n第三行')
        page.locator('#editor').evaluate('(b)=>b.setSelectionRange(0,6)')
        page.locator('#editor').press('Control+b')
        assert page.locator('#editor').input_value().startswith('测试\n')
        page.locator('#editor').press('Control+f');page.locator('#findText').fill('第二行');page.locator('#findNext').click()
        page.locator('#replaceText').fill('替换内容');page.locator('#replaceOne').click()
        assert '替换内容' in page.locator('#editor').input_value()
        page.locator('#findClose').click()
        page.locator('#editor').fill('<img src="x" onerror="window.BAD=true"><script>window.BAD=true</script><span style="position:fixed;inset:0">安全文本</span>\n\n---\n\n文本')
        page.wait_for_timeout(200)
        assert page.locator('#preview [onerror],#preview script,#preview article [style]').count()==0
        assert page.evaluate('window.BAD') is None
        assert page.locator('#preview hr').count()==1
        assert errors==[]
    finally:context.close()
