import os
import re
import time
import requests
from bs4 import BeautifulSoup, Tag, NavigableString, Comment
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from openai import OpenAI

# ================= 配置区 =================
API_KEY = "your-api-key"
BASE_URL = 'https://docs.example.com'
LOGIN_URL = f"{BASE_URL}/login"
MENU_SELECTOR = 'aside.sidebar nav'     # 菜单选择器
CONTENT_SELECTOR = 'main.content-body'  # 正文选择器
OUTPUT_DIR = "markdown_docs"

client = OpenAI(
    api_key=API_KEY,
    base_url=CUSTOM_BASE_URL
)

class WebToMarkdownParser:
    def __init__(self):
        self.output_path = OUTPUT_DIR
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)

    def parse_image_with_ai(self, img_url):
        """调用多模态模型解析图片内容"""
        if not img_url: return ""
        try:
            # 补全相对路径
            full_img_url = requests.compat.urljoin(BASE_URL, img_url)
            response = client.chat.completions.create(
                model="gpt-4o-mini",  # 推荐使用 gpt-4o-mini，性价比极高
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "简要描述图片内容，并提取图片中的关键文字信息。"},
                        {"type": "image_url", "image_url": {"url": full_img_url}}
                    ]
                }],
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"[AI解析失败: {e}]"

    def handle_element(self, element):
        """递归处理 HTML 标签映射到 Markdown"""
        if isinstance(element, Comment): return ""
        if isinstance(element, NavigableString):
            return element.string if element.string else ""

        # 1. 递归获取子节点转换后的内容
        child_content = "".join(self.handle_element(child) for child in element.children)

        # 2. 映射逻辑
        tag = element.name
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
            case 'code':
                return f"`{child_content}`" if element.parent.name != 'pre' else child_content
            case 'pre': return f"\n```\n{child_content.strip()}\n```\n"
            case 'table': return self.convert_table(element)
            case 'img':
                src = element.get('src', '')
                ai_desc = self.parse_image_with_ai(src)
                return f"\n\n![image]({src})\n> **AI解析**: {ai_desc}\n\n"
            case 'hr': return "\n---\n"
            case _: return child_content # 其他如 div, span 直接透传子内容

    def convert_table(self, table):
        """处理表格映射"""
        rows = []
        for tr in table.find_all('tr'):
            cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
            rows.append(f"| {' | '.join(cells)} |")
        if not rows: return ""
        # 增加分割线
        sep = f"| {' | '.join(['---'] * len(table.find('tr').find_all(['td', 'th'])))} |"
        rows.insert(1, sep)
        return "\n" + "\n".join(rows) + "\n"

def main():
    options = Options()
    driver = webdriver.Chrome(options=options)
    parser = WebToMarkdownParser()

    # 1. 登录
    driver.get(LOGIN_URL)
    input(">>> 请在浏览器中完成登录，完成后回到终端按回车继续...")

    # 2. 抓取菜单树
    # 使用 BS4 解析当前登录后的 DOM
    soup = BeautifulSoup(driver.page_source, 'lxml')
    menu_nav = soup.select_one(MENU_SELECTOR)
    
    tasks = []
    def traverse_menu(root, current_path=[]):
        for li in root.find_all('li', recursive=False):
            a = li.find('a', recursive=False)
            if not a: continue
            
            title = re.sub(r'[\\/:*?"<>|]', '-', a.get_text(strip=True)) # 清理非法字符
            new_path = current_path + [title]
            url = a.get('href')
            
            if url and not url.startswith('#') and 'javascript' not in url:
                tasks.append({'path': new_path, 'url': requests.compat.urljoin(BASE_URL, url)})
            
            # 如果有嵌套的 ul 列表，则继续递归
            sub_ul = li.find('ul')
            if sub_ul: traverse_menu(sub_ul, new_path)

    if menu_nav:
        traverse_menu(menu_nav)
        print(f">>> 找到 {len(tasks)} 个有效链接")
    else:
        print(">>> 错误: 未能定位到菜单栏，请检查 MENU_SELECTOR")
        return

    # 3. 遍历链接并保存
    for task in tasks:
        file_name = "-".join(task['path']) + ".md"
        print(f">>> 正在同步: {file_name}")
        
        driver.get(task['url'])
        time.sleep(2) # 页面加载缓冲
        
        page_soup = BeautifulSoup(driver.page_source, 'lxml')
        content_element = page_soup.select_one(CONTENT_SELECTOR)
        
        if content_element:
            markdown_content = parser.handle_element(content_element)
            save_path = os.path.join(OUTPUT_DIR, file_name)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(f"# {' / '.join(task['path'])}\n")
                f.write(f"原文: {task['url']}\n\n---\n")
                f.write(markdown_content)
        
    driver.quit()
    print(">>> 任务全部完成！")

if __name__ == "__main__":
    main()
