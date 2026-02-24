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
CONFIG_FILE = "menu.json"           # JSON 配置文件
BASE_URL = "https://docs.example.com" # 基础 URL
LOGIN_URL = f"{BASE_URL}/login"
CONTENT_SELECTOR = "main.content-body" # 页面正文选择器
OUTPUT_DIR = "scraped_docs"

# OpenAI 配置
API_KEY = "your-api-key"
CUSTOM_BASE_URL = "https://your-proxy-domain.com/v1"

client = OpenAI(api_key=API_KEY, base_url=CUSTOM_BASE_URL)

class DocScraper:
    def __init__(self):
        self.output_path = OUTPUT_DIR
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
        
        # 初始化浏览器
        self.driver = webdriver.Chrome()
        self.session = requests.Session()

    def sync_cookies(self):
        """将 Selenium 的登录态同步到 requests"""
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie['name'], cookie['value'])

    def get_image_base64(self, img_url):
        """下载图片并转为 Base64 流"""
        try:
            full_url = requests.compat.urljoin(BASE_URL, img_url)
            # 使用带登录态的 session 下载
            resp = self.session.get(full_url, timeout=10)
            if resp.status_code == 200:
                ext = img_url.split('.')[-1].lower()
                mime = f"image/{ext}" if ext in ['png','jpg','jpeg','gif'] else "image/jpeg"
                b64 = base64.b64encode(resp.content).decode('utf-8')
                return f"data:{mime};base64,{b64}"
        except Exception as e:
            print(f"  [!] 图片获取失败: {e}")
        return None

    def analyze_img_with_ai(self, img_url):
        """多模态解析图片"""
        b64_data = self.get_image_base64(img_url)
        if not b64_data: return "[无法读取图片]"
        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "描述图片内容并提取其中文字。"},
                    {"type": "image_url", "image_url": {"url": b64_data}}
                ]}]
            )
            return res.choices[0].message.content.strip()
        except Exception as e:
            return f"[AI解析报错: {e}]"

    def html_to_md(self, element):
        """递归将 BS4 元素转换为 Markdown"""
        if isinstance(element, Comment): return ""
        if isinstance(element, NavigableString): return element.string or ""

        tag = element.name
        # 预先处理子节点内容
        inner_md = "".join(self.html_to_md(c) for c in element.children)

        match tag:
            case 'h1' | 'h2' | 'h3': return f"\n{'#' * int(tag[1])} {inner_md}\n"
            case 'p': return f"\n{inner_md}\n"
            case 'strong' | 'b': return f"**{inner_md}**"
            case 'em' | 'i': return f"*{inner_md}*"
            case 'a': return f"[{inner_md}]({element.get('href', '#')})"
            case 'ul' | 'ol': return f"\n{inner_md}\n"
            case 'li':
                prefix = "1. " if element.parent.name == 'ol' else "* "
                return f"{prefix}{inner_md}\n"
            case 'pre': return f"\n```\n{element.get_text().strip()}\n```\n"
            case 'img':
                src = element.get('src', '')
                desc = self.analyze_img_with_ai(src)
                return f"\n![img]({src})\n> **AI解析**: {desc}\n"
            case 'table': return self._parse_table(element)
            case _: return inner_md

    def _parse_table(self, table):
        rows = []
        for tr in table.find_all('tr'):
            cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
            rows.append(f"| {' | '.join(cells)} |")
        if not rows: return ""
        sep = f"| {' | '.join(['---']*len(table.find('tr').find_all(['td','th'])))} |"
        rows.insert(1, sep)
        return "\n" + "\n".join(rows) + "\n"

    def process_menu_tree(self, nodes, current_path=[]):
        """递归遍历 JSON 菜单树"""
        for node in nodes:
            label = re.sub(r'[\\/:*?"<>|]', '-', node.get('label', 'unnamed'))
            new_path = current_path + [label]
            
            # 判断是否有子节点
            children = node.get('children', [])
            if children:
                # 递归子节点
                self.process_menu_tree(children, new_path)
            else:
                # 叶子节点，拼接 URL 并爬取
                target_url = f"{BASE_URL}/{node['belongToSysId']}/{node['id']}"
                self.scrape_page(target_url, new_path)

    def scrape_page(self, url, path_list):
        file_name = "-".join(path_list) + ".md"
        print(f">>> 正在同步: {file_name} (URL: {url})")
        
        self.driver.get(url)
        time.sleep(2) # 等待页面加载
        
        soup = BeautifulSoup(self.driver.page_source, 'lxml')
        content = soup.select_one(CONTENT_SELECTOR)
        
        if content:
            md_body = self.html_to_md(content)
            save_path = os.path.join(self.output_path, file_name)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(f"# {' / '.join(path_list)}\n\n{md_body}")

    def run(self):
        # 1. 加载配置
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            menu_data = json.load(f)

        # 2. 登录并同步 Cookie
        self.driver.get(LOGIN_URL)
        input(">>> 请在浏览器登录完成后，回到此处按回车...")
        self.sync_cookies()

        # 3. 开始递归处理
        self.process_menu_tree(menu_data)
        
        self.driver.quit()
        print(">>> 任务全部完成！")

if __name__ == "__main__":
    DocScraper().run()
