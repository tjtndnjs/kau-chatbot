import dash
from dash import html, dcc, Input, Output, State, callback_context, ALL
import dash_bootstrap_components as dbc
from datetime import datetime
import requests
import urllib3

# 💡 rag_core 모듈 더미 처리
try:
    import rag_core
except ImportError:
    class MockRag:
        def get_ai_response(self, text):
            return f"**{text}**에 대한 답변입니다. (rag_core 모듈 필요)"
    rag_core = MockRag()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
server = app.server

# ---------------------------------------------------
# 데이터
# ---------------------------------------------------
SUBWAY_UP = [
    "09:04","09:18","09:34","09:53","10:08","10:28","10:45","11:03","11:20",
    "11:39","11:55","12:13","12:35","12:52","13:12","13:28","13:49","14:07",
    "14:25","14:43","15:02","15:22","15:38","15:56","16:13","16:28","16:46",
    "17:03","17:19","17:36","17:53","18:10","18:23","18:41","18:59","19:13",
    "19:29","19:50","20:04","20:21","20:38","20:57"
]

SUBWAY_DOWN = [
    "09:10","09:25","09:42","09:58","10:15","10:32","10:52","11:10","11:29",
    "11:47","12:05","12:25","12:42","13:00","13:18","13:36","13:55","14:15",
    "14:35","14:55","15:15","15:35","15:55","16:15","16:32","16:50","17:08",
    "17:25","17:42","17:58","18:15","18:32","18:50","19:08","19:25","19:45",
    "20:05","20:25","20:45"
]

ACADEMIC_CALENDAR = {
    "11": [("11.03(일)", "수업일수 2/3선")],
    "12": [("12.08(월) ~ 12(금)", "기말고사"),
           ("12.15(월)~19(금)", "보강기간"),
           ("12.22(월)", "동계 계절학기"),
           ("12.25(목)", "성탄절")],
    "1":  [("01.01(목)", "신정"),
           ("01.02(금) ~ 08(목)", "복학 집중신청")],
    "2":  [("02.03(화) ~ 04(수)", "장바구니 신청"),
           ("02.10(화) ~ 11(수)", "본 수강신청"),
           ("02.12(목)", "학위수여식")]
}

def get_kau_menu():
    try:
        requests.get("https://kau.ac.kr/kaulife/foodmenu.php", verify=False, timeout=2)
        return True
    except:
        return False

# ---------------------------------------------------
# 버튼용 카드 UI 함수들
# ---------------------------------------------------

def card_food():
    return html.Div(
        className="ai-card",
        children=[
            html.Div("🍱 오늘의 학생식당 메뉴", className="card-title"),
            html.Div("학교 홈페이지에서 실시간 식단표를 가져왔습니다.", className="card-desc"),
            dbc.Button(
                "이번 주 전체 메뉴 보기",
                href="https://kau.ac.kr/kaulife/foodmenu.php",
                target="_blank",
                className="card-btn-yellow"
            ),
        ]
    )

def card_subway(now, up, down):
    return html.Div(
        className="ai-card",
        children=[
            html.Div(f"🚇 한국항공대역 실시간 기준 시간표 ({now})", className="card-title"),

            html.Div([
                html.Div("서울/용산행 (UP)", className="small-title"),
                html.Div(", ".join(up) if up else "운행 종료", className="time-text"),
            ], className="mt-2"),

            html.Div([
                html.Div("일산/문산행 (DOWN)", className="small-title"),
                html.Div(", ".join(down) if down else "운행 종료", className="time-text"),
            ], className="mt-2"),
        ]
    )

