import os
import sys
import subprocess
import requests
import pandas as pd
import streamlit as st
from urllib.parse import unquote
import xml.etree.ElementTree as ET

# --------------------------------------------------------------------------------
# [Step 0] 환경 설정 및 라이브러리 강제 업데이트
# --------------------------------------------------------------------------------
def setup_environment():
    # 필수 패키지 목록
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
            # 패키지가 없으면 강제 설치
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

    # 한글 폰트 설치 (나눔고딕)
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try:
            urllib.request.urlretrieve(url, font_path)
        except:
            pass

# Streamlit 실행 전 환경 점검
if "streamlit" not in sys.modules:
    setup_environment()

import google.generativeai as genai

# --------------------------------------------------------------------------------
# [Step 1] API 키 로드 (Secrets 관리)
# --------------------------------------------------------------------------------
def get_clean_key(key_name):
    """Secrets에서 키를 안전하게 가져오는 함수"""
    raw_key = st.secrets.get(key_name, "")
    if not raw_key:
        return None
    if "%" in raw_key:
        return unquote(raw_key)
    return raw_key

# 각종 API 키 로드
api_key = get_clean_key("GOOGLE_API_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY", "")
law_id = st.secrets.get("LAW_USER_ID", "")
law_key = st.secrets.get("LAW_API_KEY", "")

# Google AI 설정
if api_key:
    genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 법령 파싱 엔진 (국가법령정보센터)
# --------------------------------------------------------------------------------
class LegalEngine:
    @staticmethod
    def get_ordinance(region, keyword):
        """지역명과 키워드로 조례를 검색"""
        
        # 키가 없으면 AI 추론 모드로 전환
        if not law_id or not law_key:
            return "🔒 법령 API 키가 설정되지 않았습니다. (AI 추론 모드로 진행)"
            
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
                
                # XML 파싱 (에러 방지를 위한 예외처리 포함)
                for child in root.findall(".//law"):
                    try:
                        name = child.find("법령명한글").text
                        link = child.find("법령상세링크").text
                        law_list.append(f"- [{name}]({link})")
                    except:
                        continue
                
                if law_list:
                    # 상위 3개 결과만 반환
                    return "\n".join(law_list[:3])
                else:
                    return "관련 조례 검색 결과가 없습니다."
                    
        except Exception as e:
            return f"법령 서버 연결 실패 ({str(e)})"
        
        return "데이터 확인 중"

# --------------------------------------------------------------------------------
# [Engine 2] 위치 및 데이터 수집 엔진
# --------------------------------------------------------------------------------
class DataEngine:
    @staticmethod
    def get_location(address):
        """주소를 좌표와 지역명으로 변환"""
        if not kakao_key:
            return None, None, "카카오 API 키가 없습니다."
            
        try:
            url = "https://dapi.kakao.com/v2/local/search/address.json"
            headers = {"Authorization": f"KakaoAK {kakao_key}"}
            resp = requests.get(url, headers=headers, params={"query": address}, timeout=3)
            
            if resp.status_code == 200:
                docs = resp.json().get('documents')
                if docs:
                    addr = docs[0]['address']
                    coords = (float(docs[0]['y']), float(docs[0]['x']))
                    
                    # 지역명 추출 (2단계 우선, 없으면 1단계)
                    region = addr.get('region_2depth_name', '')
                    if not region:
                        region = addr.get('region_1depth_name', '')
                        
                    return region, coords, addr
                    
        except:
            pass
            
        return None, None, "위치 검색 실패"

# --------------------------------------------------------------------------------
# [Engine 3] AI 융합 분석 엔진 (모델 호환성 개선)
# --------------------------------------------------------------------------------
def generate_legal_insight(addr, region, law_data):
    if not api_key:
        return "⚠️ Google AI API 키가 설정되지 않았습니다."
    
    # [중요] 호환성이 가장 좋은 'gemini-pro' 모델 사용
    try:
        model = genai.GenerativeModel('gemini-pro')
    except:
        return "AI 모델 로드 실패. 잠시 후 다시 시도해주세요."
    
    prompt = f"""
    당신은 대한민국 최고의 부동산 법률 분석가입니다.
    
    [분석 대상]
    주소: {addr}
    관할 지역: {region}
    
    [참고 조례 데이터]
    {law_data}
    
    위 데이터를 바탕으로 투자자를 위한 핵심 전략 리포트를 작성하세요.
    (조례 데이터가 부족할 경우, 해당 지역의 통상적인 용도지역 규제를 추론하여 답변하세요.)
    
    1. 📜 **적용 조례 확인**: '{region} 도시계획조례' 기준 분석.
    2. 🏗️ **건축 제한 분석**: 건폐율/용적률 상한선 및 건축 가능한 용도 추천.
    3. 💰 **수
