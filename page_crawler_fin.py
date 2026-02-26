import os
import re
import json
import time
import base64
import requests
from bs4 import BeautifulSoup, NavigableString, Comment
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from openai import OpenAI

# ================= 配置区 =================
CONFIG_FILE = "menu.json"           
BASE_URL = "https://your-system-domain.com" # 基础域名
LOGIN_URL = f"{BASE_URL}/login"
CONTENT_SELECTOR = "main.content-body"      # 正文容器选择器
OUTPUT_DIR = "scraped_docs"
VERSION_PARAM = "1.2.0"                    # URL 中的版本号

# OpenAI 配置
API_KEY = "your-api-key"
CUSTOM_BASE_URL = "https://your-proxy-domain.com/v1"
MODEL_NAME = "gpt-4o-mini" 

# 过滤配置
SKIP_IMAGE_PREFIX = "xxx"

client = OpenAI(api_key=API_KEY, base_url=CUSTOM_BASE_URL)

class DocScraper:
    def __init__(self):
        if not os.path.exists(OUTPUT_DIR):
            os.makedirs(OUTPUT_DIR)
        
        self.driver = webdriver.Chrome()
        self.session = requests.Session()

    def sync_cookies(self):
        """登录态同步"""
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie['name'], cookie['value'])

    def get_image_base64(self, img_url):
        """下载图片并转码"""
        try:
            # 这里的 img_url 已假定为完整 URL
            resp = self.session.get(img_url, timeout=10)
            if resp.status_code == 200:
                ext = img_url.split('.')[-1].split('?')[0].lower()
                mime = f"image/{ext}" if ext in ['png','jpg','jpeg','gif','webp'] else "image/jpeg"
                b64 = base64.b64encode(resp.content).decode('utf-8')
                return f"data:{mime};base64,{b64}"
        except Exception as e:
            print(f"  [!] 图片下载失败: {e}")
        return None

    def analyze_img_with_ai(self, img_url):
        """大模型解析图片"""
        if not img_url or img_url.startswith(SKIP_IMAGE_PREFIX):
            return None

        b64_data = self.get_image_base64(img_url)
        if not b64_data: return "[无法读取图片内容]"
        
        try:
            res = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "描述图片内容并提取关键文字。"},
                    {"type": "image_url", "image_url": {"url": b64_data}}
                ]}]
            )
            return res.choices[0].message.content.strip()
        except Exception as e:
            return f"[AI解析报错: {e}]"

    def html_to_md(self, element):
        """HTML 到 Markdown 转换"""
        if isinstance(element, Comment): return ""
        if isinstance(element, NavigableString): return element.string or ""

        tag = element.name
        inner_md = "".join(self.html_to_md(c) for c in element.children)

        match tag:
            case 'h1' | 'h2' | 'h3': return f"\n\n{'#' * int(tag[1])} {inner_md}\n"
            case 'p': return f"\n\n{inner_md}\n"
            case 'strong' | 'b': return f" **{inner_md}** "
            case 'a': return f" [{inner_md}]({element.get('href', '#')}) "
            case 'ul' | 'ol': return f"\n{inner_md}\n"
            case 'li':
                prefix = "1. " if element.parent.name == 'ol' else "* "
                return f"{prefix}{inner_md}\n"
            case 'pre': return f"\n```\n{element.get_text().strip()}\n```\n"
            case 'img':
                src = element.get('src', '').strip()
                desc = self.analyze_img_with_ai(src)
                if desc is None: return ""
                return f"\n\n![img]({src})\n> **AI解析**: {desc}\n\n"
            case 'table': return self._parse_table(element)
            case _: return inner_md

    def _parse_table(self, table):
        rows = []
        all_tr = table.find_all('tr')
        if not all_tr: return ""
        for tr in all_tr:
            cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
            rows.append(f"| {' | '.join(cells)} |")
        if len(rows) > 0:
            col_count = len(all_tr[0].find_all(['td', 'th']))
            sep = f"| {' | '.join(['---'] * col_count)} |"
            rows.insert(1, sep)
        return "\n" + "\n".join(rows) + "\n"

    def traverse_menu(self, menu_list, path=[]):
        """
        递归解析新的 JSON 结构
        字段: childList, menuCode, label
        """
        for node in menu_list:
            label = re.sub(r'[\\/:*?"<>|]', '-', node.get('label', 'unnamed'))
            new_path = path + [label]
            
            # 判断 childList
            child_list = node.get('childList', [])
            
            if child_list:
                # 存在子列表，继续递归
                self.traverse_menu(child_list, new_path)
            else:
                # 叶子节点，拼接新的 URL 规则
                menu_code = node.get('menuCode')
                if menu_code:
                    target_url = f"{BASE_URL}/designCode?code={menu_code}&version={VERSION_PARAM}"
                    self.scrape_page(target_url, new_path)

    def scrape_page(self, url, path_list):
        file_name = "-".join(path_list) + ".md"
        print(f">>> 正在同步: {file_name}")
        try:
            self.driver.get(url)
            time.sleep(2) # 等待页面渲染
            
            soup = BeautifulSoup(self.driver.page_source, 'lxml')
            content = soup.select_one(CONTENT_SELECTOR)
            
            if content:
                md_body = self.html_to_md(content)
                save_path = os.path.join(OUTPUT_DIR, file_name)
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(f"# {' / '.join(path_list)}\n\n{md_body}")
            else:
                print(f"  [!] 未找到正文内容: {url}")
        except Exception as e:
            print(f"  [!] 抓取异常: {url} -> {e}")

    def run(self):
        # 1. 登录
        self.driver.get(LOGIN_URL)
        input(">>> 请在浏览器完成登录后，回到此处按回车...")
        self.sync_cookies()

        # 2. 读取 JSON 并启动
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            menu_data = json.load(f)
        
        self.traverse_menu(menu_data)
        
        self.driver.quit()
        print(">>> 任务全部完成！")

if __name__ == "__main__":
    DocScraper().run()