def card_academic():
    return html.Div(
        className="ai-card",
        children=[
            html.Div("📅 다가오는 주요 학사일정", className="card-title"),

            html.Div([
                html.Div("12월", className="month-label"),
                html.Ul([
                    html.Li("12.08(월) ~ 12(금) : 2학기 기말고사"),
                    html.Li("12.15(월) ~ 19(금) : 보강 기간"),
                    html.Li("12.22(월) : 동계 계절학기 개강"),
                    html.Li("12.25(목) : 성탄절"),
                ]),
            ], className="mt-2"),

            html.Div([
                html.Div("1월 (2026)", className="month-label"),
                html.Ul([
                    html.Li("01.01(목) : 신정"),
                    html.Li("01.02(금) ~ 08(목) : 복학 집중신청"),
                ]),
            ], className="mt-2"),
        ]
    )

def card_library():
    return html.Div(
        className="ai-card",
        children=[
            html.Div("📚 실시간 좌석 정보는 아래 링크에서 확인해주세요!", className="card-title"),
            dbc.Button(
                "좌석 현황 실시간 보기",
                href="http://210.119.25.31/Webseat/domian5.asp",
                target="_blank",
                className="card-btn-green"
            ),
        ]
    )

# AI 말풍선 하나를 그리는 공통 함수
def render_ai_message(msg):
    t = msg.get("type")
    if t == "food":
        body = card_food()
        bubble_child = html.Div(body, className="ai-bubble")
    elif t == "subway":
        body = card_subway(msg.get("time", ""), msg.get("up", []), msg.get("down", []))
        bubble_child = html.Div(body, className="ai-bubble")
    elif t == "academic":
        body = card_academic()
        bubble_child = html.Div(body, className="ai-bubble")
    elif t == "library":
        body = card_library()
        bubble_child = html.Div(body, className="ai-bubble")
    else:
        # 기본 텍스트 응답
        bubble_child = dcc.Markdown(str(msg.get("content", "")), className="ai-bubble")

    return html.Div([
        html.Img(src="/assets/mascot.png", className="profile-img"),
        html.Div([
            html.Div("마하", className="ai-name"),
            bubble_child
        ])
    ], className="message-row ai-row")

# ---------------------------------------------------
# PC / 모바일 사이드바
# ---------------------------------------------------

sidebar_tabs = html.Div([
    html.H4("KAU 챗봇", className="text-primary fw-bold mb-4"),

    dbc.Tabs([
        dbc.Tab(label="사용법", tab_id="tab-usage", children=[
            html.P("👋 안녕하세요! 한국항공대 AI 도우미입니다.")
        ]),

        dbc.Tab(label="지난 기록", tab_id="tab-history", children=[
            html.Div(
                id="history-list",
                className="mt-3",
                style={"cursor": "pointer", "fontSize": "0.9rem"}
            ),
        ]),
    ], id="tabs-pc", active_tab="tab-usage"),

    html.Div(
        dbc.Button("🗑 기록 전체 삭제", id="clear-history",
                   color="danger", className="w-100 mt-3"),
        id="clear-btn-wrapper-pc",
        style={"display": "none"}
    )
], className="sidebar")

sidebar_tabs_mobile = html.Div([
    html.H4("KAU 챗봇", className="text-primary fw-bold mb-4"),

    dbc.Tabs([
        dbc.Tab(label="사용법", tab_id="tab-usage", children=[
            html.P("👋 안녕하세요! 한국항공대 AI 도우미입니다.")
        ]),

        dbc.Tab(label="지난 기록", tab_id="tab-history", children=[
            html.P("기록은 오른쪽 화면에서 선택하세요.",
                   className="text-muted small mt-3")
        ]),
    ], id="tabs-mobile", active_tab="tab-usage"),

    html.Div(
        dbc.Button("🗑 기록 전체 삭제", id="clear-history-mobile",
                   color="danger", className="w-100 mt-3"),
        id="clear-btn-wrapper-mobile",
        style={"display": "none"}
    )
])

# ---------------------------------------------------
# 레이아웃
# ---------------------------------------------------

