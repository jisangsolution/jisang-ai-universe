import os
import sys
import subprocess
import urllib.request
import pandas as pd
from datetime import datetime
import io

# [Step 0] 스마트 런처
def setup_environment():
    required = {
        "streamlit": "streamlit", 
        "plotly": "plotly", 
        "google-generativeai": "google.generativeai", 
        "python-dotenv": "dotenv", 
        "reportlab": "reportlab" 
    }
    needs_install = []
    
    for pkg, mod in required.items():
        try:
            __import__(mod)
        except ImportError:
            needs_install.append(pkg)
    
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
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] PDF 생성기 (ReportLab)
# --------------------------------------------------------------------------------
def generate_final_pdf(address, context):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    font_path = "NanumGothic.ttf"
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
        font_name = 'NanumGothic'
    else:
        font_name = 'Helvetica'
        
    # Header & Title
    c.setFont(font_name, 10)
    c.drawRightString(width - 20*mm, height - 20*mm, "Jisang AI Enterprise Report")
    c.setStrokeColorRGB(0.2, 0.2, 0.6)
    c.line(20*mm, height - 22*mm, width - 20*mm, height - 22*mm)
    
    c.setFont(font_name, 22)
    c.drawCentredString(width / 2, height - 50*mm, "부동산 5대 영역 종합 분석 보고서")
    
    # Body
    c.setFillColorRGB(0.96, 0.97, 0.99)
    c.rect(20*mm, height - 90*mm, width - 40*mm, 30*mm, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    
    c.setFont(font_name, 12)
    c.drawString(25*mm, height - 70*mm, f"• 분석 대상: {address}")
    c.drawString(25*mm, height - 80*mm, f"• 발행 일자: {datetime.now().strftime('%Y년 %m월 %d일')}")
    
    y_pos = height - 110*mm
    c.setFont(font_name, 16)
    c.drawString(20*mm, y_pos, "1. 핵심 분석 결과 (Summary)")
    y_pos -= 10*mm
    
    c.setFont(font_name, 11)
    facts = [
        f"💰 [금융] 연간 이자 절감 예상액: {context['finance_saving']:,} 원",
        f"⚖️ [세무] 예상 취득세 (공장): {context['tax_est']:,} 원 ({context['tax_rate']}%)",
        f"🏗️ [개발] 신축 분양 예상 수익: {context['dev_profit']:,} 원 (ROI {context['dev_roi']}%)",
        f"🚨 [위험] 발견된 권리 리스크: {context['restrictions']}"
    ]
    for fact in facts:
        c.drawString(25*mm, y_pos, fact)
        y_pos -= 8*mm
        
    y_pos -= 10*mm
    c.setFont(font_name, 16)
    c.drawString(20*mm, y_pos, "2. AI 심층 솔루션 제언")
    y_pos -= 8*mm
    c.setFont(font_name, 11)
    c.drawString(25*mm, y_pos, "통합 대환 솔루션을 통해 금융 비용 절감 및 리스크 해소를 권장합니다.")

    # PDF Footer Disclaimer
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(20*mm, 35*mm, width - 20*mm, 35*mm)
    c.setFont(font_name, 8)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    
    footer_lines = [
        "[면책 조항] 본 보고서는 참고 자료이며 법적 효력이 없습니다.",
        "제시된 수치는 시뮬레이션 결과로 실제와 다를 수 있으며, 투자 책임은 본인에게 있습니다."
    ]
    fy = 30*mm
    for l in footer_lines:
        c.drawCentredString(width/2, fy, l)
        fy -= 4*mm
    
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# --------------------------------------------------------------------------------
# [Engine 2] 도메인 계산기
# --------------------------------------------------------------------------------
class DomainExpert:
    @staticmethod
    def calc_finance(debt): return int(debt * 0.10)
    @staticmethod
    def calc_tax(price): return int(price * 0.046), 4.6
    @staticmethod
    def calc_development(price, size): 
        cost, rev = size * 5000000, size * 10000000
        profit = rev - cost - price
        return int(profit), round((profit/(price+cost))*100, 2)

# --------------------------------------------------------------------------------
# [Chatbot] 응답 로직
# --------------------------------------------------------------------------------
def get_universe_response(u_in, ctx):
    u_in = u_in.lower()
    if any(k in u_in for k in ["안내", "도와줘"]): return "1. 금융\n2. 세무\n3. 개발\n4. 권리"
    if any(k in u_in for k in ["금융", "이자"]): return f"💰 연간 **{ctx['finance_saving']:,}원** 절감 가능합니다."
    if any(k in u_in for k in ["세금", "취득"]): return f"⚖️ 예상 취득세: **{ctx['tax_est']:,}원**"
    return "죄송합니다. '안내해줘'라고 입력하세요."

# --------------------------------------------------------------------------------
# [UI] Dashboard
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Universe", page_icon="🌌", layout="wide")

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2040/2040504.png", width=60)
    st.title("🌌 Jisang Universe")
    st.markdown("### 📍 분석 대상")
    addr_input = st.text_input("주소 입력", "김포시 통진읍 도사리 163-1")
    if st.button("🚀 분석 실행", type="primary", use_container_width=True):
        st.session_state['current_addr'] = addr_input
        st.session_state.uni_chat = [{"role": "assistant", "content": f"안녕하세요! **'{addr_input}'** 전담 AI입니다."}]

if 'current_addr' not in st.session_state: st.session_state['current_addr'] = "김포시 통진읍 도사리 163-1"

# Data
price, debt = 850000000, 600000000
saving = DomainExpert.calc_finance(debt)
tax, tax_rate = DomainExpert.calc_tax(price)
profit, roi = DomainExpert.calc_development(price, 363)
ctx = {"finance_saving": saving, "tax_est": tax, "tax_rate": tax_rate, "dev_profit": profit, "dev_roi": roi, "restrictions": "신탁등기, 압류"}

# Layout
st.title(f"🏢 {st.session_state['current_addr']} 종합 분석")
tab1, tab2, tab3 = st.tabs(["📊 통합 대시보드", "💬 AI 컨시어지", "📂 B2B 포트폴리오"])

with tab1:
    c1, c2, c3 = st.columns(3)
    c1.metric("💰 금융 (이자절감)", f"{saving/10000:,.0f}만 원/년")
    c2.metric("⚖️ 세무 (예상취득세)", f"{tax/10000:,.0f}만 원")
    c3.metric("🏗️ 개발 (예상수익)", f"{profit/10000:,.0f}만 원")
    
    st.markdown("---")
    c_risk, c_sol = st.columns([1, 2])
    with c_risk: st.error(f"🔴 권리 위험: {ctx['restrictions']}")
    with c_sol: 
        st.success("**✅ 지상 AI 통합 솔루션**")
        st.write("- **금융**: 대환 실행\n- **세무**: 중과세 검토\n- **개발**: 공장 증축")

    st.markdown("---")
    st.subheader("📑 보고서 다운로드")
    try:
        pdf_bytes = generate_final_pdf(st.session_state['current_addr'], ctx)
        st.download_button("📄 한글 정밀 보고서 (.pdf)", pdf_bytes, "Jisang_Final_Report.pdf", "application/pdf", type="primary")
    except Exception as e: st.error(f"PDF 오류: {e}")

    # ★ [추가됨] 웹 대시보드 하단 면책 조항
    st.markdown("---")
    with st.expander("⚖️ 법적 고지 및 면책 조항 (Disclaimer)", expanded=False):
        st.caption("""
        1. **정보의 참고성**: 본 서비스에서 제공하는 모든 분석 결과(금융, 세무, 개발 등)는 AI 알고리즘 및 공공 데이터를 기반으로 추산된 시뮬레이션 결과이며, 법적 효력이 없습니다.
        2. **변동 가능성**: 실제 대출 금리, 한도, 세금, 인허가 여부는 금융사의 심사 및 관할 관청의 최종 결정에 따라 달라질 수 있습니다.
        3. **책임의 한계**: 본 서비스의 분석 내용을 근거로 한 투자, 계약, 법률 행위에 대한 최종 책임은 사용자 본인에게 있으며, (주)지상 AI는 이에 대한 어떠한 법적 책임도 지지 않습니다.
        """)

with tab2:
    st.subheader("💬 AI 부동산 비서")
    if "uni_chat" not in st.session_state: st.session_state.uni_chat = [{"role": "assistant", "content": "안녕하세요!"}]
    for msg in st.session_state.uni_chat:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])
    if prompt := st.chat_input("질문 입력"):
        st.session_state.uni_chat.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.write(prompt)
        reply = get_universe_response(prompt, ctx)
        st.session_state.uni_chat.append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"): st.markdown(reply)

with tab3:
    st.subheader("💼 포트폴리오 (B2B)")
    df = pd.DataFrame({"주소": [st.session_state['current_addr'], "강남구"], "평가액": ["8.5억", "25억"]})
    st.dataframe(df, use_container_width=True)
    st.download_button("📥 엑셀 다운로드", df.to_csv().encode('utf-8'), "portfolio.csv")