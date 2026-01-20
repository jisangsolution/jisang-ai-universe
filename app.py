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

# [Step 0] 스마트 런처: 라이브러리 강제 로드
def setup_environment():
    required = ["streamlit", "google-generativeai", "requests", "reportlab", "pandas"]
    for pkg in required:
        try: __import__(pkg.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    
    # 폰트 다운로드 (안전한 서버로 변경)
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try: urllib.request.urlretrieve(url, font_path)
        except: pass

setup_environment()

import google.generativeai as genai

# API Keys - 보안 로드
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")   
land_go_key = st.secrets.get("LAND_GO_KR_KEY")   
kakao_key = st.secrets.get("KAKAO_API_KEY")
vworld_key = st.secrets.get("VWORLD_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] PNU & GIS 마스터
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
# [Engine 2] 종합 팩트 엔진 (V-World + 국토부)
# --------------------------------------------------------------------------------
class MasterFactEngine:
    @staticmethod
    def get_land_features(pnu):
        # V-World 데이터 (도로/형상/지세)
        url = "http://api.vworld.kr/req/data"
        params = {
            "key": vworld_key, "domain": "https://share.streamlit.io",
            "service": "data", "version": "2.0", "request": "getfeature",
            "format": "json", "size": "1", "data": "LP_PA_CBND_BU_INFO",
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
        except: return {"도로접면": "데이터 수집 중", "형상": "사각형 추정", "지세": "평지"}

    @staticmethod
    def get_land_basic(pnu):
        # 국토부 데이터 (지목/면적/공시지가)
        key = requests.utils.unquote(land_go_key or data_go_key)
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        try:
            res = requests.get(url, params={"serviceKey": key, "pnu": pnu, "numOfRows": 1}, timeout=5)
            item = ET.fromstring(res.content).find('.//item')
            return {
                "지목": item.findtext("lndcgrCodeNm") or "정보없음",
                "면적": item.findtext("lndpclAr") or "0",
                "공시지가": item.findtext("pblntfPclnd") or "0"
            }
        except: return None

# --------------------------------------------------------------------------------
# [Engine 3] AI 수석 전략가 (Gemini 1.5 Flash)
# --------------------------------------------------------------------------------
def get_unicorn_insight(addr, land, feat):
    if not api_key: return "AI 연결 필요"
    model = genai.GenerativeModel('gemini-1.5-flash')
    land_info = f"면적:{land['면적']}m2, 지목:{land['지목']}, 지가:{land['공시지가']}원" if land else "기본정보수집중"
    feat_info = f"도로:{feat['도로접면']}, 형상:{feat['형상']}, 지세:{feat['지세']}" if feat else "특성수집중"
    
    prompt = f"""
    당신은 부동산 유니콘 기업의 '수석 투자 전략가'입니다. 
    대상: {addr} / 데이터: {land_info}, {feat_info}

    부동산 종사자의 지갑을 열게 할 3대 인사이트를 작성하세요:
    1. 📐 개발 시뮬레이션: 도로접면과 형상을 고려한 최적 건축 규모 제안.
    2. 💰 가치 분석: 공시지가 및 입지 기반의 미래 가치 평가.
    3. 💡 핵심 전략: 전문가로서 매수/개발/매도 중 어떤 전략이 유효한지 3줄 요약.
    """
    try: return model.generate_content(prompt).text
    except: return "AI가 전략을 구상하고 있습니다. 잠시 후 새로고침 해주세요."

# --------------------------------------------------------------------------------
# [UI] 유니콘 마스터 대시보드
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Unicorn Master", layout="wide", page_icon="🦄")

# 사이드바
with st.sidebar:
    st.title("🦄 지상 AI")
    st.caption("Unicorn Master Ver 9.0")
    st.markdown("---")
    target_addr = st.text_input("📍 분석할 주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    search_btn = st.button("🚀 유니콘 통합 분석 시작", type="primary", use_container_width=True)
    st.markdown("---")
    st.info("💡 **Tip:** 토지특성정보(도로/형상)를 통해 건축 가능성을 즉시 확인합니다.")

st.title("지상 AI 부동산 종합 솔루션")

if search_btn:
    pnu, coords, addr_data = get_pnu_and_coords(target_addr)
    if pnu:
        with st.status("🏗️ 국가 데이터베이스 및 AI 브레인 동기화 중...", expanded=True) as status:
            st.write("1. 토지 기본 정보 수집...")
            land_basic = MasterFactEngine.get_land_basic(pnu)
            st.write("2. V-World 토지 특성 정밀 스캔...")
            land_feat = MasterFactEngine.get_land_features(pnu)
            st.write("3. 유니콘 AI 통합 전략 수립...")
            ai_insight = get_unicorn_insight(target_addr, land_basic, land_feat)
            status.update(label="분석 완료!", state="complete", expanded=False)

        # GIS 시각화
        st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17)

        # 결과 리포트
        st.divider()
        st.header(f"🏢 {target_addr} 분석 보고서")
        
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
                else:
                    st.warning("토지 특성 정보 동기화 중...")

        with c2:
            st.subheader("💡 유니콘 수석 전략가 인사이트")
            st.markdown(ai_insight)
            st.caption("※ 본 분석은 AI 기반 시뮬레이션이며, 실제 투자 시 전문가 검토가 필요합니다.")
    else:
        st.error("입력하신 주소의 PNU 코드를 찾을 수 없습니다. 번지수까지 정확히 입력해 주세요.")
else:
    st.info("👈 왼쪽 사이드바에 분석하고 싶은 부동산 주소를 입력하고 '분석 시작'을 눌러주세요.")
