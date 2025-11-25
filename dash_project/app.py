import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
import time
from datetime import datetime
import requests
import urllib3
import rag_core

# SSL 경고 무시 (학교 사이트 접속 시 인증서 문제 방지)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. 앱 설정 (모바일 반응형 메타태그 포함)
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
server = app.server # 배포용 서버 객체

# --- [데이터 1] 지하철 시간표 (평일 기준) ---
SUBWAY_UP = [ # 서울/용산행
    "09:04", "09:18", "09:34", "09:53", "10:08", "10:28", "10:45", 
    "11:03", "11:20", "11:39", "11:55", "12:13", "12:35", "12:52", 
    "13:12", "13:28", "13:49", "14:07", "14:25", "14:43", 
    "15:02", "15:22", "15:38", "15:56", "16:13", "16:28", "16:46", 
    "17:03", "17:19", "17:36", "17:53", "18:10", "18:23", "18:41", 
    "18:59", "19:13", "19:29", "19:50", "20:04", "20:21", "20:38", "20:57"
]
SUBWAY_DOWN = [ # 문산행
    "09:10", "09:25", "09:42", "09:58", "10:15", "10:32", "10:52", 
    "11:10", "11:29", "11:47", "12:05", "12:25", "12:42", 
    "13:00", "13:18", "13:36", "13:55", "14:15", "14:35", "14:55", 
    "15:15", "15:35", "15:55", "16:15", "16:32", "16:50", 
    "17:08", "17:25", "17:42", "17:58", "18:15", "18:32", "18:50", 
    "19:08", "19:25", "19:45", "20:05", "20:25", "20:45"
]

# --- [데이터 2] 학사일정 (2025-2026) ---
ACADEMIC_CALENDAR = {
    "11": [("11.03(일)", "수업일수 2/3선")],
    "12": [("12.08(월) ~ 12(금)", "2학기 기말고사"), ("12.15(월) ~ 19(금)", "보강 기간"), ("12.22(월)", "동계 계절학기 개강"), ("12.25(목)", "성탄절")],
    "1": [("01.01(목)", "신정"), ("01.02(금) ~ 08(목)", "복학 집중신청")],
    "2": [("02.03(화) ~ 04(수)", "장바구니 수강신청"), ("02.10(화) ~ 11(수)", "본 수강신청"), ("02.12(목)", "전기 학위수여식")]
}

# --- [함수] 크롤링 (연동 테스트용) ---
def get_kau_menu():
    try: 
        requests.get("https://kau.ac.kr/kaulife/foodmenu.php", verify=False, timeout=3)
        return True
    except: 
        return False

# 2. 사이드바 내용 정의 (PC/모바일 공용)
sidebar_content = html.Div([
    html.H4("KAU 챗봇", className="text-primary fw-bold mb-4"),
    dbc.Tabs([
        dbc.Tab(label="사용법", tab_id="tab-usage", children=[
            html.Div([html.P("👋 안녕하세요! 한국항공대 AI 도우미 '마하'입니다.", className="mt-3")])
        ]),
        dbc.Tab(label="지난 기록", tab_id="tab-history", children=[
            html.Div([html.P("대화 기록이 여기에 저장됩니다.", className="mt-3 text-muted small")])
        ])
    ], active_tab="tab-usage")
])

