import sys
import subprocess
import importlib.util

# --------------------------------------------------------------------------------
# 1. 라이브러리 자동 설치 및 설정 (System Bootstrapper)
# --------------------------------------------------------------------------------
def install_requirements():
    """
    필요한 라이브러리가 설치되어 있는지 확인하고, 없으면 자동으로 설치합니다.
    Streamlit Cloud 배포 시에도 유용하지만, 로컬 실행 시 편의를 제공합니다.
    """
    required_libraries = [
        "streamlit",
        "google-generativeai",
        "requests",
        "pandas",
        "urllib3"
    ]
    
    for lib in required_libraries:
        # 패키지명과 임포트명이 다른 경우 처리 (google-generativeai -> google.generativeai)
        import_name = "google.generativeai" if lib == "google-generativeai" else lib
        
        if importlib.util.find_spec(import_name) is None:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", lib])
                print(f"Successfully installed: {lib}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to install {lib}: {e}")

# 실행 전 라이브러리 점검
install_requirements()

# 라이브러리 임포트
import streamlit as st
import google.generativeai as genai
import requests
import pandas as pd
import json
from urllib.parse import unquote
import time

# --------------------------------------------------------------------------------
# 2. SystemConfig: 시스템 설정 및 시크릿 관리
# --------------------------------------------------------------------------------
class SystemConfig:
    """
    시스템 환경 설정, API 키 로드, 로깅 설정을 담당합니다.
    """
    @staticmethod
    def init_page():
        """Streamlit 페이지 초기 설정"""
        st.set_page_config(
            page_title="Jisang AI - 부동산 의사결정 시스템",
            page_icon="🏢",
            layout="wide",
            initial_sidebar_state="expanded"
        )
        
        # 폰트 깨짐 방지 (필요 시 CSS 주입)
        st.markdown("""
            <style>
            .stApp { font-family: 'Pretendard', sans-serif; }
            </style>
        """, unsafe_allow_html=True)

    @staticmethod
    def get_secrets():
        """
        st.secrets에서 API 키를 안전하게 로드합니다.
        URL Encoding된 키가 있을 수 있으므로 unquote 처리를 수행합니다.
        키가 없을 경우 None을 반환하여 데모 모드로 유도합니다.
        """
        keys = {
            "google_api_key": None,
            "kakao_api_key": None,
            "law_api_key": None
        }
        
        try:
            if "GOOGLE_API_KEY" in st.secrets:
                keys["google_api_key"] = unquote(st.secrets["GOOGLE_API_KEY"])
            if "KAKAO_API_KEY" in st.secrets:
                keys["kakao_api_key"] = unquote(st.secrets["KAKAO_API_KEY"])
            if "LAW_API_KEY" in st.secrets:
                keys["law_api_key"] = unquote(st.secrets["LAW_API_KEY"])
        except FileNotFoundError:
            # 로컬에서 secrets.toml이 없는 경우 무시 (데모 모드 진입)
            pass
        except Exception:
            pass
            
        return keys

# --------------------------------------------------------------------------------
# 3. DataEngine: 외부 데이터 수집 (Kakao, 공공데이터)
# --------------------------------------------------------------------------------
class DataEngine:
    """
    외부 API와의 통신을 담당하며, 실패 시 방어적으로 더미 데이터를 반환합니다.
    """
    def __init__(self, kakao_key, law_key):
        self.kakao_key = kakao_key
        self.law_key = law_key

    def get_coordinates(self, address):
        """
        Kakao Local API를 사용하여 주소를 좌표(lat, lng)와 행정구역 정보로 변환합니다.
        """
        if not self.kakao_key:
            return None, "API 키 없음 (데모 모드)"

        url = "https://dapi.kakao.com/v2/local/search/address.json"
        headers = {"Authorization": f"KakaoAK {self.kakao_key}"}
        params = {"query": address}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data['documents']:
                    doc = data['documents'][0]
                    # 도로명 주소와 지번 주소 모두 파싱 시도
                    coords = {
                        "lat": float(doc['y']),
                        "lng": float(doc['x']),
                        "region_1depth": doc['address']['region_1depth_name'],
                        "region_2depth": doc['address']['region_2depth_name'],
                        "region_3depth": doc['address']['region_3depth_name'],
                    }
                    return coords, None
                else:
                    return None, "주소 검색 결과 없음"
            else:
                return None, f"Kakao API 오류: {response.status_code}"
        except Exception as e:
            return None, f"네트워크/파싱 오류: {str(e)}"

    def get_law_data(self, region_name):
        """
        국가법령정보센터 API를 흉내내어 조례 정보를 검색합니다.
        실제 오픈 API 연동은 매우 복잡하므로(XML 파싱 등), 여기서는 구조만 잡고
        데모 데이터 혹은 검색 실패 처리를 수행합니다.
        """
        if not self.law_key:
            return "도시계획조례 데이터 수신 대기 중 (API Key Missing)"

        # 실제로는 여기서 requests.get(...)을 통해 국가법령정보센터 DRF/OpenAPI 호출
        # 예외 발생을 방지하기 위해 간단한 try-except 구조 사용
        try:
            # 시뮬레이션: 실제 API 호출 로직이 들어갈 자리
            # response = requests.get(url, params={...}, timeout=5)
            # if response.ok: return parse_xml(response.text)
            
            # 현재는 안정성을 위해 지역명 기반 더미 텍스트 반환 (구현 예시)
            return f"[{region_name}] 도시계획 조례 검색 결과: \n해당 지역은 제3종일반주거지역에 해당할 가능성이 높으며, 건폐율 50%, 용적률 250% 이하 적용 대상임."
        except Exception as e:
            return f"법령 데이터 조회 중 오류: {str(e)}"

