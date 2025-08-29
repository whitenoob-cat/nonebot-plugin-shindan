import re
import time
from pathlib import Path
from typing import Union

import httpx
import jinja2
from bs4 import BeautifulSoup, Tag
from nonebot_plugin_htmlrender import get_new_page, html_to_pic

from .config import shindan_config
from .model import ShindanConfig

tpl_path = Path(__file__).parent / "templates"
env = jinja2.Environment(loader=jinja2.FileSystemLoader(tpl_path), enable_async=True)


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/96.0.4664.110 Safari/537.36"
)
headers = {"user-agent": USER_AGENT}
if shindan_config.shindanmaker_cookie:
    headers["cookie"] = shindan_config.shindanmaker_cookie

async def try_browse_pages(timeout:int=3) -> str:
    _page_list = ["","cn.","en.","kr.","jp."]
    _time_spend = {}
    async with get_new_page() as page:
        await page.set_extra_http_headers(headers=headers)
        for _page_name in _page_list:
            try:
                _timestamp = time.time()
                await page.goto(f"https://{_page_name}shindanmaker.com", wait_until="commit", timeout=timeout*1000)
                _timestamp = time.time() - _timestamp 
                _time_spend[_page_name] = _timestamp
            except Exception:
                _timestamp = "Timeout"
    _least_time_spend = min(_time_spend,default="-1")
    if _least_time_spend == "-1":
        return "Timeout"
    else:
        return f"https://{_least_time_spend}shindanmaker.com"


async def download_image(url: str) -> bytes:
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=20, follow_redirects=True)
        return resp.read()


async def get_shindan_title(id: int) -> str:
    url = await try_browse_pages()
    if url == "Timeout":
        raise RuntimeError("所有站点均无法访问，请稍后再试")
    async with get_new_page() as page:
        await page.set_extra_http_headers(headers=headers)
        await page.goto(url, wait_until="commit")
        return await page.locator('//h1[@id="shindanTitle"]').inner_text()


async def make_shindan(id: int, name: str, mode="image") -> Union[str, bytes]:
    url = await try_browse_pages()
    if url == "Timeout":
        raise RuntimeError("所有站点均无法访问，请稍后再试")
    seed = time.strftime("%y%m%d", time.localtime())
    async with get_new_page() as page:
        await page.set_extra_http_headers(headers=headers)
        await page.goto(url, wait_until="commit")
        await page.locator('//input[@id="user_input_value_1"]').fill(name + seed)
        await page.locator('//button[@id="shindanButtonSubmit"]').click()
        content = await page.content()

    if mode == "image":
        html, has_chart = await render_html(content)
        html = html.replace(seed, "")
        return await html_to_pic(
            html,
            template_path=f"file://{tpl_path.absolute()}",
            wait=2000 if has_chart else 0,
            viewport={"width": 750, "height": 100},
        )
    else:
        dom = BeautifulSoup(content, "lxml")
        result = dom.find("span", {"id": "shindanResult"})
        assert isinstance(result, Tag)
        for img in result.find_all("img"):
            img.replace_with(img["src"])
        return result.text.replace(seed, "")


def remove_shindan_effects(content: Tag, type: str):
    for tag in content.find_all("span", {"class": "shindanEffects", "data-mode": type}):
        assert isinstance(tag, Tag)
        if noscript := tag.find_next("noscript"):
            noscript.replace_with_children()
            tag.extract()


async def render_html(content: str) -> tuple[str, bool]:
    dom = BeautifulSoup(content, "lxml")
    result_js = str(dom.find("script", string=re.compile(r"savedShindanResult")))
    title = str(
        dom.find("h1", {"id": "shindanResultAbove"})
        or dom.find("div", {"class": "shindanTitleImageContainer"})
    )
    result = dom.find("div", {"id": "shindanResultBlock"})
    assert isinstance(result, Tag)
    remove_shindan_effects(result, "ef_shuffle")
    remove_shindan_effects(result, "ef_typing")
    result = str(result)
    has_chart = "chart.js" in content

    shindan_tpl = env.get_template("shindan.html")
    html = await shindan_tpl.render_async(
        result_js=result_js, title=title, result=result, has_chart=has_chart
    )
    return html, has_chart


async def render_shindan_list(shindan_list: list[ShindanConfig]) -> bytes:
    tpl = env.get_template("shindan_list.html")
    html = await tpl.render_async(shindan_list=shindan_list)
    return await html_to_pic(
        html,
        template_path=f"file://{tpl_path.absolute()}",
        viewport={"width": 100, "height": 100},
    )
