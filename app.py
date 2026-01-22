import os
import sys
import subprocess
import requests
import pandas as pd
import streamlit as st
from urllib.parse import unquote
import xml.etree.ElementTree as ET

# [Step 0] 환경 설정 (라이브러리 강제 업데이트 포함)
def setup_environment():
    required_packages = ["streamlit", "google-generativeai", "requests", "pandas", "plotly"]
    for pkg in required_packages:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            # 강제 업그레이드 옵션 추가
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", pkg])

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

# [Step 1] API 키 로드
def get_clean_key(key_name):
    raw_key = st.secrets.get(key_name, "")
    if not raw_key: return None
    if "%" in raw_key: return unquote(raw_key)
    return raw_key

# 키 로드
api_key = get_clean_key("GOOGLE_API_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY", "")
law_id = st.secrets.get("LAW_USER_ID", "")
law_key = st.secrets.get("LAW_API_KEY", "")

if api_key:
    genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 법령 파싱 엔진 (국가법령정보센터)
# --------------------------------------------------------------------------------
class LegalEngine:
    @staticmethod
    def get_ordinance(region, keyword):
        # 키가 설정되어 있는지 확인
        if not law_id or not law_key:
            return "🔒 법령 API 키가 설정되지 않아 AI가 추론합니다."
            
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
                root = ET.fromstring(response.content)
                law_list = []
                # XML 파싱 로직 안전장치
                for child in root.findall(".//law"):
                    try:
                        name = child.find("법령명한글").text
                        link = child.find("법령상세링크").text
                        law_list.append(f"- [{name}]({link})")
                    except: continue
                
                if law_list:
                    return "\n".join(law_list[:3])
                else:
                    return "관련 조례 검색 결과가 없습니다."
        except Exception as e:
            return f"법령 서버 연결 대기 중 ({str(e)})"
        
        return "법령 데이터 확인 중"

# --------------------------------------------------------------------------------
# [Engine 2] 데이터 수집 엔진
# --------------------------------------------------------------------------------
class DataEngine:
    @staticmethod
    def get_location(address):
        if not kakao_key: return None, None, "카카오 키 없음"
        try:
            url = "https://dapi.kakao.com/v2/local/search/address.json"
            headers = {"Authorization": f"KakaoAK {kakao_key}"}
            resp = requests.get(url, headers=headers, params={"query": address}, timeout=3)
            if resp.status_code == 200:
                docs = resp.json().get('documents')
                if docs:
                    addr = docs[0]['address']
                    coords = (float(docs[0]['y']), float(docs[0]['x']))
                    # 지역명 2단계 (예: 김포시, 강남구)
                    region = addr.get('region_2depth_name', '')
                    if not region: region = addr.get('region_1depth_name', '')
                    return region, coords, addr
        except: pass
        return None, None, "위치 검색 실패"

# --------------------------------------------------------------------------------
# [Engine 3] AI 융합 분석 (Stable Model)
# --------------------------------------------------------------------------------
def generate_legal_insight(addr, region, law_data):
    if not api_key: return "⚠️ Google API 키가 필요합니다."
    
    # [수정됨] 가장 안정적인 'gemini-pro' 모델 사용
    try:
        model = genai.GenerativeModel('gemini-pro')
    except:
        return "AI 모델 로드 실패. 잠시 후 다시 시도해주세요."
    
    prompt = f"""
    당신은 대한민국 최고의 부동산 법률 전문가입니다.
    
    [분석 대상] {addr} ({region})
    [법령 데이터] {law_data}
    
    위 데이터를 바탕으로 투자자를 위한 핵심 리포트를 3가지로 요약해줘:
    1. 📜 **적용 조례 확인**: '{region} 도시계획조례'를 기준으로 판단할 것.
    2. 🏗️ **건축 제한 분석**: 해당 지역의 일반적인 용도지역(예: 계획관리, 자연녹지 등)을 추론하고 건폐율/용적률 상한 설명.
    3. 💰 **수익화 전략**: 이 땅에 카페나 창고를 지을 때의 법적 유불리 판단.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 분석 중 오류 발생: {str(e)}"

# --------------------------------------------------------------------------------
# [UI] 지상 AI Ver 14.1
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Legal", layout="wide", page_icon="⚖️")

st.markdown("""
<style>
    .law-box { background-color: #f8f9fa; padding: 15px; border-radius: 5px; border: 1px solid #ddd; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("⚖️ Jisang AI")
    st.caption("Ver 14.1 (Stable Engine)")
    addr_input = st.text_input("주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    if st.