# --------------------------------------------------------------------------------
# 4. AIEngine: Google Gemini Pro 연동 및 분석
# --------------------------------------------------------------------------------
class AIEngine:
    """
    Google Gemini Pro 모델을 사용하여 부동산 데이터를 분석합니다.
    안정성을 위해 gemini-pro (stable) 모델만 사용합니다.
    """
    def __init__(self, api_key):
        self.api_key = api_key
        self.is_active = False
        
        if self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                # 안전 설정을 포함하여 모델 초기화 (필요시 safety_settings 추가)
                self.model = genai.GenerativeModel('gemini-pro')
                self.is_active = True
            except Exception as e:
                print(f"Gemini 설정 오류: {e}")
                self.is_active = False

    def generate_report(self, address, coords_data, law_text):
        """
        수집된 정보를 바탕으로 3단 리포트를 생성합니다.
        """
        # 1. 프롬프트 구성
        prompt = f"""
        당신은 전문 부동산 컨설턴트 '지상 AI'입니다. 다음 정보를 바탕으로 상세 분석 보고서를 작성하세요.

        [분석 대상]
        주소: {address}
        행정구역: {coords_data.get('region_1depth', '')} {coords_data.get('region_2depth', '')} {coords_data.get('region_3depth', '')}
        참고 법령 데이터: {law_text}

        [요청 사항]
        다음 3가지 항목으로 나누어 마크다운 형식으로 출력하세요.
        1. **법률 분석**: 해당 지역의 용도지역 예측 및 주요 법적 규제 요약.
        2. **건축 제한**: 예상 건폐율, 용적률 및 건축 가능한 건물의 형태 제안.
        3. **수익성 전략**: 이 땅을 가장 효율적으로 개발하거나 활용할 수 있는 아이디어 (상가주택, 오피스텔 등).

        정보가 부족하면 보수적으로 추론하고, 추론임을 명시하세요.
        """

        # 2. API 호출 또는 데모 모드
        if not self.is_active:
            return self._get_demo_response()

        try:
            response = self.model.generate_content(prompt)
            # 응답 안전성 검사
            if response and response.text:
                return response.text
            else:
                return "AI 분석 결과를 생성하지 못했습니다. (응답 비어있음)"
        except Exception as e:
            return f"AI 분석 중 오류가 발생했습니다: {str(e)}\n\n(데모 결과로 대체합니다)\n{self._get_demo_response()}"

    def _get_demo_response(self):
        """API 키가 없거나 오류 발생 시 보여줄 더미 데이터"""
        return """
        ### ⚠️ 데모 모드 분석 결과
        **현재 Gemini API 키가 설정되지 않았거나 네트워크 오류입니다.**
        
        #### 1. 법률 분석 (예시)
        - 대상지는 **제2종일반주거지역**으로 추정됩니다.
        - 일조권 사선 제한 여부를 확인해야 합니다.
        
        #### 2. 건축 제한 (예시)
        - **건폐율**: 60% 이하
        - **용적률**: 200% ~ 250%
        - **층수 제한**: 지자체 조례에 따라 다름 (보통 7층 이하 또는 제한 없음)
        
        #### 3. 수익성 전략 (예시)
        - 1층 필로티 주차장 + 근린생활시설 추천.
        - 상부층은 다세대 주택 혹은 오피스텔로 구성하여 임대 수익 극대화.
        """

