import os
import sys
import subprocess
import time
import requests
import pandas as pd
import streamlit as st
from urllib.parse import unquote
import xml.etree.ElementTree as ET

# [Step 0] 환경 설정 (무결성 확보)
def setup_environment():
    required_packages = ["streamlit", "google-generativeai", "requests", "pandas", "plotly"]
    for pkg in required_packages:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
            print(f"Installed {pkg}")

    # 한글 폰트 안전 확보
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try:
            urllib.request.urlretrieve(url, font_path)
        except:
            pass

# 모듈 로딩 전 환경 점검
if "streamlit" not in sys.modules:
    setup_environment()

import google.generativeai as genai

# [Step 1] API 키 로드 (안전 장치 적용)
def get_clean_key(key_name):
    raw_key = st.secrets.get(key_name, "")
    if not raw_key:
        return None
    if "%" in raw_key:
        return unquote(raw_key)
    return raw_key

# Secrets 로드
api_key = get_clean_key("GOOGLE_API_KEY")
land_go_key = get_clean_key("LAND_GO_KR_KEY")
data_go_key = get_clean_key("DATA_GO_KR_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY", "")
vworld_key = st.secrets.get("VWORLD_API_KEY", "")

if api_key:
    genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 불사신 데이터 엔진 (API + AI Failover)
# --------------------------------------------------------------------------------
class ImmortalDataEngine:
    
    @staticmethod
    def get_location(address):
        """카카오 API로 좌표 및 PNU 획득 (가장 안정적)"""
        if not kakao_key:
            return None, None, "카카오 키 설정 필요"
        
        try:
            url = "https://dapi.kakao.com/v2/local/search/address.json"
            headers = {"Authorization": f"KakaoAK {kakao_key}"}
            resp = requests.get(url, headers=headers, params={"query": address}, timeout=3)
            
            if resp.status_code == 200:
                docs = resp.json().get('documents')
                if docs:
                    addr = docs[0]['address']
                    b_code = addr['b_code']
                    mount = "2" if addr.get('mountain_yn') == 'Y' else "1"
                    main = addr['main_address_no'].zfill(4)
                    sub = addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else "0000"
                    
                    pnu = f"{b_code}{mount}{main}{sub}"
                    coords = (float(docs[0]['y']), float(docs[0]['x']))
                    return pnu, coords, addr
                    
            return None, None, "주소 검색 결과 없음"
        except Exception as e:
            return None, None, f"통신 오류: {str(e)}"

    @staticmethod
    def get_land_data_hybrid(pnu, address):
        """
        국토부 API 시도 -> 실패 시 AI 추론 데이터 반환 (중단 없는 서비스)
        """
        # 1. 국토부 API 시도
        target_key = land_go_key or data_go_key
        if target_key:
            try:
                url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
                # 인코딩/디코딩 키 모두 시도 (호환성 확보)
                keys_to_try
