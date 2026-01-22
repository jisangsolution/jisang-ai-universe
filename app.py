import os
import sys
import subprocess
import requests
import pandas as pd
import streamlit as st
from urllib.parse import unquote
import xml.etree.ElementTree as ET

# --------------------------------------------------------------------------------
# [Step 0] 환경 설정 및 라이브러리 검증
# --------------------------------------------------------------------------------
def setup_environment():
    required_packages = [
        "streamlit", 
        "google-generativeai", 
        "requests", 
        "pandas", 
        "plotly"
    ]
    
    for pkg in required_packages:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

    # 폰트 설정
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try:
            urllib.request.urlretrieve(url, font_path)
        except:
            pass

if "streamlit" not in sys.modules:
    setup_environment()

import google.generativeai as genai

# --------------------------------------------------------------------------------
# [Step 1] API 키 로드 (안전성 강화)
# --------------------------------------------------------------------------------
def get_clean_key(key_name):
    try:
        raw_key = st.secrets.get(key_name, "")
        if not raw_key:
            return None
        if "%" in raw_key:
            return unquote(raw_key)
        return raw_key
    except:
        return None

# 키 로드
api_key = get_clean_key("GOOGLE_API_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY", "")
law_id = st.secrets.get("LAW_USER_ID", "")
law_key = st.secrets.get("LAW_API_KEY", "")

# Google AI 설정 (Gemini-Pro 사용)
if api_key:
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        st.error(f"API 설정 오류: {e}")

# --------------------------------------------------------------------------------
# [Engine 1] 법령 파싱 엔진 (오류 방지 로직 적용)
# --------------------------------------------------------------------------------
class LegalEngine:
    @staticmethod
    def get_ordinance(region, keyword):
        # 키 미설정 시 방어 로직
        if not law_id or not law_key:
            return "🔒 법령 API 키 미설정 (AI 추론 모드로 진행)"
            
        url = "http://www.law.go.kr/DRF/lawSearch.do"
        params = {
            "OC": law_id,
            "target": "ordin",
            "type": "XML",
            "query": f"{region} {keyword}"
        }
        
        try:
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                try:
                    root = ET.fromstring(response.content)
                    law_list = []
                    
                    for child in root.findall(".//law"):
                        try:
                            name = child.find("법령명한글").text
                            link = child.find("법령상세링크").text
                            law_list.append(f"- [{name}]({link})")
                        except:
                            continue
                    
                    if law_list:
                        return "\n".join(law_list[:3])
                    else:
                        return "관련 조례 검색 결과가 없습니다."
                except:
                    return "데이터 파싱 중 오류 발생"
                    
        except Exception as e:
            return f"법령 서버 연결 실패 ({str(e)})"
        
        return "데이터 확인 중"

# --------------------------------------------------------------------------------
# [Engine 2] 위치 데이터 엔진
# --------------------------------------------------------------------------------
class DataEngine:
    @staticmethod
    def get_location(address):
        if not kakao_key:
            return None, None, "카카오 API 키 필요"
            
        try:
            url = "https://dapi.kakao.com/v2/local/search/address.json"
            headers = {"Authorization": f"KakaoAK {kakao_key}"}
            resp = requests.get(url, headers=headers, params={"query": address}, timeout=3)
            
            if resp.status_code == 200:
                docs = resp.json().get('documents')
                if docs:
                    addr = docs[0]['address']
                    coords = (float(docs[0]['y']), float(docs[0]['x']))
                    
                    # 지역명 추출 로직 단순화
                    region = addr.get('region_2depth_name', '')
                    if not region:
                        region = addr.get('region_1depth_name', '')
                        
                    return region, coords, addr
        except:
            pass
            
        return None, None, "위치 검색 실패"

# --------------------------------------------------------------------------------
# [Engine 3] AI 융합 분석 (Gemini-Pro Stable)
# --------------------------------------------------------------------------------
def generate_legal_insight(addr, region, law_data):
    if not api_key:
        return "⚠️ Google AI API 키가 설정되지 않았습니다."
    
    # [수정] 가장 안정적인 모델로 고정
    try:
        model