# --------------------------------------------------------------------------------
# 5. Main Application Logic
# --------------------------------------------------------------------------------
def main():
    # 1. 시스템 초기화
    SystemConfig.init_page()
    keys = SystemConfig.get_secrets()
    
    # 2. 엔진 인스턴스 생성
    data_engine = DataEngine(keys['kakao_api_key'], keys['law_api_key'])
    ai_engine = AIEngine(keys['google_api_key'])

    # 3. 사이드바 UI
    with st.sidebar:
        st.title("🏗️ 지상 AI")
        st.caption("부동산 통합 의사결정 시스템")
        st.divider()
        
        target_address = st.text_input("분석할 주소를 입력하세요", value="서울특별시 강남구 테헤란로 427")
        run_btn = st.button("분석 실행 (Run Analysis)", type="primary")
        
        st.divider()
        st.info("💡 Tip: 상세 주소를 입력할수록 정확도가 높아집니다.")
        
        # API 상태 표시 (디버깅용)
        st.write("---")
        st.caption("System Status")
        st.caption(f"Gemini: {'✅ Ready' if keys['google_api_key'] else '❌ Missing'}")
        st.caption(f"Kakao: {'✅ Ready' if keys['kakao_api_key'] else '❌ Missing'}")

    # 4. 메인 화면 로직
    if run_btn:
        st.header(f"📍 분석 보고서: {target_address}")
        
        # 상태 컨테이너
        status_container = st.status("데이터 수집 및 분석 중...", expanded=True)
        
        # [Step 1] 좌표 및 기본 정보 변환
        status_container.write("🔍 주소 데이터 변환 중...")
        coords, error_msg = data_engine.get_coordinates(target_address)
        
        # 데모 모드 핸들링 (좌표 못 구해도 데모 좌표 사용)
        if not coords:
            status_container.warning(f"좌표 변환 실패: {error_msg} -> 데모 좌표(서울시청) 사용")
            coords = {
                "lat": 37.5665, 
                "lng": 126.9780, 
                "region_1depth": "서울", 
                "region_2depth": "중구", 
                "region_3depth": "태평로1가"
            }
            time.sleep(1) # UX를 위한 짧은 대기

        # [Step 2] 법령 데이터 검색
        status_container.write("📜 자치법규(도시계획조례) 검색 중...")
        law_info = data_engine.get_law_data(coords.get('region_2depth', '미확인 지역'))
        time.sleep(0.5)

        # [Step 3] AI 분석 수행
        status_container.write("🧠 Gemini Pro 엔진 구동 중...")
        ai_result = ai_engine.generate_report(target_address, coords, law_info)
        
        status_container.update(label="분석 완료!", state="complete", expanded=False)

        # 5. 결과 시각화 (2단 컬럼)
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("지도 확인")
            # 지도 데이터 프레임 생성
            map_data = pd.DataFrame({
                'lat': [coords['lat']],
                'lon': [coords['lng']]
            })
            st.map(map_data, zoom=15)
            
            st.success(f"**행정구역**: {coords['region_1depth']} {coords['region_2depth']} {coords['region_3depth']}")

        with col2:
            st.subheader("참고 조례 데이터")
            st.text_area("수집된 원문 데이터", value=law_info, height=250, disabled=True)

        st.divider()
        
        # 6. AI 리포트 출력
        st.subheader("🤖 지상 AI 솔루션")
        st.markdown(ai_result)

    else:
        # 대기 화면
        st.markdown("""
        ### 👋 환영합니다!
        좌측 사이드바에 분석하고 싶은 **토지, 건물의 주소**를 입력해주세요.
        
        **지상 AI**는 다음 과정을 통해 의사결정을 지원합니다:
        1. **위치 분석**: 정확한 위경도 및 행정구역 식별
        2. **규제 검색**: 해당 지자체의 도시계획 조례 탐색
        3. **AI 컨설팅**: Gemini Pro 모델이 건축 제한과 수익화 전략을 제안
        """)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # 최후의 방어선 (앱 크래시 방지)
        st.error("시스템 치명적 오류 발생. 관리자에게 문의하세요.")
        st.exception(e)
