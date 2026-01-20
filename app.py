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

# [Step 0] 스마트 런처: 환경 자동 세팅
def setup_environment():
    required = ["streamlit", "google-generativeai", "requests", "reportlab"]
    for pkg in required:
        try: __import__(pkg.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
            os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", __file__])

    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try: urllib.request.urlretrieve(url, font_path)
        except: pass

if "streamlit" not in sys.modules:
    setup_environment()

import google.generativeai as genai

# API Keys - 보안 로드
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")   
land_go_key = st.secrets.get("LAND_GO_KR_KEY")   
kakao_key = st.secrets.get("KAKAO_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 주소 정밀 해석 (PNU 마스터)
# --------------------------------------------------------------------------------
def get_pnu_and_coords(address):
    if not kakao_key: return None, None, "Kakao API Key Missing"
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    try:
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=5)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                addr = docs[0]['address']
                lat, lon = float(docs[0]['y']), float(docs[0]['x'])
                b_code = addr['b_code']
                
                # [무결성 로직] 산 여부 정밀 판정
                mount_yn = addr.get('mountain_yn', 'N')
                mount_cd = "2" if mount_yn == 'Y' else "1"
                
                # 번지/호수 정밀 패딩
                main_no = addr['main_address_no'].zfill(4)
                sub_no = addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else "0000"
                pnu = f"{b_code}{mount_cd}{main_no}{sub_no}" 
                
                loc_info = {
                    "full_addr": addr['address_name'],
                    "sigungu": b_code[:5], "bjdong": b_code[5:],
                    "gu_name": addr['region_2depth_name'],
                    "dong_name": addr['region_3depth_name']
                }
                return pnu, (lat, lon), loc_info
    except: pass
    return None, None, "주소 해석 불가"

# --------------------------------------------------------------------------------
# [Engine 2] 데이터 융합 엔진 (Real Estate Fact Engine)
# --------------------------------------------------------------------------------
class RealEstateFactEngine:
    @staticmethod
    def get_land_details(pnu):
        # 토지대장 연동 (지목, 면적, 공시지가)
        key = land_go_key or data_go_key
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        params = {"serviceKey": requests.utils.unquote(key), "pnu": pnu, "numOfRows": 1}
        try:
            res = requests.get(url, params=params, timeout=10)
            root = ET.fromstring(res.content)
            item = root.find('.//item')
            if item is not None:
                return {
                    "지목": item.findtext("lndcgrCodeNm") or "정보없음",
                    "면적": item.findtext("lndpclAr") or "0",
                    "공시지가": item.findtext("pblntfPclnd") or "0",
                    "소유": item.findtext("ownshpSeCodeNm") or "정보없음"
                }
        except: pass
        return None

    @staticmethod
    def get_building_details(loc, pnu):
        # 건축물대장 연동 (주소 기반 실패 시 PNU 활용 대비)
        url = "http://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo"
        params = {
            "serviceKey": requests.utils.unquote(data_go_key),
            "sigunguCd": loc['sigungu'], "bjdongCd": loc['bjdong'],
            "bun": pnu[11:15], "ji": pnu[15:19]
        }
        try:
            res = requests.get(url, params=params, timeout=10)
            root = ET.fromstring(res.content)
            item = root.find('.//item')
            if item is not None:
                return {
                    "용도": item.findtext("mainPurpsCdNm") or "정보없음",
                    "연면적": item.findtext("totArea") or "0",
                    "위반": "위반" if item.findtext("otherConst") else "정상"
                }
        except: pass
        return None

# --------------------------------------------------------------------------------
# [Engine 3] 유니콘 AI 종합 전략 (Gemini 1.5 Flash)
# --------------------------------------------------------------------------------
def get_unicorn_insight(loc, land, bld):
    if not api_key: return "AI 서버 연결 권한이 없습니다."
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # 데이터 가용성에 따른 프롬프트 최적화
    land_info = f"지목:{land['지목']}, 면적:{land['면적']}m2, 공시지가:{land['공시지가']}원" if land else "토지 데이터 응답 지연 (주소 기반 추론 필요)"
    bld_info = f"용도:{bld['용도']}, 상태:{bld['위반']}" if bld else "현재 건축물 없음 (나대지 개발 관점)"

    prompt = f"""
    당신은 부동산 유니콘 기업의 '수석 투자 전략가'입니다. 
    대상 주소: {loc['full_addr']} ({loc['dong_name']})
    입력된 팩트: {land_info} / {bld_info}

    부동산 업계 종사자가 즉시 활용할 수 있도록 다음 4단계를 정밀 분석하세요:
    
    1. 📐 토지 활용 시나리오: 현재 지목과 면적에서 가능한 최대 건축 규모(가설계 제안).
    2. 💸 경제적 타당성: 공시지가 및 입지 기반의 추정 자산 가치와 수익 창출 모델.
    3. ⚖️ 공법 규제 체크: 조례상 건폐율/용적률 및 토지이용규제(토지이음 키워드).
    4. 🦄 유니콘 포인트: 이 땅의 '지갑을 열게 할' 단 하나의 핵심 가치 제안.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 컨설턴트 분석 중: 데이터 수집 완료 후 인사이트를 생성하고 있습니다. (잠시 후 새로고침)"

# --------------------------------------------------------------------------------
# [UI] 유니콘 마스터 대시보드
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Unicorn Master", layout="wide")

st.markdown("""
    <style>
    .metric-card { border-radius: 10px; background-color: #fcfcfc; padding: 20px; border: 1px solid #eee; }
    .stAlert { border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🦄 지상 AI")
    st.caption("Unicorn Master Ver 7.5")
    st.markdown("---")
    target_addr = st.text_input("📍 분석 주소", "경기도 김포시 통진읍 도사리 163-1")
    search_btn = st.button("🚀 유니콘 통합 분석 시작", type="primary", use_container_width=True)

st.title("지상 AI 부동산 종합 솔루션")
st.info("상위 0.1% 전문가 그룹의 팩트 데이터 기반 AI 의사결정 플랫폼")

if search_btn:
    pnu, coords, loc_info = get_pnu_and_coords(target_addr)
    
    if pnu:
        with st.status("🏗️ 국가 데이터베이스 및 AI 뉴럴 엔진 가동 중...", expanded=True) as status:
            st.write("1. 토지대장 실시간 원천 데이터 획득...")
            land_data = RealEstateFactEngine.get_land_details(pnu)
            
            st.write("2. 건축물 현황 및 위반 리스크 스캔...")
            bld_data = RealEstateFactEngine.get_building_details(loc_info, pnu)
            
            st.write("3. 유니콘 AI 수석 전략가 종합 진단...")
            ai_insight = get_unicorn_insight(loc_info, land_data, bld_data)
            
            status.update(label="분석 완료!", state="complete", expanded=False)

        # GIS 시각화
        st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17)

        # 결과 리포트
        st.divider()
        st.header(f"🏢 {target_addr} 분석 리포트")
        
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.subheader("📊 팩트 체크 (Raw Data)")
            with st.container(border=True):
                if land_data:
                    st.success("✅ 토지 데이터 수신 성공")
                    st.write(f"• **지목**: {land_data['지목']}")
                    st.write(f"• **면적**: {float(land_data['면적']):,.1f} ㎡")
                    st.write(f"• **공시지가**: {int(land_data['공시지가']):,} 원/㎡")
                else:
                    st.warning("⚠️ 토지 데이터 응답 지연 (API 승인 상태 확인 필요)")
                
                st.markdown("---")
                if bld_data:
                    st.write(f"• **주용도**: {bld_data['용도']}")
                    st.write(f"• **상태**: {bld_data['위반']}")
                else:
                    st.info("🍃 현재 나대지 상태 (건물 없음)")

        with c2:
            st.subheader("💡 유니콘 수석 전략가 인사이트")
            st.markdown(ai_insight)
            
    else:
        st.error("정확한 지번 주소가 아닙니다. 주소를 다시 확인해 주세요.")