app.layout = dbc.Container([
    dcc.Store(id='chat-history-store', data=[], storage_type="local"),

    dbc.Offcanvas(
        [sidebar_tabs_mobile],
        id="offcanvas",
        title="메뉴",
        is_open=False
    ),

    dbc.Row([
        dbc.Col([sidebar_tabs], width=3, className="d-none d-md-block p-0"),

        dbc.Col([
            dbc.Row([
                dbc.Col([
                    dbc.Button("☰", id="open-offcanvas", n_clicks=0,
                               color="link", className="d-md-none",
                               style={"fontSize": "1.5rem"}),
                    html.H2("KAU 챗봇 Service",
                            className="d-inline-block mt-4 mb-4 fw-bold",
                            style={"color": "#002d62"})
                ], className="d-flex align-items-center justify-content-center")
            ]),

            dcc.Loading(
                id="loading-chat",
                type="circle",
                color="#002d62",
                fullscreen=False,
                children=html.Div(
                    id="chat-display",
                    className="chat-container mb-3"
                )
            ),

            html.Div([
                dbc.Button("🍱 오늘 학식", id="btn-food", size="sm", className="m-1 rounded-pill"),
                dbc.Button("🚇 지하철시간", id="btn-subway", size="sm", className="m-1 rounded-pill"),
                dbc.Button("📅 학사일정", id="btn-calendar", size="sm", className="m-1 rounded-pill"),
                dbc.Button("📚 도서관자리", id="btn-library", size="sm", className="m-1 rounded-pill"),
            ], className="mb-2 d-flex justify-content-center flex-wrap"),

            dbc.Row([
                dbc.Col(
                    dbc.Input(id="user-input", placeholder="질문을 입력하세요...",
                              type="text", style={"borderRadius": "25px"}),
                    width=10, xs=9),
                dbc.Col(
                    dbc.Button("전송", id="send-btn", color="primary",
                               className="w-100", style={"borderRadius": "25px"}),
                    width=2, xs=3),
            ], className="g-2"),

            html.Div(
                "※ AI 답변은 부정확할 수 있습니다.",
                className="text-center text-muted mt-3 mb-4",
                style={"fontSize": "0.75rem"}
            )
        ], width=12, md=9, className="px-4")
    ])
], fluid=True)

# ---------------------------------------------------
# 콜백
# ---------------------------------------------------

# 1) 모바일 메뉴 토글
@app.callback(
    Output("offcanvas", "is_open"),
    Input("open-offcanvas", "n_clicks"),
    State("offcanvas", "is_open")
)
def toggle_menu(n, is_open):
    if n:
        return not is_open
    return is_open

# 2) 탭에 따라 삭제 버튼 표시 (PC)
@app.callback(
    Output("clear-btn-wrapper-pc", "style"),
    Input("tabs-pc", "active_tab")
)
def toggle_clear_btn_pc(active_tab):
    if active_tab == "tab-history":
        return {"display": "block"}
    return {"display": "none"}

# 3) 탭에 따라 삭제 버튼 표시 (모바일)
@app.callback(
    Output("clear-btn-wrapper-mobile", "style"),
    Input("tabs-mobile", "active_tab")
)
def toggle_clear_btn_mobile(active_tab):
    if active_tab == "tab-history":
        return {"display": "block"}
    return {"display": "none"}

# 4) 기록 전체 삭제
@app.callback(
    Output("chat-history-store", "data", allow_duplicate=True),
    [Input("clear-history", "n_clicks"),
     Input("clear-history-mobile", "n_clicks")],
    prevent_initial_call=True
)
def clear_history(pc, mobile):
    return []

# 5) 지난 기록 목록 생성 (왼쪽 탭 리스트)
@app.callback(
    Output("history-list", "children"),
    Input("chat-history-store", "data")
)
def update_history_list(history):
    if not history:
        return []
    return [
        html.Div(
            f"• {msg['content']}",
            className="text-primary mb-2",
            id={"type": "history-item", "index": i},
            n_clicks=0
        )
        for i, msg in enumerate(history)
        if msg.get("speaker") == "user"
    ]

