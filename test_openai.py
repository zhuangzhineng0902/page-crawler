import requests
import json

# --- 严格对照 Cherry Studio 的设置 ---
API_KEY = "你的API_KEY"
# 尝试不同的路径组合：1. 带/v1  2. 不带/v1
BASE_URL = "https://your-proxy-domain.com/v1" 

def diagnostic_request():
    url = f"{BASE_URL}/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {API_KEY.strip()}", # 确保去掉首尾空格
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hi"}]
    }

    print(f"请求地址: {url}")
    print(f"Header预览: Authorization: Bearer {API_KEY[:10]}...")

    try:
        response = requests.post(url, headers=headers, json=payload)
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ 原生请求成功！说明是 OpenAI SDK 配置问题。")
            print(response.json()['choices'][0]['message']['content'])
        else:
            print(f"❌ 请求失败。返回内容: {response.text}")
            
    except Exception as e:
        print(f"❌ 网络异常: {e}")

if __name__ == "__main__":
    diagnostic_request()
