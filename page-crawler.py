import os
import re
import time
import base64
import requests
from bs4 import BeautifulSoup, Tag, NavigableString, Comment
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from openai import OpenAI

# ================= 配置区 =================
# OpenAI 客户端配置
API_KEY = "your-api-key"
CUSTOM_BASE_URL = "https://your-proxy-domain.com/v1" # 自定义 URL

# 网页选择器配置
BASE_URL = 'https://docs.example.com'
LOGIN_URL = f"{BASE_URL}/login"
MENU_SELECTOR = 'aside.sidebar nav'     # 菜单选择器
CONTENT_SELECTOR = 'main.content-body'  # 正文选择器
OUTPUT_DIR = "markdown_docs"

# 初始化 OpenAI 客户端
client = OpenAI(
    api_key=API_KEY,
    base_url=CUSTOM_BASE_URL
)

class WebToMarkdownParser:
    def __init__(self, session):
        self.session = session # 共享爬虫的 Session 以保持登录状态

    def encode_image_to_base64(self, img_url):
        """下载图片并转换为 Base64 文件流"""
        try:
            # 补全相对路径
            full_url = requests.compat.urljoin(BASE_URL, img_url)
            # 使用带 Cookie 的 session 下载图片
            response = self.session.get(full_url, timeout=10)
            if response.status_code == 200:
                # 获取图片后缀名（简单处理）
                ext = img_url.split('.')[-1].lower()
                mime_type = f"image/{ext}" if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp'] else "image/jpeg"
                base64_data = base64.b64encode(response.content).decode('utf-8')
                return f"data:{mime_type};base64,{base64_data}"
        except Exception as e:
            print(f"图片下载失败: {e}")
        return None

    def parse_image_with_ai(self, img_url):
        """将图片文件流发送给大模型"""
        base64_image = self.encode_image_to_base64(img_url)
        if not base64_image:
            return "[图片解析失败：无法获取图片文件流]"

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请描述这张图片的内容，并提取其中的关键文字。"},
                        {
                            "type": "image_url",
                            "image_url": {"url": base64_image} # 这里传入的是 base64 数据流
                        }
                    ]
                }],
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"[AI解析报错: {e}]"

    def handle_element(self, element):
        """递归处理 HTML 到 Markdown 的映射 (基于 beautifulsoup4)"""
        if isinstance(element, Comment): return ""
        if isinstance(element, NavigableString):
            return element.string if element.string else ""

        # 递归获取子节点内容
        child_content = "".join(self.handle_element(child) for child in element.children)

        tag = element.name
        # 完整的标签映射矩阵
        match tag:
            case 'h1': return f"\n# {child_content}\n"
            case 'h2': return f"\n## {child_content}\n"
            case 'h3': return f"\n### {child_content}\n"
            case 'p': return f"\n{child_content}\n"
            case 'strong' | 'b': return f"**{child_content}**"
            case 'em' | 'i': return f"*{child_content}*"
            case 'a': return f"[{child_content}]({element.get('href', '#')})"
            case 'li':
                prefix = "1. " if element.parent.name == 'ol' else "* "
                return f"{prefix}{child_content}\n"
            case 'ul' | 'ol': return f"\n{child_content}\n"
            case 'blockquote': return f"\n> {child_content.replace('\n', '\n> ')}\n"
            case 'pre': return f"\n```\n{child_content.strip()}\n```\n"
            case 'code':
                return f"`{child_content}`" if element.parent.name != 'pre' else child_content
            case 'img':
                src = element.get('src', '')
                ai_desc = self.parse_image_with_ai(src)
                return f"\n\n![image]({src})\n> **AI 图片内容解析**: {ai_desc}\n\n"
            case 'table': return self.convert_table(element)
            case 'hr': return "\n---\n"
            case 'br': return "\n"
            case _: return child_content

    def convert_table(self, table):
        """表格转换"""
        rows = []
        for tr in table.find_all('tr'):
            cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
            rows.append(f"| {' | '.join(cells)} |")
        if not rows: return ""
        sep = f"| {' | '.join(['---'] * len(table.find('tr').find_all(['td', 'th'])))} |"
        rows.insert(1, sep)
        return "\n" + "\n".join(rows) + "\n"

def main():
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    
    # 1. 启动 Selenium 
    driver = webdriver.Chrome()
    driver.get(LOGIN_URL)
    input(">>> 请在浏览器中完成登录，完成后回到终端按回车...")

    # 2. 将 Selenium 的 Cookie 同步给 Requests (用于下载图片)
    session = requests.Session()
    for cookie in driver.get_cookies():
        session.cookies.set(cookie['name'], cookie['value'])
    
    parser = WebToMarkdownParser(session)

    # 3. 抓取菜单树
    soup = BeautifulSoup(driver.page_source, 'lxml')
    menu_nav = soup.select_one(MENU_SELECTOR)
    
    tasks = []
    def traverse_menu(root, current_path=[]):
        for li in root.find_all('li', recursive=False):
            a = li.find('a', recursive=False)
            if not a: continue
            
            # 清理文件名非法字符
            title = re.sub(r'[\\/:*?"<>|]', '-', a.get_text(strip=True))
            new_path = current_path + [title]
            url = a.get('href')
            
            if url and not url.startswith('#') and 'javascript' not in url:
                tasks.append({'path': new_path, 'url': requests.compat.urljoin(BASE_URL, url)})
            
            sub_ul = li.find('ul')
            if sub_ul: traverse_menu(sub_ul, new_path)

    if menu_nav:
        traverse_menu(menu_nav)
    else:
        print("未定位到菜单，请检查 MENU_SELECTOR"); return

    # 4. 遍历并生成 Markdown
    for task in tasks:
        file_name = "-".join(task['path']) + ".md"
        print(f">>> 正在同步: {file_name}")
        
        driver.get(task['url'])
        time.sleep(2) # 页面加载等待
        
        page_soup = BeautifulSoup(driver.page_source, 'lxml')
        content_element = page_soup.select_one(CONTENT_SELECTOR)
        
        if content_element:
            markdown_content = parser.handle_element(content_element)
            with open(os.path.join(OUTPUT_DIR, file_name), "w", encoding="utf-8") as f:
                f.write(f"# {' / '.join(task['path'])}\n\n")
                f.write(markdown_content)

    driver.quit()
    print(">>> 任务完成！")

if __name__ == "__main__":
    main()