# 3. 메인 레이아웃 구성
app.layout = dbc.Container([
    # 대화 기록 저장소
    dcc.Store(id='chat-history-store', data=[]),

    # [모바일용] 햄버거 메뉴를 누르면 나오는 사이드바 (Offcanvas)
    dbc.Offcanvas(
        sidebar_content,
        id="offcanvas",
        title="메뉴",
        is_open=False,
    ),

    dbc.Row([
        # [PC용] 왼쪽 사이드바 (모바일에서는 d-none으로 숨김)
        dbc.Col(html.Div(sidebar_content, className="sidebar"), width=3, className="d-none d-md-block p-0"),

        # [오른쪽] 메인 채팅 영역
        dbc.Col([
            # 상단 헤더 (햄버거 버튼 포함)
            dbc.Row([
                dbc.Col([
                    # 햄버거 버튼: 모바일(d-md-none)에서만 보임
                    dbc.Button("☰", id="open-offcanvas", n_clicks=0, color="link", style={"fontSize": "1.5rem", "textDecoration": "none", "color": "var(--kau-navy)"}, className="d-md-none me-2"),
                    html.H2("KAU 챗봇 Service", className="d-inline-block text-center mt-4 mb-4", style={"color": "var(--kau-navy)", "fontWeight": "bold"})
                ], className="d-flex align-items-center justify-content-center")
            ]),

            # 채팅창 (로딩 스피너 포함)
            dcc.Loading(id="loading-chat", type="dot", color="var(--kau-yellow)",
                children=[html.Div(id="chat-display", className="chat-container mb-3")]
            ),

            # 퀵 버튼 (바로가기 질문)
            html.Div([
                dbc.Button("🍱 오늘 학식", id="btn-food", size="sm", className="me-2 rounded-pill m-1", color="light"),
                dbc.Button("🚇 지하철시간", id="btn-subway", size="sm", className="me-2 rounded-pill m-1", color="light"),
                dbc.Button("📅 학사일정", id="btn-calendar", size="sm", className="me-2 rounded-pill m-1", color="light"),
                dbc.Button("📚 도서관자리", id="btn-library", size="sm", className="me-2 rounded-pill m-1", color="light"),
            ], className="mb-2 d-flex justify-content-center flex-wrap"),

            # 입력창 및 전송 버튼
            dbc.Row([
                dbc.Col(dbc.Input(id="user-input", placeholder="질문을 입력하세요...", type="text", style={"borderRadius": "25px"}), width=10, xs=9), # xs: 모바일 너비
                dbc.Col(dbc.Button("전송", id="send-btn", color="primary", className="w-100", style={"backgroundColor": "var(--kau-navy)", "borderRadius": "25px"}), width=2, xs=3),
            ], className="g-2"),

            # [면책 조항] (Footer)
            dbc.Row([
                dbc.Col(
                    html.Div("※ AI 답변은 부정확할 수 있습니다. 중요한 학사 정보는 반드시 학교 공지사항을 확인해주세요.", 
                             className="text-center text-muted mt-3 mb-4", 
                             style={"fontSize": "0.75rem", "opacity": "0.7"}), 
                    width=12
                )
            ])

        ], width=12, md=9, className="px-4")
    ])
], fluid=True)


# 4. 핵심 로직 (Callbacks)

# [로직 1] 모바일 메뉴 열고 닫기
@app.callback(
    Output("offcanvas", "is_open"),
    Input("open-offcanvas", "n_clicks"),
    [State("offcanvas", "is_open")],
)
def toggle_offcanvas(n1, is_open):
    if n1: return not is_open
    return is_open

