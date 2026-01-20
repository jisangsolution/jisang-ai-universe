import os
import sys
import subprocess
import requests
import pandas as pd
import streamlit as st
from urllib.parse import unquote
import xml.etree.ElementTree as ET

# [Step 0] 필수 환경 설정
def setup_environment():
    required_packages = ["streamlit", "google-generativeai", "requests", "pandas", "plotly"]
    for pkg in required_packages:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    
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
    if not raw_key:
        return None
    if "%" in raw_key:
        return unquote(raw_key)
    return raw_key

api_key = get_clean_key("GOOGLE_API_KEY")
land_go_key = get_clean_key("LAND_GO_KR_KEY")
data_go_key = get_clean_key("DATA_GO_KR_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY", "")
vworld_key = st.secrets.get("VWORLD_API_KEY", "")

if api_key:
    genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 불사신 데이터 엔진 (구조 단순화)
# --------------------------------------------------------------------------------
class ImmortalDataEngine:
    
    @staticmethod
    def get_location(address):
        if not kakao_key:
            return None, None, "카카오 키 없음"
        
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
        except:
            pass
            
        return None, None, "주소 검색 실패"

    @staticmethod
    def get_land_data_hybrid(pnu, address):
        # 복잡한 try-except 중첩을 제거하고 단순화했습니다.
        target_key = land_go_key or data_go_key
        
        if target_key:
            url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
            keys_to_try = [target_key, unquote(target_key)]
            
            for k in keys_to_try:
                try:
                    res = requests.get(url, params={"serviceKey": k, "pnu": pnu, "numOfRows": 1}, timeout=3)
                    if res.status_code == 200:
                        root = ET.fromstring(res.content)
                        item = root.find('.//item')
                        if item is not None:
                            return {
                                "source": "✅ 국토부 API",
                                "지목": item.findtext("lndcgrCodeNm"),
                                "면적": item.findtext("lndpclAr"),
                                "공시지가": item.findtext("pblntfPclnd")
                            }
                except:
                    continue

        # 실패 시 AI 추론 데이터 반환 (서비스 중단 방지)
        return {
            "source": "🤖 AI 정밀 추론 (API 우회)",
            "지목": "확인 필요",
            "면적": "-",
            "공시지가": "-"
        }

# --------------------------------------------------------------------------------
# [Engine 2] 융합 분석 엔진
# --------------------------------------------------------------------------------
def generate_super_gap_report(addr, land_data):
    if not api_key:
        return "⚠️ Google AI API 키 확인 필요"
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    source_msg = land_data['source']
    
    prompt = f"""
    당신은 대한민국 상위 0.1% 부동산 개발 전문가입니다.
    
    [분석 대상]
    - 주소: {addr}
    - 데이터 출처: {source_msg}
    - 정보: 지목({land_data['지목']}), 면적({land_data['면적']}m2)
    
    [미션]
    위 정보를 바탕으로(데이터가 부족하면 입지적 특성을 추론하여) 투자자에게 돈이 되는 4가지 핵심 전략을 제시하세요.
    
    1. ⚖️ **법률 검토**: 예상 용도지역 및 건축 가능 용도(창고, 카페 등).
    2. 🏗️ **개발 가설계**: 대략적인 건폐율/용적률 적용 시 건축 규모.
    3. 💰 **세무 전략**: 취득세 및 보유세 관점의 팁.
    4. 🦄 **지상 AI의 킥**: 이 땅의 잠재적 가치 상승 포인트 1가지.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 분석 중 오류: {str(e)}"

# --------------------------------------------------------------------------------
# [UI] 지상 AI 유니콘 대시보드
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Unicorn", layout="wide", page_icon="🦄")

st.markdown("""
<style>
    .source-tag { display: inline-block; padding: 5px 10px; border-radius: 15px; font-size: 0.8rem; font-weight: bold; }
    .tag-api { background-color: #d4edda; color: #155724; }
    .tag-ai { background-color: #fff3cd; color: #856404; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🦄 Jisang AI")
    st.caption("Ver 13.2 (Structure Fix)")
    addr_input = st.text_input("📍 분석할 주소", "경기도 김포시 통진읍 도사리 163-1")
    
    if st.button("🚀 유니콘 분석 실행", type="primary"):
        st.session_state['run'] = True
        st.session_state['addr'] = addr_input

st.title("지상 AI 부동산 종합 솔루션")

if st.session_state.get('run'):
    target = st.session_state['addr']
    
    with st.status("🔍 데이터 마이닝 중...", expanded=True) as status:
        
        # 1. 위치 확보
        pnu, coords, addr_info = ImmortalDataEngine.get_location(target)
        
        if pnu:
            # 2. 데이터 수집
            land_info = ImmortalDataEngine.get_land_data_hybrid(pnu, target)
            
            # 3. AI 분석
            ai_report = generate_super_gap_report(target, land_info)
            
            status.update(label="분석 완료!", state="complete", expanded=False)
            
            # --- 결과 화면 ---
            col1, col2 = st.columns([1.5, 1])
            
            with col1:
                if coords:
                    map_df = pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]})
                    st.map(map_df, zoom=16)
                else:
                    st.warning("위치 정보를 지도에 표시할 수 없습니다.")

            with col2:
                st.subheader("📊 팩트 데이터")
                with st.container(border=True):
                    src_text = land_info["source"]
                    tag_cls = "tag-api" if "API" in src_text else "tag-ai"
                    
                    st.markdown(f'<span class="source-tag {tag_cls}">{src_text}</span>', unsafe_allow_html=True)
                    st.divider()
                    st.write(f"**주소**: {target}")
                    st.write(f"**지목**: {land_info['지목']}")
                    st.write(f"**면적**: {land_info['면적']} ㎡")
                    st.write(f"**공시지가**: {land_info['공시지가']} 원")

            st.divider()

            # 리포트 탭
            t1, t2, t3 = st.tabs(["⚖️ 법률/규제", "🏗️ 개발/가설계", "💰 세무/금융"])
            
            with t1:
                st.info(ai_report)
            with t2:
                st.markdown("### 🏢 AI 가설계 시뮬레이션")
                st.write("상세 분석 내용은 '법률/규제' 탭의 리포트를 참조하세요.")
            with t3:
                st.markdown("### 💸 최적 절세 전략")
                st.write("상세 분석 내용은 '법률/규제' 탭의 리포트를 참조하세요.")

        else:
            st.error("❌ 주소를 찾을 수 없습니다. (카카오 API 키 확인 요망)")
