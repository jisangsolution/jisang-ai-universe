import os
import sys
import subprocess
import urllib.request
import io
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import pandas as pd
import streamlit as st

# [Step 0] 환경 설정
def setup_environment():
    required = ["streamlit", "google-generativeai", "requests", "reportlab"]
    for pkg in required:
        try: __import__(pkg.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
            os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", __file__])

if "streamlit" not in sys.modules:
    setup_environment()

import google.generativeai as genai

# API Keys
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")   
land_go_key = st.secrets.get("LAND_GO_KR_KEY")   
kakao_key = st.secrets.get("KAKAO_API_KEY")
vworld_key = st.secrets.get("VWORLD_API_KEY") # 신규 추가

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 주소 마스터 (PNU 생성)
# --------------------------------------------------------------------------------
def get_pnu_and_coords(address):
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    try:
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=5)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                addr = docs[0]['address']
                b_code = addr['b_code']
                mount_cd = "2" if addr.get('mountain_yn') == 'Y' else "1"
                pnu = f"{b_code}{mount_cd}{addr['main_address_no'].zfill(4)}{addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else '0000'}"
                return pnu, (float(docs[0]['y']), float(docs[0]['x'])), addr
    except: pass
    return None, None, None

# --------------------------------------------------------------------------------
# [Engine 2] 종합 데이터 융합 (Fact Engine)
# --------------------------------------------------------------------------------
class MasterFactEngine:
    @staticmethod
    def get_land_features(pnu):
        # [V-World 토지특성 API 연동]
        if not vworld_key: return None
        url = "http://api.vworld.kr/req/data"
        params = {
            "key": vworld_key,
            "domain": "https://share.streamlit.io",
            "service": "data", "version": "2.0", "request": "getfeature",
            "format": "json", "size": "1", "data": "LP_PA_CBND_BU_INFO", # 토지특성정보
            "attrfilter": f"pnu:like:{pnu}"
        }
        try:
            res = requests.get(url, params=params, timeout=5).json()
            feat = res['response']['result']['featureCollection']['features'][0]['properties']
            return {
                "도로접면": feat.get('road_side_nm', '정보없음'),
                "형상": feat.get('lad_shpe_nm', '정보없음'),
                "지세": feat.get('lad_hght_nm', '정보없음')
            }
        except: return {"도로접면": "연결중", "형상": "연결중", "지세": "연결중"}

    @staticmethod
    def get_land_basic(pnu):
        key = requests.utils.unquote(land_go_key or data_go_key)
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        try:
            res = requests.get(url, params={"serviceKey": key, "pnu": pnu, "numOfRows": 1}, timeout=5)
            item = ET.fromstring(res.content).find('.//item')
            return {
                "지목": item.findtext("lndcgrCodeNm"),
                "면적": item.findtext("lndpclAr"),
                "공시지가": item.findtext("pblntfPclnd")
            }
        except: return None

# --------------------------------------------------------------------------------
# [Engine 3] 유니콘 AI 종합 전략
# --------------------------------------------------------------------------------
def get_unicorn_insight(addr, land, feat):
    model = genai.GenerativeModel('gemini-1.5-flash')
    land_info = f"면적:{land['면적']}m2, 지목:{land['지목']}, 지가:{land['공시지가']}원" if land else "기본정보수집중"
    feat_info = f"도로:{feat['도로접면']}, 형상:{feat['형상']}, 지세:{feat['지세']}" if feat else "특성수집중"
    
    prompt = f"""
    당신은 부동산 유니콘 기업의 '수석 투자 전략가'입니다. 
    대상: {addr} / 데이터: {land_info}, {feat_info}

    이 땅의 '지갑을 열게 할' 핵심 가치를 분석하세요:
    1. 📐 건축 가능성: 도로접면과 형상을 고려할 때 실제 건축 시 효율성.
    2. 💰 가치 분석: 지세와 입지 기반의 토지 가치 평가.
    3. 💡 한줄평: 전문가의 시선에서 본 이 땅의 투자 매력도.
    """
    try: return model.generate_content(prompt).text
    except: return "인사이트 생성 중..."

# --------------------------------------------------------------------------------
# [UI] 유니콘 솔루션
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Unicorn Master", layout="wide")

with st.sidebar:
    st.title("🦄 지상 AI")
    st.caption("Unicorn Master Ver 8.0")
    target_addr = st.text_input("📍 분석 주소", "경기도 김포시 통진읍 도사리 163-1")
    search_btn = st.button("🚀 유니콘 통합 분석 시작", type="primary", use_container_width=True)

st.title("지상 AI 부동산 종합 솔루션")

if search_btn:
    pnu, coords, addr_data = get_pnu_and_coords(target_addr)
    if pnu:
        with st.status("🏗️ V-World 및 국가망 데이터 연동 중...", expanded=True):
            st.write("1. 토지 기본 정보 수집...")
            land_basic = MasterFactEngine.get_land_basic(pnu)
            st.write("2. V-World 토지 특성(도로/형상) 분석...")
            land_feat = MasterFactEngine.get_land_features(pnu)
            st.write("3. 유니콘 AI 전략 수립...")
            ai_insight = get_unicorn_insight(target_addr, land_basic, land_feat)

        st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17)
        st.divider()
        c1, c2 = st.columns([1, 2])
        with c1:
            st.subheader("📊 팩트 체크")
            with st.container(border=True):
                if land_basic:
                    st.write(f"• **지목**: {land_basic['지목']} / **면적**: {float(land_basic['면적']):,.1f} ㎡")
                    st.write(f"• **공시지가**: {int(land_basic['공시지가']):,} 원/㎡")
                if land_feat:
                    st.markdown("---")
                    st.write(f"• **도로접면**: {land_feat['도로접면']}")
                    st.write(f"• **형상**: {land_feat['형상']} / **지세**: {land_feat['지세']}")
        with c2:
            st.subheader("💡 유니콘 수석 전략가 인사이트")
            st.markdown(ai_insight)
    else: st.error("주소를 확인해주세요.")
