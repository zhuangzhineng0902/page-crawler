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
BASE_URL = "https://docs.example.com" # 仅用于登录和拼接规则的基础域名
LOGIN_URL = f"{BASE_URL}/login"
CONTENT_SELECTOR = "main.content-body" # 页面正文选择器
OUTPUT_DIR = "scraped_docs"

# OpenAI 配置
API_KEY = "your-api-key"
CUSTOM_BASE_URL = "https://your-proxy-domain.com/v1"

client = OpenAI(api_key=API_KEY, base_url=CUSTOM_BASE_URL)

class DocScraper:
    def __init__(self):
        if not os.path.exists(OUTPUT_DIR):
            os.makedirs(OUTPUT_DIR)
        
        # 初始化浏览器
        options = Options()
        self.driver = webdriver.Chrome(options=options)
        self.session = requests.Session()

    def sync_cookies(self):
        """将 Selenium 的登录态同步到 requests Session，确保下载图片有权限"""
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie['name'], cookie['value'])

    def get_image_base64(self, img_url):
        """下载图片并转为 Base64 流（img_url 已是完整路径）"""
        try:
            # 直接使用传入的完整 url 进行请求
            resp = self.session.get(img_url, timeout=10)
            if resp.status_code == 200:
                # 简单解析 MIME 类型
                ext = img_url.split('.')[-1].split('?')[0].lower()
                mime = f"image/{ext}" if ext in ['png','jpg','jpeg','gif','webp'] else "image/jpeg"
                b64 = base64.b64encode(resp.content).decode('utf-8')
                return f"data:{mime};base64,{b64}"
        except Exception as e:
            print(f"  [!] 图片下载失败: {img_url} -> {e}")
        return None

    def analyze_img_with_ai(self, img_url):
        """调用多模态大模型解析图片文件流"""
        b64_data = self.get_image_base64(img_url)
        if not b64_data: return "[无法读取图片内容]"
        
        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "请简要描述这张图片的内容，并提取其中的文字信息（如果有）。"},
                    {"type": "image_url", "image_url": {"url": b64_data}}
                ]}]
            )
            return res.choices[0].message.content.strip()
        except Exception as e:
            return f"[AI解析报错: {e}]"

    def html_to_md(self, element):
        """基于 beautifulsoup4 的递归标签映射逻辑"""
        if isinstance(element, Comment): return ""
        if isinstance(element, NavigableString): return element.string or ""

        tag = element.name
        # 预先递归处理所有子节点内容
        inner_md = "".join(self.html_to_md(c) for c in element.children)

        match tag:
            case 'h1' | 'h2' | 'h3': 
                return f"\n\n{'#' * int(tag[1])} {inner_md}\n"
            case 'p': 
                return f"\n\n{inner_md}\n"
            case 'strong' | 'b': 
                return f" **{inner_md}** "
            case 'em' | 'i': 
                return f" *{inner_md}* "
            case 'a': 
                return f" [{inner_md}]({element.get('href', '#')}) "
            case 'ul' | 'ol': 
                return f"\n{inner_md}\n"
            case 'li':
                prefix = "1. " if element.parent.name == 'ol' else "* "
                return f"{prefix}{inner_md}\n"
            case 'blockquote': 
                return f"\n> {inner_md.replace('\n', '\n> ')}\n"
            case 'pre': 
                return f"\n```\n{element.get_text().strip()}\n```\n"
            case 'code':
                return f"`{inner_md}`" if element.parent.name != 'pre' else inner_md
            case 'img':
                src = element.get('src', '')
                desc = self.analyze_img_with_ai(src) if src else "无图片地址"
                return f"\n\n![img]({src})\n> **AI 图片内容解析**: {desc}\n\n"
            case 'table': 
                return self._parse_table(element)
            case 'hr': 
                return "\n---\n"
            case 'br': 
                return "\n"
            case _: 
                return inner_md

    def _parse_table(self, table):
        """将 HTML 表格转换为标准的 Markdown 表格"""
        rows = []
        all_tr = table.find_all('tr')
        if not all_tr: return ""
        
        for tr in all_tr:
            cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
            rows.append(f"| {' | '.join(cells)} |")
        
        if len(rows) > 0:
            # 根据第一行的列数生成分隔线
            col_count = len(all_tr[0].find_all(['td', 'th']))
            sep = f"| {' | '.join(['---'] * col_count)} |"
            rows.insert(1, sep)
            
        return "\n" + "\n".join(rows) + "\n"

    def traverse_json(self, nodes, current_path=[]):
        """递归遍历 JSON 菜单树，处理叶子节点"""
        for node in nodes:
            label = re.sub(r'[\\/:*?"<>|]', '-', node.get('label', 'unnamed'))
            new_path = current_path + [label]
            
            children = node.get('children', [])
            if children:
                # 存在子节点，继续递归
                self.traverse_json(children, new_path)
            else:
                # 叶子节点，拼接 URL 规则: {baseurl}/{belongToSysId}/{id}
                target_url = f"{BASE_URL}/{node['belongToSysId']}/{node['id']}"
                self.scrape_page(target_url, new_path)

    def scrape_page(self, url, path_list):
        """访问页面并保存 Markdown"""
        file_name = "-".join(path_list) + ".md"
        print(f">>> 正在同步: {file_name}")
        
        try:
            self.driver.get(url)
            time.sleep(2) # 页面加载等待
            
            soup = BeautifulSoup(self.driver.page_source, 'lxml')
            content = soup.select_one(CONTENT_SELECTOR)
            
            if content:
                md_body = self.html_to_md(content)
                save_path = os.path.join(OUTPUT_DIR, file_name)
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(f"# {' / '.join(path_list)}\n\n")
                    f.write(f"原文地址: {url}\n\n---\n")
                    f.write(md_body)
            else:
                print(f"  [!] 未能找到内容容器: {url}")
        except Exception as e:
            print(f"  [!] 页面抓取失败: {url} -> {e}")

    def run(self):
        # 1. 登录并同步 Cookie
        self.driver.get(LOGIN_URL)
        input(">>> 请在浏览器登录完成后，回到此处按回车继续...")
        self.sync_cookies()

        # 2. 读取配置并执行递归
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            menu_data = json.load(f)
        
        self.traverse_json(menu_data)
        
        self.driver.quit()
        print(">>> 任务全部完成！")

if __name__ == "__main__":
    DocScraper().run()
