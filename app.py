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

# [Step 0] 환경 설정 및 필수 폰트 자동 로드
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

# API Keys - 안전한 로드 (오류 방지 로직)
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")   # 건축물대장
land_go_key = st.secrets.get("LAND_GO_KR_KEY")   # 토지대장 (신규)
kakao_key = st.secrets.get("KAKAO_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 주소 정밀 분석 (PNU & 지번 추출)
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
                # 산(Mountain) 구분: 대지는 1, 산은 2
                mount_cd = "2" if addr.get('mountain_yn') == 'Y' else "1"
                bun = addr['main_address_no'].zfill(4)
                ji = addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else "0000"
                pnu = f"{b_code}{mount_cd}{bun}{ji}" 
                
                loc_info = {
                    "full_addr": addr['address_name'],
                    "sigungu": b_code[:5], "bjdong": b_code[5:],
                    "bun": bun, "ji": ji, "gu_name": addr['region_2depth_name'],
                    "dong_name": addr['region_3depth_name']
                }
                return pnu, (lat, lon), loc_info
    except: pass
    return None, None, "주소 해석 실패"

# --------------------------------------------------------------------------------
# [Engine 2] 국가 데이터 융합 엔진 (토지 + 건물)
# --------------------------------------------------------------------------------
class RealEstateFactEngine:
    @staticmethod
    def get_land_details(pnu):
        # 토지대장 연동 (지목, 면적, 공시지가)
        key = land_go_key or data_go_key # 우선순위 적용
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        params = {"serviceKey": requests.utils.unquote(key), "pnu": pnu, "numOfRows": 1}
        try:
            res = requests.get(url, params=params, timeout=10)
            root = ET.fromstring(res.content)
            item = root.find('.//item')
            if item is not None:
                return {
                    "지목": item.findtext("lndcgrCodeNm"),
                    "면적": item.findtext("lndpclAr"),
                    "공시지가": item.findtext("pblntfPclnd"),
                    "소유": item.findtext("ownshpSeCodeNm")
                }
        except: pass
        return None

    @staticmethod
    def get_building_details(loc):
        # 건축물대장 연동
        url = "http://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo"
        params = {
            "serviceKey": requests.utils.unquote(data_go_key),
            "sigunguCd": loc['sigungu'], "bjdongCd": loc['bjdong'],
            "bun": loc['bun'], "ji": loc['ji']
        }
        try:
            res = requests.get(url, params=params, timeout=10)
            root = ET.fromstring(res.content)
            item = root.find('.//item')
            if item is not None:
                return {
                    "용도": item.findtext("mainPurpsCdNm"),
                    "연면적": item.findtext("totArea"),
                    "위반": "위반" if item.findtext("otherConst") else "정상"
                }
        except: pass
        return None

# --------------------------------------------------------------------------------
# [Engine 3] 전문가 집단 AI 분석 (Expert Advisory)
# --------------------------------------------------------------------------------
def get_unicorn_insight(loc, land, bld):
    if not api_key: return "AI 라이선스 미등록"
    # 모델명 업데이트: gemini-1.5-flash (최적의 성능과 비용)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # 팩트 데이터 패키징
    land_info = f"지목:{land['지목']}, 면적:{land['면적']}m2, 공시지가:{land['공시지가']}원/m2" if land else "미공개 필지(나대지)"
    bld_info = f"용도:{bld['용도']}, 상태:{bld['위반']}" if bld else "건물 없음(개발 유망지)"

    prompt = f"""
    당신은 부동산 유니콘 기업의 수석 전략가(Architect + Appraiser)입니다.
    대상 주소: {loc['full_addr']} ({loc['dong_name']})
    데이터: 토지[{land_info}], 건물[{bld_info}]

    부동산 종사자(시행사, 투자자)가 의사결정을 내릴 수 있도록 다음 항목을 분석하세요.
    
    1. 📐 토지 활용 가치: 
       - 지목과 면적 기반의 가설계 제안 (예: 창고, 공장, 근생 신축 가능성).
       - 지자체({loc['gu_name']}) 조례상 건폐율/용적률 추정 가이드.
    2. 💸 경제적 타당성: 
       - 공시지가를 기반으로 본 자산의 가치를 평가하고 주변 개발 호재 가능성 언급.
    3. 📜 규제 가이드(토지이음 연계): 
       - 해당 필지에서 반드시 확인해야 할 공법적 규제(군사시설, 상수원 등).
    4. 💡 투자의견: 매입 가치를 5단계(S-D)로 평점 매기고, 그 이유를 3줄 요약.

    *모든 답변은 전문적이고 신뢰감 있는 톤으로 작성하세요.*
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 분석 엔진 재가동 필요 (Error: {str(e)})"

# --------------------------------------------------------------------------------
# [UI] 유니콘 솔루션 대시보드
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Unicorn", layout="wide", page_icon="🦄")

st.markdown("""
    <style>
    .report-card { border-radius: 10px; background-color: #f9f9f9; padding: 20px; border: 1px solid #eee; }
    .stMetric { background-color: white; padding: 10px; border-radius: 5px; box-shadow: 1px 1px 3px rgba(0,0,0,0.1); }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🦄 지상 AI")
    st.caption("Real Estate Total Solution")
    st.markdown("---")
    target_addr = st.text_input("📍 분석 주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    search_btn = st.button("🚀 종합 정밀 분석 실행", type="primary", use_container_width=True)
    st.markdown("---")
    st.info("💡 **유니콘 팁**: 건물이 없는 토지의 경우 공법적 규제 및 개발 가시성을 중심으로 분석합니다.")

if search_btn:
    pnu, coords, loc_info = get_pnu_and_coords(target_addr)
    
    if pnu:
        with st.status("🏗️ 국가 데이터베이스 및 AI 브레인 가동 중...", expanded=True) as status:
            st.write("1. 토지대장 원천 데이터 추출...")
            land_data = GovDataEngine.get_land_details(pnu)
            
            st.write("2. 건축물 현황 및 위반 여부 스캔...")
            bld_data = GovDataEngine.get_building_details(loc_info)
            
            st.write("3. 유니콘 AI 종합 전략 수립...")
            ai_insight = get_unicorn_insight(loc_info, land_data, bld_data)
            
            status.update(label="분석 완료!", state="complete", expanded=False)

        # 지도 시각화
        st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17)

        # 결과 리포트 레이아웃
        st.divider()
        st.header(f"🏢 {target_addr} 종합 보고서")
        
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.subheader("📑 핵심 팩트 시트")
            with st.container(border=True):
                st.markdown("**[토지 원천 데이터]**")
                if land_data:
                    st.write(f"• **지목**: {land_data['지목']}")
                    st.write(f"• **면적**: {float(land_data['면적']):,.1f} ㎡ (약 {float(land_data['면적'])/3.3058:.1f}평)")
                    st.write(f"• **공시지가**: {int(land_data['공시지가']):,} 원/㎡")
                    st.write(f"• **소유**: {land_data['소유']}")
                else:
                    st.warning("⚠️ 토지 정보를 불러올 수 없습니다. (API 키 동기화 확인 필요)")
                
                st.markdown("---")
                st.markdown("**[건물 현황 데이터]**")
                if bld_data:
                    st.write(f"• **주용도**: {bld_data['용도']}")
                    st.write(f"• **상태**: {bld_data['위반']}")
                else:
                    st.info("🍃 현재 나대지 상태 (건물 없음)")

        with c2:
            st.subheader("💡 유니콘 수석 전략가 진단")
            st.markdown(ai_insight)
            st.caption("※ 본 보고서는 AI가 생성한 참고용 분석이며, 실제 법적 인허가는 전문가와 상의하십시오.")
            
    else:
        st.error("❌ 입력하신 주소의 PNU 코드를 생성할 수 없습니다. 번지수까지 정확히 입력했는지 확인해주세요.")