# 6) 지난 기록 클릭 → 대화 한 쌍만 표시
@app.callback(
    Output("chat-display", "children", allow_duplicate=True),
    Input({"type": "history-item", "index": ALL}, "n_clicks"),
    State("chat-history-store", "data"),
    prevent_initial_call=True
)
def load_history(clicks, history):
    if not clicks or all(c == 0 for c in clicks):
        return dash.no_update

    ctx = callback_context
    if not ctx.triggered:
        return dash.no_update

    clicked_id = ctx.triggered_id
    if not clicked_id:
        return dash.no_update

    idx = clicked_id["index"]
    if idx >= len(history):
        return dash.no_update

    user_msg = history[idx]
    ai_msg = history[idx + 1] if idx + 1 < len(history) else None

    ui = [
        html.Div(
            [html.Div(user_msg["content"], className="user-bubble")],
            className="message-row user-row"
        )
    ]

    if ai_msg:
        ui.append(render_ai_message(ai_msg))

    return ui

# 7) 질문 → 응답 생성 및 전체 채팅 렌더링
@app.callback(
    [Output("chat-display", "children", allow_duplicate=True),
     Output("user-input", "value"),
     Output("chat-history-store", "data", allow_duplicate=True)],
    [Input("send-btn", "n_clicks"),
     Input("user-input", "n_submit"),
     Input("btn-food", "n_clicks"),
     Input("btn-subway", "n_clicks"),
     Input("btn-calendar", "n_clicks"),
     Input("btn-library", "n_clicks")],
    [State("user-input", "value"),
     State("chat-history-store", "data")],
    prevent_initial_call=True
)
def update_chat(send, enter, food, subway, cal, lib, user_input, history):
    ctx = callback_context
    if not ctx.triggered:
        return dash.no_update, "", dash.no_update

    if history is None:
        history = []

    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    user_text = ""

    if trigger in ["send-btn", "user-input"]:
        user_text = user_input
    elif trigger == "btn-food":
        user_text = "오늘 학식 뭐야?"
    elif trigger == "btn-subway":
        user_text = "지하철 시간표 알려줘"
    elif trigger == "btn-calendar":
        user_text = "학사일정 알려줘"
    elif trigger == "btn-library":
        user_text = "도서관 자리 있어?"

    if not user_text:
        return dash.no_update, "", dash.no_update

    # 사용자 메시지 저장
    history.append({"speaker": "user", "content": user_text})

    # AI 응답 생성 (type 기반)
    ai_entry = {"speaker": "ai"}

    if "학식" in user_text:
        get_kau_menu()
        ai_entry["type"] = "food"

    elif "지하철" in user_text:
        now = datetime.now().strftime("%H:%M")
        up = [t for t in SUBWAY_UP if t > now][:3]
        down = [t for t in SUBWAY_DOWN if t > now][:3]
        ai_entry.update({
            "type": "subway",
            "time": now,
            "up": up,
            "down": down
        })

    elif "도서관" in user_text:
        ai_entry["type"] = "library"

    elif "학사" in user_text or "일정" in user_text:
        ai_entry["type"] = "academic"

    else:
        try:
            text = rag_core.get_ai_response(user_text)
        except Exception:
            text = "오류가 발생했습니다."
        ai_entry.update({
            "type": "text",
            "content": text
        })

    history.append(ai_entry)

    # 화면 다시 그리기
    chat_view = []
    for msg in history:
        if msg.get("speaker") == "user":
            chat_view.append(
                html.Div(
                    [html.Div(msg["content"], className="user-bubble")],
                    className="message-row user-row"
                )
            )
        else:
            chat_view.append(render_ai_message(msg))

    return chat_view, "", history


if __name__ == "__main__":
    app.run(debug=True)