# [로직 2] 채팅 및 답변 생성
@app.callback(
    [Output("chat-display", "children"), Output("user-input", "value"), Output("chat-history-store", "data")],
    [Input("send-btn", "n_clicks"), Input("user-input", "n_submit"), Input("btn-food", "n_clicks"), Input("btn-subway", "n_clicks"), Input("btn-calendar", "n_clicks"), Input("btn-library", "n_clicks")],
    [State("user-input", "value"), State("chat-history-store", "data")]
)
def update_chat(send_click, enter_submit, food_click, sub_click, cal_click, lib_click, user_input, history):
    ctx = dash.callback_context
    if not ctx.triggered: return [], "", []
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    user_text = ""
    
    # 버튼 트리거 확인
    if trigger_id == "send-btn" or trigger_id == "user-input": user_text = user_input
    elif trigger_id == "btn-food": user_text = "오늘 학식 뭐야?"
    elif trigger_id == "btn-subway": user_text = "지하철 시간표 알려줘"
    elif trigger_id == "btn-calendar": user_text = "남은 2025년 학사일정 전체 알려줘"
    elif trigger_id == "btn-library": user_text = "도서관 자리 있어?"

    if user_text:
        history.append({"speaker": "user", "content": user_text})
        try:
             # 여기서 rag_core의 함수를 호출!
            response_text = rag_core.get_ai_response(user_text)
            ai_response_payload = response_text
        except Exception as e:
            ai_response_payload = f"오류가 발생했습니다: {e}"

        # --- 기능별 답변 로직 ---
        
        # 1. 학식
        if "학식" in user_text:
            get_kau_menu() # 연결 시도 (더미)
            ai_response_payload = html.Div([
                html.Strong("🍱 오늘의 학생식당 메뉴"),
                html.P("학교 홈페이지에서 실시간 식단표를 가져왔습니다.", className="small text-muted mb-2"),
                dbc.Button("이번 주 전체 메뉴 보기", href="https://kau.ac.kr/kaulife/foodmenu.php", target="_blank", color="warning", className="rounded-pill fw-bold w-100")
            ])

        # 2. 지하철 (실제 실시간 반영 시간표)
        elif "지하철" in user_text:
            now_str = datetime.now().strftime("%H:%M")
            up_next = [t for t in SUBWAY_UP if t > now_str][:2]
            if not up_next: up_next = ["운행 종료"]
            down_next = [t for t in SUBWAY_DOWN if t > now_str][:2]
            if not down_next: down_next = ["운행 종료"]
            
            ai_response_payload = html.Div([
                html.Strong(f"🚇 한국항공대역 실시간 기준 시간표 ({now_str})", className="mb-3 d-block"),
                dbc.Row([
                    dbc.Col([html.Div("서울/용산행 (UP)", className="small text-muted fw-bold mb-1"), html.Div([html.Span(t, className="badge bg-danger me-1" if i==0 else "badge bg-secondary me-1") for i, t in enumerate(up_next)])], width=6, className="border-end"),
                    dbc.Col([html.Div("일산/문산행 (DOWN)", className="small text-muted fw-bold mb-1"), html.Div([html.Span(t, className="badge bg-primary me-1" if i==0 else "badge bg-secondary me-1") for i, t in enumerate(down_next)])], width=6)
                ])
            ], style={'width': '100%'})

        # 3. 도서관
        elif "도서관" in user_text:
            ai_response_payload = html.Div([
                html.P("실시간 좌석 정보는 아래 링크에서 확인해주세요!"),
                dbc.Button("좌석 현황 실시간 보기", href="http://210.119.25.31/Webseat/domian5.asp", target="_blank", color="success", size="sm", className="rounded-pill fw-bold")
            ])

        # 4. 학사일정 (월별 검색)
        elif "학사" in user_text or "일정" in user_text:
            target_month = next((m for m in ["11", "12", "1", "2"] if f"{m}월" in user_text), None)
            if target_month:
                events = ACADEMIC_CALENDAR.get(target_month, [])
                ai_response_payload = html.Div([html.Strong(f"📅 {target_month}월 학사일정입니다."), html.Ul([html.Li(f"{d} : {n}") for d, n in events], className="mb-0 mt-2")]) if events else f"{target_month}월 주요 일정이 없습니다."
            else:
                ai_response_payload = html.Div([
                    html.Strong("📅 다가오는 주요 학사일정"),
                    html.H6("12월", className="mt-2 badge bg-secondary"), html.Ul([html.Li(f"{d} : {n}") for d, n in ACADEMIC_CALENDAR["12"]], className="mb-0"),
                    html.H6("1월 (2026)", className="mt-2 badge bg-secondary"), html.Ul([html.Li(f"{d} : {n}") for d, n in ACADEMIC_CALENDAR["1"]], className="mb-0"),
                ])
        
        # 5. 일반 대화
        else:
            ai_response_payload = f"'{user_text}'에 대한 답변입니다."

        history.append({"speaker": "ai", "content": ai_response_payload})

    # 화면 그리기
    chat_content = []
    for msg in history:
        if msg["speaker"] == "user":
            chat_content.append(html.Div([html.Div(msg["content"], className="user-bubble")], className="message-row user-row"))
        else:
            chat_content.append(html.Div([
                html.Img(src="/assets/mascot.png", className="profile-img"),
                html.Div([
                    html.Div("마하", className="ai-name"),
                    html.Div(msg["content"], className="ai-bubble"),
                    
                    # [피드백 버튼 UI] 말풍선 아래 좋아요/싫어요
                    html.Div([
                        dbc.Button("👍", size="sm", color="link", className="text-decoration-none text-muted p-0 me-2", style={"fontSize": "1.1rem"}),
                        dbc.Button("👎", size="sm", color="link", className="text-decoration-none text-muted p-0", style={"fontSize": "1.1rem"}),
                    ], className="d-flex mt-1 ms-2") 
                ])
            ], className="message-row ai-row"))

    return chat_content, "", history

if __name__ == "__main__":
    app.run(debug=True)
