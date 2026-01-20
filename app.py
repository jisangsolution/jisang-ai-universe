import os
import sys
import subprocess
import urllib.request
import io
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import pandas as pd

# [Step 0] 스마트 런처
def setup_environment():
    required = {
        "streamlit": "streamlit", 
        "plotly": "plotly", 
        "google-generativeai": "google.generativeai", 
        "python-dotenv": "dotenv", 
        "reportlab": "reportlab",
        "requests": "requests"
    }
    needs_install = []
    for pkg, mod in required.items():
        try: __import__(mod)
        except ImportError: needs_install.append(pkg)
    if needs_install:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U"] + needs_install)
        os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", __file__])

    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path) or os.path.getsize(font_path) < 100:
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try: urllib.request.urlretrieve(url, font_path)
        except: pass

if "streamlit" not in sys.modules:
    setup_environment()
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", __file__]
    sys.exit(stcli.main())

import streamlit as st
import google.generativeai as genai
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

# API Keys Load
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] Kakao Geocoding & Context
# --------------------------------------------------------------------------------
def get_codes_from_kakao(address):
    if not kakao_key: return None, None, None, None, None, None, "API Key Missing"
    
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    params = {"query": address}
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=5)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                # 좌표 및 기본 행정정보
                lat, lon = float(docs[0]['y']), float(docs[0]['x'])
                b_code = docs[0]['address']['b_code']
                h_code = docs[0]['address']['h_code'] # 행정동 코드 추가
                
                # 상세 주소 분해
                region_1 = docs[0]['address']['region_1depth_name'] # 도/시 (예: 경기도)
                region_2 = docs[0]['address']['region_2depth_name'] # 시/군/구 (예: 김포시)
                region_3 = docs[0]['address']['region_3depth_name'] # 읍면동 (예: 통진읍)
                
                sigungu, bjdong = b_code[:5], b_code[5:]
                main_no = docs[0]['address']['main_address_no']
                sub_no = docs[0]['address']['sub_address_no']
                bun = main_no.zfill(4)
                ji = sub_no.zfill(4) if sub_no else "0000"
                
                # 지역 정보 패키징
                loc_info = {
                    "si": region_1,
                    "gu": region_2,
                    "dong": region_3
                }
                
                return sigungu, bjdong, bun, ji, (lat, lon), loc_info, "Success"
            return None, None, None, None, None, None, "주소 미확인"
        return None, None, None, None, None, None, f"Error {resp.status_code}"
    except Exception as e: return None, None, None, None, None, None, str(e)

# --------------------------------------------------------------------------------
# [Engine 2] Gov Data Connector (Building)
# --------------------------------------------------------------------------------
class RealDataConnector:
    def __init__(self, service_key):
        self.service_key = service_key
        self.base_url = "http://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo"

    def get_building_info(self, sigungu_cd, bjdong_cd, bun, ji):
        if not self.service_key: return {"status": "error", "msg": "API Key Missing"}
        
        key_to_use = requests.utils.unquote(self.service_key)
        params = {
            "serviceKey": key_to_use, "sigunguCd": sigungu_cd, "bjdongCd": bjdong_cd,
            "bun": bun, "ji": ji, "numOfRows": 1, "pageNo": 1
        }
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            if response.status_code == 200:
                try:
                    root = ET.fromstring(response.content)
                    item = root.find('.//item')
                    if item is not None:
                        return {
                            "status": "success",
                            "주용도": item.findtext("mainPurpsCdNm") or "미지정",
                            "연면적": item.findtext("totArea") or "0",
                            "사용승인일": item.findtext("useAprDay") or "-",
                            "구조": item.findtext("strctCdNm") or "-",
                            "위반여부": "위반" if item.findtext("otherConst") else "정상"
                        }
                    return {"status": "nodata", "msg": "토지 상태 (건물 없음)"}
                except: return {"status": "error", "msg": "XML Parsing Error"}
            elif response.status_code == 500: return {"status": "nodata", "msg": "데이터 미존재"}
            else: return {"status": "error", "msg": f"Server Error {response.status_code}"}
        except Exception as e: return {"status": "error", "msg": str(e)}

