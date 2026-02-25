import base64
import requests
from openai import OpenAI

# ================= 诊断配置区 =================
# 请确保与 Cherry Studio 中的配置完全一致
API_KEY = "你的API_KEY"
# 注意：有些代理需要带 /v1，有些不需要。
# 如果 Cherry Studio 是 https://api.proxy.com，这里也保持一致。
BASE_URL = "https://your-proxy-domain.com/v1" 
MODEL_NAME = "gpt-4o-mini"
TEST_IMAGE_URL = "https://example.com/test.jpg" # 换成一个你确认能访问的图

# ================= 诊断逻辑 =================

def test_api_diagnose(img_url):
    print(f"1. 开始测试 URL: {img_url}")
    
    # 初始化客户端
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    
    # 步骤 A: 下载并转码
    try:
        resp = requests.get(img_url, timeout=10)
        resp.raise_for_status()
        
        # 自动识别 MIME 类型
        ext = img_url.split('.')[-1].split('?')[0].lower()
        mime_type = f"image/{ext}" if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp'] else "image/jpeg"
        
        # 关键点：构造 Base64 流
        base64_data = base64.b64encode(resp.content).decode('utf-8')
        full_base64_string = f"data:{mime_type};base64,{base64_data}"
        
        print(f"2. 图片下载成功，MIME类型: {mime_type}")
        print(f"   Base64 字符串前50位: {full_base64_string[:50]}...")
    except Exception as e:
        print(f"❌ 步骤 A 失败（图片下载或转码）: {e}")
        return

    # 步骤 B: 调用 API
    print(f"3. 正在请求模型: {MODEL_NAME} (Base URL: {BASE_URL})")
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这张图片里有什么？"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": full_base64_string, # 传入 Base64 流
                                "detail": "low"           # 强制低精度模式，减少数据量，提高成功率
                            }
                        },
                    ],
                }
            ],
            max_tokens=100
        )
        print("✅ 步骤 B 成功！API 返回结果:")
        print("-" * 30)
        print(response.choices[0].message.content)
        print("-" * 30)
        
    except Exception as e:
        print(f"❌ 步骤 B 失败（API 调用）")
        print(f"   报错详情: {type(e).__name__}: {str(e)}")
        
        # 特殊诊断
        if "404" in str(e):
            print("💡 诊断提示：404 错误通常是 BASE_URL 路径不对，请检查是否多写或少写了 '/v1'")
        elif "400" in str(e):
            print("💡 诊断提示：400 错误通常是图片格式不被支持或 Base64 字符串过长。尝试换个小图测试。")
        elif "401" in str(e):
            print("💡 诊断提示：401 错误说明 API_KEY 无效或过期。")

if __name__ == "__main__":
    test_api_diagnose(TEST_IMAGE_URL)
