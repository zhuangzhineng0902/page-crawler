import os
import time
import requests
from bs4 import BeautifulSoup, NavigableString
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from openai import OpenAI

# ================= 配置区 =================
CHROME_DRIVER_PATH = '/path/to/chromedriver'  # 替换为你的驱动路径
BASE_URL = 'https://example.com'               # 网站主域名
LOGIN_URL = 'https://example.com/login'        # 登录页面
MENU_SELECTOR = 'nav.sidebar-nav'              # 左侧菜单栏的 CSS 选择器
CONTENT_SELECTOR = 'main.content'              # 正文内容的 CSS 选择器
API_KEY = "your-openai-api-key"                # 多模态模型 API Key
OUTPUT_DIR = "scraped_docs"

client = OpenAI(api_key=API_KEY)

# ================= 核心功能区 =================

def get_image_description(image_url):
    """调用大模型解析图片内容"""
    try:
        # 如果是相对路径则补全
        if not image_url.startswith('http'):
            image_url = requests.compat.urljoin(BASE_URL, image_url)
            
        response = client.chat.completions.create(
            model="gpt-4o-mini", # 或 gpt-4-vision-preview
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "描述图中的关键信息和文字"},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"解析失败: {e}"

def html_to_md(tag):
    """递归将 HTML 转换为 Markdown (映射逻辑)"""
    if isinstance(tag, NavigableString):
        return tag.strip()
    
    if tag is None: return ""

    # 获取子节点内容
    children_content = "".join([html_to_md(child) for child in tag.contents]).strip()
    
    name = tag.name
    if name in ['h1', 'h2', 'h3']:
        level = name[1]
        return f"\n\n{'#' * int(level)} {children_content}\n"
    elif name == 'p':
        return f"\n\n{children_content}\n"
    elif name in ['strong', 'b']:
        return f" **{children_content}** "
    elif name in ['em', 'i']:
        return f" *{children_content}* "
    elif name == 'a':
        return f" [{children_content}]({tag.get('href', '#')}) "
    elif name == 'ul':
        return f"\n{children_content}\n"
    elif name == 'ol':
        return f"\n{children_content}\n"
    elif name == 'li':
        prefix = "1. " if tag.parent.name == 'ol' else "* "
        return f"{prefix}{children_content}\n"
    elif name == 'blockquote':
        return f"\n> {children_content}\n"
    elif name == 'pre':
        code = tag.get_text()
        return f"\n```\n{code}\n```\n"
    elif name == 'img':
        src = tag.get('src', '')
        desc = get_image_description(src) if src else "无图片"
        return f"\n\n![image]({src})\n> **AI 解析**: {desc}\n\n"
    elif name in ['div', 'section', 'article', 'span']:
        return children_content
    return children_content

def sanitize(text):
    """清理文件名非法字符"""
    return "".join(c for c in text if c.isalnum() or c in ('-', '_')).strip()

def parse_menu(driver, menu_element, path_titles=[]):
    """递归解析左侧菜单树"""
    pages = []
    # 查找当前层级的 li
    items = menu_element.find_all('li', recursive=False)
    
    for item in items:
        link = item.find('a', recursive=False)
        if not link: continue
        
        title = sanitize(link.get_text(strip=True))
        url = link.get('href')
        new_path = path_titles + [title]
        
        if url and url != '#' and not url.startswith('javascript'):
            full_url = requests.compat.urljoin(BASE_URL, url)
            pages.append({'titles': new_path, 'url': full_url})
            
        # 查找子菜单 (假设在 ul 中)
        sub_menu = item.find('ul')
        if sub_menu:
            pages.extend(parse_menu(driver, sub_menu, new_path))
    return pages

# ================= 主程序 =================

def run():
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    
    driver = webdriver.Chrome()
    driver.get(LOGIN_URL)
    
    print(">>> 请在打开的浏览器中完成登录，完成后回到此处按回车...")
    input("--- 登录完成后请按回车继续 ---")
    
    # 解析菜单
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    menu_box = soup.select_one(MENU_SELECTOR)
    if not menu_box:
        print("未找到菜单栏，请检查 MENU_SELECTOR"); return
        
    all_tasks = parse_menu(driver, menu_box)
    print(f">>> 共发现 {len(all_tasks)} 个页面待抓取")

    for task in all_tasks:
        file_name = "-".join(task['titles']) + ".md"
        print(f"正在处理: {file_name}")
        
        driver.get(task['url'])
        time.sleep(2) # 等待渲染
        
        page_soup = BeautifulSoup(driver.page_source, 'html.parser')
        main_content = page_soup.select_one(CONTENT_SELECTOR)
        
        if main_content:
            md_result = html_to_md(main_content)
            with open(f"{OUTPUT_DIR}/{file_name}", "w", encoding="utf-8") as f:
                f.write(f"# {' > '.join(task['titles'])}\n\n")
                f.write(f"原文链接: {task['url']}\n\n---\n")
                f.write(md_result)
        
    driver.quit()
    print(">>> 抓取任务全部完成！")

if __name__ == "__main__":
    run()