# --------------------------------------------------------------------------------
# [Engine 3] AI Legal & Land Analyst (The Unicorn Core)
# --------------------------------------------------------------------------------
def get_comprehensive_analysis(address, loc_info, building_data):
    if not api_key: return "Google API 키가 설정되지 않았습니다."
    
    model = genai.GenerativeModel('gemini-pro')
    
    # 건물 정보가 있는지 여부에 따라 맥락 설정
    building_context = ""
    if building_data['status'] == 'success':
        building_context = f"현재 건물 있음. 용도: {building_data['주용도']}, 연면적: {building_data['연면적']}m2."
    else:
        building_context = "현재 건물 없음(나대지 상태). 신축 개발 관점에서 분석 필요."

    # 프롬프트: 법률 및 조례 데이터베이스 역할 수행
    prompt = f"""
    당신은 대한민국 최고의 '부동산 공법 전문가'이자 'AI 도시계획가'입니다.
    대상 주소: {address} ({loc_info['si']} {loc_info['gu']} {loc_info['dong']})
    상태: {building_context}

    아래의 [필수 분석 항목]을 해당 지자체({loc_info['gu']})의 최신 **도시계획조례** 및 **건축조례**에 기반하여 정밀 분석하고,
    마크다운(Markdown) 표와 리스트 형식으로 깔끔하게 보고해 주세요.

    [필수 분석 항목]
    1. **기본 토지 정보 추정**:
       - 예상 용도지역 (예: 계획관리지역, 제2종일반주거지역 등 - 주소지 특성에 맞춰 추론)
       - 예상 공시지가 수준 (주변 시세 기반 추정치)
       
    2. **법적 규제 분석 ({loc_info['gu']} 조례 기준)**:
       - **건폐율(BCR)**: 법적 상한 및 조례 상한 (%)
       - **용적률(FAR)**: 법적 상한 및 조례 상한 (%)
       - **지구단위계획**: 해당 여부 및 특이사항 가능성
       - **규제 사항**: 군사시설보호구역, 비행안전구역, 개발행위허가 제한 여부 등 확인

    3. **건축 가능성 (Allowable Uses)**:
       - 허용 용도: (예: 단독주택, 제1/2종 근린생활시설, 공장, 창고 등)
       - 불허 용도: (해당 용도지역에서 건축 불가능한 시설)
       - **주차장 조례**: 부설주차장 설치 기준 (예: 134m2당 1대 등)

    4. **최적 개발 솔루션 (Solution)**:
       - 해당 입지에서 가장 수익성이 높은 개발 방식 제안 (3줄 요약)
       - 투자 주의사항 (Risk Check)

    *답변은 전문가처럼 명확한 수치와 법적 근거를 들어 작성하세요.*
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 정밀 분석 중 오류 발생: {str(e)}"

# --------------------------------------------------------------------------------
# [UI] Dashboard
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Universe", page_icon="🦄", layout="wide")

# CSS Styling
st.markdown("""
<style>
    .metric-card {background-color: #f0f2f6; padding: 20px; border-radius: 10px; margin-bottom: 10px;}
    .info-box {background-color: #e8f4f8; padding: 15px; border-radius: 5px; border-left: 5px solid #00a8cc;}
    .warning-box {background-color: #fff3cd; padding: 15px; border-radius: 5px; border-left: 5px solid #ffc107;}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🦄 지상 AI")
    st.caption("부동산 종합 솔루션 (Unicorn Edt.)")
    st.markdown("---")
    addr_input = st.text_input("주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    if st.button("🚀 종합 정밀 분석 실행", type="primary", use_container_width=True):
        st.session_state['run'] = True
        st.session_state['addr'] = addr_input
    
    st.markdown("---")
    st.info("💡 **Tip:** 토지이용계획, 건축법, 조례, 사업성 분석을 한 번에 수행합니다.")

st.title("지상 AI 부동산 종합 분석 시스템")

if st.session_state.get('run'):
    target = st.session_state['addr']
    
    with st.status("🔍 유니버스 데이터 파이프라인 가동...", expanded=True) as status:
        st.write("1. 🛰️ 위성/행정 데이터 수집 (Kakao API)...")
        sigungu, bjdong, bun, ji, coords, loc_info, msg = get_codes_from_kakao(target)
        
        if sigungu:
            # 1. Map Display
            st.write("2. 📍 위치 기반 GIS 분석...")
            col_map, col_info = st.columns([2, 1])
            with col_map:
                if coords:
                    st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=16, use_container_width=True)
            
            # 2. Building Data
            st.write("3. 🏢 건축물대장 및 소유권 분석 (Gov24)...")
            connector = RealDataConnector(data_go_key)
            real_data = connector.get_building_info(sigungu, bjdong, bun, ji)
            
            # 3. AI Analysis
            st.write("4. ⚖️ 법률/조례/사업성 정밀 분석 (Gemini Pro)...")
            ai_report = get_comprehensive_analysis(target, loc_info, real_data)
            
            status.update(label="분석 완료! (All Systems Go
