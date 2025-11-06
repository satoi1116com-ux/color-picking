import streamlit as st
import time, random, io, csv, base64, os
from typing import List, Dict
import streamlit.components.v1 as components
from pathlib import Path
import json
import gspread
from google.oauth2.service_account import Credentials
import traceback
import time
import math

# ---------- 設定 ----------
st.set_page_config(page_title="階層的色選択実験", layout="wide")
RESULTS_CSV = 'results.csv'
COLOR_RESULTS_CSV = 'color_results.csv'
UPLOAD_DIR = Path('uploads')
UPLOAD_DIR.mkdir(exist_ok=True)
META_RESULTS_CSV = 'meta_results.csv'



# ---------- ユーティリティ ----------
def safe_rerun():
    """Streamlit のバージョン差に対処してアプリを再実行するユーティリティ（フォールバックあり）。"""
    if hasattr(st, "experimental_rerun"):
        try:
            st.experimental_rerun()
            return
        except Exception:
            pass
    if hasattr(st, "rerun"):
        try:
            st.rerun()
            return
        except Exception:
            pass
    try:
        params = st.experimental_get_query_params()
        params["_rerun_ts"] = int(time.time()*1000)
        st.experimental_set_query_params(**params)
        st.stop()
    except Exception:
        return

def clamp(v, a, b):
    return max(a, min(b, v))

def path_to_hsl_separated(path: List[int]):
    baseHues = [0, 60, 120, 180, 240, 300]
    hueDeltas = [0, 30, 15, 8, 4, 2, 1, 0.5] 
    satBase = 70
    lightBase = 50
    stepAttribute = ['hue','hue','hue','lightness','lightness','saturation','saturation','final']
    filled = path + [1] * (8 - len(path))
    H = baseHues[filled[0]] if filled[0] < len(baseHues) else 0
    S = satBase
    L = lightBase
    for i in range(1, 8):
        m = filled[i] - 1
        attr = stepAttribute[i]
        if attr == 'hue':
            delta = hueDeltas[i] if i < len(hueDeltas) else 5
            H += m * delta
        elif attr == 'saturation':
            satChange = 25 if i == 5 else 15 
            S += m * satChange
        elif attr == 'lightness':
            lightChange = 20 if i == 3 else 10
            L += m * lightChange
        elif attr == 'final':
            H += m * 1.5
            S += m * 2
            L += m * 1.2
    H = (H % 360 + 360) % 360
    S = clamp(round(S), 8, 95)
    L = clamp(round(L), 3, 95)
    return {'H': H, 'S': S, 'L': L}

def hsl_to_hex(hsl: Dict[str, float]):
    h = hsl['H'] / 360.0
    s = hsl['S'] / 100.0
    l = hsl['L'] / 100.0
    def hue2rgb(p, q, t):
        if t < 0: t += 1
        if t > 1: t -= 1
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
        return p
    if s == 0:
        r = g = b = l
    else:
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = hue2rgb(p, q, h + 1/3)
        g = hue2rgb(p, q, h)
        b = hue2rgb(p, q, h - 1/3)
    def to_hex(x):
        return format(int(round(x * 255)), '02x')
    return f"#{to_hex(r)}{to_hex(g)}{to_hex(b)}"



def render_audio_player(audio_bytes: bytes, mime: str='audio/wav', autoplay=False, loop=False, height=90):
    if audio_bytes is None:
        st.write("音声ファイルが読み込まれていません。")
        return
    b64 = base64.b64encode(audio_bytes).decode('ascii')
    autoplay_attr = 'autoplay' if autoplay else ''
    loop_attr = 'loop' if loop else ''
    html = f"""
    <audio controls {autoplay_attr} {loop_attr} style="width:100%">
      <source src="data:{mime};base64,{b64}">
      Your browser does not support the audio element.
    </audio>
    """
    components.html(html, height=height)

def safe_filename(name: str) -> str:
    name = os.path.basename(name)
    return "".join(c for c in name if c.isalnum() or c in "._-")

@st.cache_resource(show_spinner=False)
def init_gsheets_client():
    """
    st.secrets に
      - gcp_service_account (JSON文字列)
      - gspread_spreadsheet_id (スプレッドシートID)
    を入れておくこと。
    戻り値: (client, spreadsheet) または (None, None)  — 初期化失敗時は None を返す
    """
    try:
        sa_json_text = st.secrets.get("gcp_service_account", None)
        ssid = st.secrets.get("gspread_spreadsheet_id", None)
        if not sa_json_text or not ssid:
            raise RuntimeError("st.secrets に gcp_service_account または gspread_spreadsheet_id がありません。")
        sa_info = json.loads(sa_json_text)
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(ssid)
        return client, spreadsheet
    except Exception as e:
        # 初期化失敗はアプリは続行するが、Google 書き込みは行われない
        st.error("Google Sheets の初期化に失敗しました（Secrets / API / 権限を確認してください）。")
        st.write(traceback.format_exc())
        return None, None

# 初期化（1回だけ実行される）
_gs_client, _gs_spreadsheet = init_gsheets_client()

def _ensure_worksheet_and_header(spreadsheet, sheet_title: str, header: list):
    """指定スプレッドシートにワークシートがなければ作り、ヘッダーを整備して返す。"""
    try:
        try:
            ws = spreadsheet.worksheet(sheet_title)
        except gspread.exceptions.WorksheetNotFound:
            # 新規作成（行数/列数は動的に増やせるが初期値を指定）
            ws = spreadsheet.add_worksheet(title=sheet_title, rows="1000", cols=str(len(header)))
            ws.append_row(header, value_input_option='USER_ENTERED')
        else:
            # 既存シートの先頭行がヘッダらしくなければ挿入（簡易対応）
            existing = ws.row_values(1)
            if not existing or len(existing) < len(header):
                ws.insert_row(header, index=1)
        return ws
    except Exception as e:
        st.warning(f"ワークシート準備でエラー: {e}")
        return None

def _retry_append(ws, row_values, max_retries=3, backoff_base=0.5):
    """
    gspread append_row を信頼性高く行うため小さなリトライを行う。
    """
    for attempt in range(1, max_retries+1):
        try:
            ws.append_row(row_values, value_input_option='USER_ENTERED')
            return True
        except Exception as ex:
            wait = backoff_base * (2 ** (attempt-1)) + (0.1 * attempt)
            time.sleep(wait)
            last_err = ex
    st.warning(f"Google Sheets への書き込みを試みましたが失敗しました: {last_err}")
    return False

def append_row_to_sheet(sheet_title: str, row_dict: dict, header: list):
    """
    sheet_title: ワークシート名
    row_dict: 辞書（header の要素をキーとする）
    header: ワークシートの列順
    """
    if _gs_spreadsheet is None:
        # 初期化失敗または未設定 → 無視（ローカルCSVは残す）
        return False
    try:
        ws = _ensure_worksheet_and_header(_gs_spreadsheet, sheet_title, header)
        if ws is None:
            return False
        row = [row_dict.get(col, "") for col in header]
        return _retry_append(ws, row)
    except Exception as e:
        st.warning(f"Google Sheets 書き込み例外: {e}")
        return False

# ---------------- 既存CSV保存 + Google Sheets 両対応関数 ----------------
# 既存の append_result_csv 等の代替として使います。呼び出し箇所を置換してください。

def append_result_csv_and_sheet(row: dict):
    """段階的選択結果をローカルCSVに追記し、Google Sheets にも append する。"""
    header = ['participant_id','trial','audioName','path','finalHex','finalH','finalS','finalL','stepRTs_ms','totalRT_ms','timestamp','practice','loop_playback_used']
    # ローカルCSV保存（既存の実装と同様）
    exists = os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow(row)
    # Google Sheets 保存（失敗しても処理続行）
    try:
        append_row_to_sheet("results", row, header)
    except Exception as e:
        st.warning(f"Google Sheets 書込失敗 (results): {e}")

def append_color_csv_and_sheet(row: dict):
    """色選択結果をローカルCSVに追記し、Google Sheets にも append する。"""
    header = ['participant_id','trial','audioName','pickedHex','pickedH','pickedS','pickedL','timestamp','loop_playback_used']
    exists = os.path.exists(COLOR_RESULTS_CSV)
    with open(COLOR_RESULTS_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow(row)
    try:
        append_row_to_sheet("color_results", row, header)
    except Exception as e:
        st.warning(f"Google Sheets 書込失敗 (color_results): {e}")

def append_meta_csv_and_sheet(row: dict):
    """メタ情報をローカルCSVに追記し、Google Sheets にも append する。"""
    # meta のヘッダは既存の定義に合わせてください（例: q1..q18 等）
    header = ['participant_id','task_order','timestamp'] + [f"q{i}" for i in range(1,19)] + ['n_color_picks','n_hierarchical_trials']
    exists = os.path.exists(META_RESULTS_CSV)
    with open(META_RESULTS_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow(row)
    try:
        append_row_to_sheet("meta_results", row, header)
    except Exception as e:
        st.warning(f"Google Sheets 書込失敗 (meta_results): {e}")

# ---------- session 初期化 ----------
if 'page' not in st.session_state:
    st.session_state['page'] = 'consent'
if 'participant_id' not in st.session_state:
    st.session_state['participant_id'] = f"{int(time.time())}_{random.randint(1000,9999)}"

if 'task_order' not in st.session_state:
    tasks = ['stage', 'color_picker']
    random.shuffle(tasks)
    st.session_state['task_order'] = tasks

if 'audio_files' not in st.session_state: st.session_state['audio_files'] = []
if 'trials_order' not in st.session_state: st.session_state['trials_order'] = []
if 'current_trial_index' not in st.session_state: st.session_state['current_trial_index'] = 0
if 'results' not in st.session_state: st.session_state['results'] = []
if 'current_path' not in st.session_state: st.session_state['current_path'] = []
if 'step_start_time' not in st.session_state: st.session_state['step_start_time'] = None
if 'step_rts' not in st.session_state: st.session_state['step_rts'] = []
if 'practice' not in st.session_state: st.session_state['practice'] = False
if 'played_this_stage' not in st.session_state: st.session_state['played_this_stage'] = False
if 'listening_complete' not in st.session_state: st.session_state['listening_complete'] = False
if 'continuous_play_mode' not in st.session_state: st.session_state['continuous_play_mode'] = False
if 'color_picker_continuous_play' not in st.session_state: st.session_state['color_picker_continuous_play'] = False
if 'color_picker_listening_complete' not in st.session_state: st.session_state['color_picker_listening_complete'] = False
if 'settings' not in st.session_state:
    st.session_state['settings'] = {'shuffle_trials': True, 'once_per_stage': False, 'autoplay': False, 'loop_audio': False}
if 'color_trials_order' not in st.session_state: st.session_state['color_trials_order'] = []
if 'color_trial_index' not in st.session_state: st.session_state['color_trial_index'] = 0
if 'color_results' not in st.session_state: st.session_state['color_results'] = []
if 'last_uploaded_names' not in st.session_state: st.session_state['last_uploaded_names'] = []
if 'next_task_to_start' not in st.session_state:
    st.session_state['next_task_to_start'] = None
if 'test_stage_path' not in st.session_state:
    st.session_state['test_stage_path'] = []
if 'audio_check_continuous_play' not in st.session_state:
    st.session_state['audio_check_continuous_play'] = False
if 'reset_counts' not in st.session_state:
    st.session_state['reset_counts'] = {}
# ---------- uploads/ からの自動読み込み（参加者用） ----------
if not st.session_state.get('audio_files'):
    try:
        files_on_disk = sorted([
            p for p in UPLOAD_DIR.iterdir() 
            if p.is_file() and not p.name.startswith('_check_sound.')
        ])
    except Exception:
        files_on_disk = []
    if files_on_disk:
        st.session_state['audio_files'] = []
        for p in files_on_disk:
            try:
                with open(p, 'rb') as f: data = f.read()
                ext = p.suffix.lower().lstrip('.')
                mime = 'audio/wav'
                if ext in ['mp3']: mime = 'audio/mpeg'
                elif ext in ['ogg']: mime = 'audio/ogg'
                elif ext in ['m4a','mp4','aac']: mime = 'audio/mp4'
                st.session_state['audio_files'].append({'id': f"disk_{p.stem}", 'name': p.name, 'safe_name': p.name, 'data': data, 'mime': mime})
            except Exception as e:
                st.warning(f"failed to load {p.name}: {e}")
        if not st.session_state.get('trials_order'):
            n = len(st.session_state['audio_files'])
            if n == 0:
                st.session_state['trials_order'] = [None]
            else:
                st.session_state['trials_order'] = list(range(n))
                if st.session_state['settings'].get('shuffle_trials', True):
                    random.shuffle(st.session_state['trials_order'])
                st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()

# ---------- UI: 管理者/参加者ページ選択（簡易） ----------
st.title("色選択手法比較実験アプリ")
st.markdown("---")

def go_to(p):
    st.session_state['page'] = p
    safe_rerun()

# ---------- 管理者判定 ----------
# ---------- 管理者判定（隠しURL: 管理者ログインを出す） ----------
import hashlib
USE_HASHED_PASSWORDS = True
# 管理者情報の取得（推奨: st.secrets へ入れる）
# .streamlit/secrets.toml に下のように書くと安全です:

ADMIN_USERS = dict(st.secrets["admin_users_hash"])



def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

# セッション用キー初期化
if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False
if "admin_user" not in st.session_state:
    st.session_state["admin_user"] = ""

# クエリ判定（隠しURLでアクセスしたかどうかだけを見る）
qparams = st.experimental_get_query_params()
# 隠しURLのトリガーが欲しければここで判定（例: ?admin=1 または ?admin=login）
qp_admin = ('admin' in qparams and qparams['admin'] and str(qparams['admin'][0]).lower() in ['1','true','yes','login'])

# 管理者として既にログイン済み（セッション）であれば管理者 UI を表示する
if st.session_state.get("is_admin", False):
    is_admin = True
else:
    is_admin = False

# --- 隠しURL（qp_admin）がついている場合はログインフォームを表示 ---
if qp_admin and not is_admin:
    st.header("管理者ログイン")
    st.markdown("このページは管理者用です。ID とパスワードを入力してください。")
    with st.form("admin_login_form"):
        uname = st.text_input("管理者ID")
        pwd = st.text_input("パスワード", type="password")
        submit = st.form_submit_button("ログイン")
        if submit:
            authenticated = False
            if USE_HASHED_PASSWORDS:
                try:
                    admin_hashes = dict(st.secrets["admin_users_hash"])
                except Exception:
                    admin_hashes = {}
                if uname in admin_hashes and _sha256(pwd) == admin_hashes[uname]:
                    authenticated = True
            else:
                if uname in ADMIN_USERS and pwd == ADMIN_USERS[uname]:
                    authenticated = True

            if authenticated:
                st.session_state["is_admin"] = True
                st.session_state["admin_user"] = uname
                st.success(f"ログイン成功: {uname}")
                # 管理ページを表示するためにページ再実行
                safe_rerun()
            else:
                st.error("ID またはパスワードが正しくありません。")
# ---------- 管理者ページ ----------
if st.session_state.get("is_admin", False):
    cols = st.columns([6,1])
    with cols[0]:
        st.header(f"管理者ダッシュボード — {st.session_state.get('admin_user','(不明)')}")
    with cols[1]:
        if st.button("ログアウト"):
            st.session_state["is_admin"] = False
            st.session_state["admin_user"] = ""
            st.success("ログアウトしました。")
            safe_rerun()

        st.markdown("---")
        st.subheader("音量チェック用 サウンド設定")
        
        # チェックサウンドのファイルパスをglobで探す
        current_check_sound_path = None
        current_check_sound_name = None
        # _check_sound.* という名前のファイルを探す
        check_sound_files = list(UPLOAD_DIR.glob('_check_sound.*'))
        if check_sound_files:
            current_check_sound_path = check_sound_files[0]
            current_check_sound_name = current_check_sound_path.name

        uploaded_check = st.file_uploader(
            "音量チェック専用の音声ファイルをアップロード ( .wav, .mp3, .ogg, .m4a )", 
            type=['wav','mp3','ogg','m4a'], 
            key="check_sound_uploader"
        )
        
        if uploaded_check:
            try:
                data = uploaded_check.read()
                # アップロードされたファイルの拡張子を取得
                ext = Path(uploaded_check.name).suffix.lower()
                # 新しいファイル名 (例: _check_sound.mp3)
                new_check_sound_name = f"_check_sound{ext}"
                new_check_sound_path = UPLOAD_DIR / new_check_sound_name
                
                # 既存のチェックサウンド（違う拡張子でも）を削除
                if current_check_sound_path and current_check_sound_path.exists():
                    current_check_sound_path.unlink()
                    
                # 新しいファイルを保存
                with open(new_check_sound_path, 'wb') as out:
                    out.write(data)
                
                st.success(f"音量チェック用サウンドを '{new_check_sound_name}' として保存しました。")
                # ページを再読み込みして下の表示に反映
                safe_rerun() 
                
            except Exception as e:
                st.error(f"チェックサウンドの保存に失敗: {e}")

        # 現在のチェックサウンドを表示・再生
        if current_check_sound_path:
            st.write(f"現在のチェックサウンド: **{current_check_sound_name}**")
            try:
                with open(current_check_sound_path, 'rb') as f:
                    check_data = f.read()
                # Mimeタイプを推測
                ext = current_check_sound_path.suffix.lower()
                mime = 'audio/wav'
                if ext == '.mp3': mime = 'audio/mpeg'
                elif ext == '.ogg': mime = 'audio/ogg'
                elif ext in ['.m4a', '.mp4', '.aac']: mime = 'audio/mp4'
                
                render_audio_player(check_data, mime=mime, autoplay=False, loop=False, height=90)
            except Exception as e:
                st.error(f"チェックサウンドの読み込み/再生に失敗: {e}")
        else:
            st.warning("音量チェック用サウンドが設定されていません。参加者ページでは代替の音源が使用されます。")


        st.markdown("---")

    st.header("管理者: 音声アップロード / ログ確認")
    st.markdown("uploads フォルダに音声ファイルを配置すると参加者ページで利用できます。")
    uploaded = st.file_uploader("音声ファイルをアップロード（複数可）", accept_multiple_files=True, type=['wav','mp3','ogg','m4a'])
    if uploaded:
        saved_count = 0
        for f in uploaded:
            try:
                data = f.read()
                safe_name = safe_filename(f.name)
                save_path = UPLOAD_DIR / safe_name
                with open(save_path, 'wb') as out:
                    out.write(data)
                saved_count += 1
            except Exception as e:
                st.error(f"ファイル保存に失敗しました ({f.name}): {e}")
        
        reloaded = []
        try:
            files_on_disk = sorted([
                p for p in UPLOAD_DIR.iterdir() 
                if p.is_file() and not p.name.startswith('_check_sound.')
            ])
            for p in files_on_disk:
                with open(p, 'rb') as fh: data = fh.read()
                ext = p.suffix.lower().lstrip('.')
                mime = 'audio/wav'
                if ext in ['mp3']: mime = 'audio/mpeg'
                elif ext in ['ogg']: mime = 'audio/ogg'
                elif ext in ['m4a','mp4','aac']: mime = 'audio/mp4'
                reloaded.append({'id': f"disk_{p.stem}", 'name': p.name, 'safe_name': p.name, 'data': data, 'mime': mime})
            st.session_state['audio_files'] = reloaded
        except Exception as e:
            st.error(f"uploads フォルダ読み込み失敗: {e}")

        n = len(st.session_state['audio_files'])
        st.session_state['trials_order'] = list(range(n)) if n > 0 else [None]
        if n > 0 and st.session_state['settings'].get('shuffle_trials', True):
            random.shuffle(st.session_state['trials_order'])
        st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()
        st.session_state['current_trial_index'] = 0
        st.session_state['color_trial_index'] = 0
        st.session_state['results'] = []
        st.session_state['current_path'] = []
        st.session_state['played_this_stage'] = False
        st.session_state['color_results'] = []
        st.session_state['listening_complete'] = False
        st.session_state['continuous_play_mode'] = False
        st.session_state['color_picker_listening_complete'] = False
        st.session_state['color_picker_continuous_play'] = False
        st.success(f"{saved_count} 件を保存・反映しました（合計 {n} 件）。")
        safe_rerun()

    if st.button("手動: トライアル順リセット＆実験初期化"):
        n = len(st.session_state.get('audio_files', []))
        st.session_state['trials_order'] = list(range(n)) if n > 0 else [None]
        if n > 0 and st.session_state['settings'].get('shuffle_trials', True):
            random.shuffle(st.session_state['trials_order'])
        st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()
        st.session_state['current_trial_index'] = 0
        st.session_state['color_trial_index'] = 0
        st.session_state['results'] = []
        st.session_state['current_path'] = []
        st.session_state['played_this_stage'] = False
        st.session_state['color_results'] = []
        st.session_state['listening_complete'] = False
        st.session_state['continuous_play_mode'] = False
        st.session_state['color_picker_listening_complete'] = False
        st.session_state['color_picker_continuous_play'] = False
        st.success("初期化しました。")
        safe_rerun()

    st.markdown("---")
    st.subheader("現在読み込まれているファイル（管理）")
    audio_list = st.session_state.get('audio_files', [])
    if not audio_list:
        st.write("まだファイルが読み込まれていません。")
    else:
        for idx, a in enumerate(audio_list):
            cols = st.columns([3,1,1,1,1])
            with cols[0]: st.markdown(f"**{idx+1}. {a.get('name')}**")
            with cols[1]:
                if st.button("再生", key=f"play_{a.get('safe_name')}_{idx}"):
                    render_audio_player(a.get('data'), mime=a.get('mime'), autoplay=True, loop=False, height=100)
            with cols[2]: st.download_button(f"Download", data=a.get('data'), file_name=a.get('name'), mime=a.get('mime'), key=f"dl_{a.get('safe_name')}_{idx}")
            with cols[3]:
                if st.button("削除", key=f"del_{a.get('safe_name')}_{idx}"):
                    filepath = UPLOAD_DIR / a.get('safe_name')
                    if filepath.exists(): filepath.unlink()
                    st.session_state['audio_files'] = [x for x in st.session_state['audio_files'] if x.get('safe_name') != a.get('safe_name')]
                    st.success(f"{a.get('safe_name')} を削除しました。反映するには「手動リセット」を押してください。")
                    safe_rerun()
    st.markdown("---")
    st.header("ログ / 結果のダウンロード")
    if os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV, 'r', encoding='utf-8') as f:
            st.download_button("results.csv をダウンロード", data=f.read(), file_name="results.csv", mime="text/csv")
    if os.path.exists(COLOR_RESULTS_CSV):
        with open(COLOR_RESULTS_CSV, 'r', encoding='utf-8') as f:
            st.download_button("color_results.csv をダウンロード", data=f.read(), file_name="color_results.csv", mime="text/csv")
    if os.path.exists(META_RESULTS_CSV):
        with open(META_RESULTS_CSV, 'r', encoding='utf-8') as f:
            st.download_button("meta_results.csv をダウンロード", data=f.read(), file_name="meta_results.csv", mime="text/csv")

# 参加者ページフロー
elif st.session_state.get('page') == 'consent':
    st.header("実験説明と参加への同意")
    st.markdown("""
    ### 1.	実験の目的と意義
    本実験では、人々が音や音楽を聴いた際に色を想起する知覚現象を扱う実験において、2種類の色選択手法を比較します。こちらの現象についての実験を行い、実験データの分析を行うことで、今後の同分野の研究で、より信頼性の高いデータを収集するための最適な実験環境を提案することを目的としています。
    ### 2.	実験の概要
    本実験は、オンラインにて実施します。参加者の皆様には、静かな環境でPCとヘッドホンまたはイヤホンをご用意いただき、画面の指示に従って作業を進めていただきます。提示される音刺激に対して下記の二つの手法を用いて想起した色を選択する作業を行っていただきます。・カラーピッカー ・段階的な色選択 各手法で色を選択した直後に、色選択に関するアンケートに回答してください。さらに、全手法での色選択及びアンケート回答後には、全体のアンケートに回答してください。二つの手法の順序は参加者ごとに異なります。作業時間は休憩時間5分を含めて計45分を想定しています。
    ### 3.	実験参加に伴う危険
    ヘッドホンを装着してディスプレイを見ながら、提示される音を聴いて画面上で色の選択を繰り返し行っていただくため、疲労や精神的負担を感じてしまう可能性があります。実験中にそのような危険性を感じた場合には、いつでも実験の中断、または参加の取り消しを行うことができます。実験は全体で45分程度を予定しています。また、実験中には5分ほどの休憩を設定していますが、疲労を感じた場合は適宜休憩をとっていただくことが可能です。 
    ### 4.	個人情報の取り扱いについて
    本実験へのご参加は任意です。また、本研究では個人が特定されない形でデータを収集するため、実験実施後に参加の同意を取り消すことはできません。 この点についてご理解いただいた上で、参加をご判断ください。実験に参加しないことによる不利益は一切ありません。
    ### 5.	問い合わせ先について
    実験担当者	筑波大学情報学群情報メディア創成学類 4年 山﨑聖生 
                            e-mail: s2210284@u.tsukuba.ac.jp
    
    実験責任者	筑波大学図書館情報メディア系 助教 飯野なみ
    〒305-8550 茨城県つくば市春日1-2 
    e-mail: niino@slis.tsukuba.ac.jp
                
    本実験は、図書館情報メディア系研究倫理審査委員会の承認を得て実施しています
    """)        
    if st.checkbox("上記の説明内容を理解したうえで、私の自由意思により本実験への参加に同意します"):
        if st.button("次へ"):
            go_to('audio_check')

# check page
elif st.session_state.get('page') == 'audio_check':
    st.header("音と操作の確認")
    st.markdown("""
    - 周囲の環境が静かであることを確認してください。
    - ヘッドホンまたはイヤホンを着用してください。
    - ブラウザ内のズーム機能で適切な画面の大きさに調整してください。
    - まず、音の確認を行ってください。必要であれば、音量を適切に調整してください。音が適切に聞こえるか、音のループ再生が適切に行われているかを確認してください。
    - 次に、操作の確認を行ってください。実際に操作を行って適切に動作が行われているかを確認してください。
    - 問題なければ「確認済み」にチェックを入れて次へ進んでください。
    """)



    # 2. チェック用サウンド (管理者設定)
    st.subheader("1. 音の確認")
    st.markdown("---")
    check_sound_data, check_sound_mime, check_sound_name = None, None, None
    check_sound_files = list(UPLOAD_DIR.glob('_check_sound.*'))
    if check_sound_files:
        check_sound_path = check_sound_files[0]
        try:
            with open(check_sound_path, 'rb') as f:
                check_sound_data = f.read()
            
            ext = check_sound_path.suffix.lower()
            check_sound_mime = 'audio/wav'
            if ext == '.mp3': check_sound_mime = 'audio/mpeg'
            elif ext == '.ogg': check_sound_mime = 'audio/ogg'
            elif ext in ['.m4a', '.mp4', '.aac']: check_sound_mime = 'audio/mp4'
            check_sound_name = check_sound_path.name
            # st.write(f"再生ファイル: **{check_sound_name}**")

        except Exception as e:
            st.error(f"チェックサウンドの読み込みに失敗: {e}")
            check_sound_data = None
    
    # フォールバック: _check_sound がない場合、audio_files[0] を使う
    if check_sound_data is None and st.session_state.get('audio_files'):
        st.info("管理者設定のチェックサウンドが見つかりません。実験用の最初の音源を再生します。")
        try:
            first = st.session_state['audio_files'][0]
            check_sound_data = first['data']
            check_sound_mime = first.get('mime','audio/wav')
            check_sound_name = first.get('name')
            st.write(f"再生ファイル: **{check_sound_name}**")
        except Exception:
            st.error("実験用音源の読み込みにも失敗しました。")

    # 再生UIの描画
    if check_sound_data:
        # 通常の1回再生
        st.write("まず、下の再生ボタンを押して音を一度最後までお聞きください。")
        render_audio_player(check_sound_data, mime=check_sound_mime, autoplay=False, loop=False)

        st.markdown("---")
        # ループ再生コントロール (本番タスクと同様)
        st.write("次に下のボタンを押して問題なくループ再生ができているか確認してください。")
        if not st.session_state.get('audio_check_continuous_play'):
            if st.button("ループ再生", key="check_start_continuous"):
                st.session_state['audio_check_continuous_play'] = True; safe_rerun()
        else:
            if st.button("再生を停止", key="check_stop_continuous"):
                st.session_state['audio_check_continuous_play'] = False; safe_rerun()
        
        if st.session_state.get('audio_check_continuous_play'):
            st.write("ループ再生中...")
            render_audio_player(check_sound_data, mime=check_sound_mime, autoplay=True, loop=True)
    else:
        st.error("再生できる音量チェック用の音声ファイルがありません。管理者に連絡してください。")

    st.markdown("---")
    st.header("2. 操作テスト")
    st.markdown("2種類の実験操作をテストしてください。**ここで選んだ色は保存されません。**")
    st.markdown("---")
    col1a,col1b = st.columns(2)


    with col1a:
        st.markdown("#### テスト1: 段階的な選択")
        st.write("""
        これは、本番の「**段階的な色選択**」タスクの操作テストです。
        
        右側に表示されている選択肢から、最もイメージに近いと感じる色を1つ選び、その下のボタンを押してください。
        
        これを合計8回（8段階）繰り返すと、最終的な色が決定されます。
        
        *本番のタスクでは、この操作を複数の音刺激に対して行っていただきます。*
        """)
    
    with col1b:

        st.write("選択肢から1つを選ぶ操作を8段階繰り返します。ボタンを押すと次の段階に進みます。")

        # セッションから現在のテストパスを取得
        current_test_path = st.session_state.get('test_stage_path', [])
        current_step_number = len(current_test_path) + 1

        if current_step_number > 8:
            # 8段階終了時の表示
            st.write(f"テスト完了 (8/8)")
            try:
                final_hsl = path_to_hsl_separated(current_test_path)
                final_hex = hsl_to_hex(final_hsl)
                st.markdown(f'<div style="height:80px;border-radius:5px;background:{final_hex};"></div>', unsafe_allow_html=True)
                st.caption(f"最終色: {final_hex}")
            except Exception as e:
                st.error(f"テスト色描画エラー: {e}")
            
            if st.button("もう一度テストする", key="test_stage_reset_final"):
                st.session_state['test_stage_path'] = [] # パスをリセット
                safe_rerun()
        else:
            # 途中の段階の表示
            st.write(f"段階 {current_step_number} / 8")
            try:
                if current_step_number == 1:
                    options = [{'digit': d, 'hex': hsl_to_hex(path_to_hsl_separated(current_test_path + [d]))} for d in range(6)]
                    test_cols = st.columns(6)
                else:
                    options = [{'digit': d, 'hex': hsl_to_hex(path_to_hsl_separated(current_test_path + [d]))} for d in [0,1,2]]
                    test_cols = st.columns(3)
                
                for i, opt in enumerate(options):
                    with test_cols[i]:
                        st.markdown(f'<div style="height:80px;border-radius:5px;background:{opt["hex"]};"></div>', unsafe_allow_html=True)
                        # キーがステップごとに変わるようにする
                        if st.button(f"({i+1})", key=f"test_stage_s{current_step_number}_o{i}"):
                            st.session_state['test_stage_path'].append(opt['digit'])
                            safe_rerun()
            except Exception as e:
                st.error(f"テスト1の描画エラー: {e}")
                
            if current_step_number > 1:
                if st.button("テストをリセット", key="test_stage_reset_mid"):
                    st.session_state['test_stage_path'] = [] # パスをリセット
                    safe_rerun()

    st.markdown("\n")
    st.markdown("\n")
    st.markdown("---")
    col2a,col2b = st.columns(2)
    with col2a:
        st.markdown("#### テスト2: 自由色選択")
        st.write("""
        これは、本番の「**カラーピッカーでの色選択**」タスクの操作テストです。
        
        右側のカラーピッカー（色選択ツール）をクリックして、色を自由に選んでみてください。
                 
        この際、下部分の数値の欄は使わずに上の2つの色空間のみで選択してください。
        
        ピッカーで選んだ色が、その下のプレビュー領域に反映されることを確認してください。
        
        *本番のタスクでは、この操作で色を1つ決定し、「この色を保存して次へ」ボタンを押していただきます。*
        """)

    with col2b:

        st.write("カラーピッカーが開き、色が変わることを確認してください。")

        if 'test_color_picker_val' not in st.session_state:
            st.session_state['test_color_picker_val'] = '#808080'

        def update_test_color():
            st.session_state['test_color_picker_val'] = st.session_state['test_color_picker_widget']

        test_color = st.color_picker(
            ":arrow_down: テスト用の色を選択", 
            key='test_color_picker_widget', 
            value=st.session_state['test_color_picker_val'],
            on_change=update_test_color,
            width="stretch"
        )

        st.markdown(f'<div style="width:100%;height:80px;background-color:{st.session_state["test_color_picker_val"]};border:1px solid #d3d3d3;border-radius:5px;"></div>', unsafe_allow_html=True)
        st.caption(f"HEX: `{st.session_state['test_color_picker_val']}`")
    st.markdown("\n")
    st.markdown("---")
    if st.checkbox("再生・操作確認済み（音・操作ともに問題なし）", key="audio_and_op_checked"):
        if st.button("次へ（実験開始）"):
            first_task = st.session_state['task_order'][0]
            go_to(first_task)



# stage (階層的色選択)
elif st.session_state.get('page') == 'stage':
    st.header("段階的な色選択")
    st.markdown("このページでは、提示される選択肢から想起した色に近いものを選び続けて色を決定します。全ての音について選び終わるとアンケートへ進みます。")

    if st.session_state['current_trial_index'] >= len(st.session_state['trials_order']):
        st.info("すべての試行が終了しました。短いアンケートにお答えください。")
        time.sleep(0.5)
        go_to('questionnaire') # stage の後のアンケートへ
        
    else:
        idx = st.session_state['trials_order'][st.session_state['current_trial_index']]
        audio_name = '(なし)' if idx is None else st.session_state['audio_files'][idx]['name']
        st.write(f"トライアル {st.session_state['current_trial_index']+1} / {len(st.session_state['trials_order'])} ")
        audio_bytes = None
        if idx is not None:
            audio_bytes = st.session_state['audio_files'][idx]['data']
            audio_mime = st.session_state['audio_files'][idx].get('mime','audio/wav')

        if not st.session_state.get('listening_complete'):
            st.markdown("---")
            st.subheader(f"トライアル {st.session_state['current_trial_index']+1} の再生")
            st.info("まず、今回の音刺激を一度最後までお聞きください。\n\n再生が終了したら、下のボタンを押して色選択に進んでください。")
            render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=False)
            if st.button("再生が終了したので、色選択に進む"):
                st.session_state['listening_complete'] = True
                safe_rerun()
        else:
            colp, _ = st.columns([3,1])
            with colp:
                st.markdown("**再生コントロール**")
                if not st.session_state.get('continuous_play_mode'):
                    if st.button("音をループ再生"):
                        st.session_state['continuous_play_mode'] = True; safe_rerun()
                else:
                    if st.button("再生を停止"):
                        st.session_state['continuous_play_mode'] = False; safe_rerun()
                if st.session_state.get('continuous_play_mode'):
                    st.write("ループ再生中...")
                    render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=True)
            
            st.markdown("---")
            st.markdown("### 色選択（8段階）")
            current_step_number = len(st.session_state.get('current_path', [])) + 1
            st.write(f"段階 {current_step_number} / 8")

            # 検討ポイント！！！！！！！！！！！
            if current_step_number > 1:
                if st.button("このトライアルの選択をリセット", key=f"reset_stage_trial_{st.session_state['current_trial_index']}"):
                    current_trial_idx = st.session_state['current_trial_index']
                    current_count = st.session_state.get('reset_counts', {}).get(current_trial_idx, 0)
                    st.session_state['reset_counts'][current_trial_idx] = current_count + 1
                    st.session_state['current_path'] = []
                    st.session_state['step_rts'] = []
                    st.session_state['step_start_time'] = None
                    st.warning("このトライアルの選択をリセットしました。段階1からやり直してください。")
                    time.sleep(1) # 警告を読ませる
                    safe_rerun()

            if current_step_number == 1:
                st.write("音に対して想起した色に近い色を6つの色から1つ選んでください。ボタンを押すと次の段階に進みます。")
                options = [{'digit': d, 'hex': hsl_to_hex(path_to_hsl_separated(st.session_state['current_path'] + [d]))} for d in range(6)]
                cols = st.columns(6)
            else:
                st.write("音に対して想起した色に近い色を3つの色から1つ選んでください。ボタンを押すと次の段階に進みます。")
                options = [{'digit': d, 'hex': hsl_to_hex(path_to_hsl_separated(st.session_state['current_path'] + [d]))} for d in [0,1,2]]
                cols = st.columns(3)
            
            for i, opt in enumerate(options):
                with cols[i]:
                    st.markdown(f'<div style="height:140px;border-radius:10px;background:{opt["hex"]};display:flex;align-items:center;justify-content:center;font-weight:bold;color:#000;margin-bottom:8px"></div>', unsafe_allow_html=True)
                    if st.button(f"この色を選ぶ ({i+1})", key=f"sel_{st.session_state['current_trial_index']}_{current_step_number}_{i}"):
                        if st.session_state['step_start_time'] is None: st.session_state['step_start_time'] = time.time()
                        rt_ms = int((time.time() - st.session_state['step_start_time'])*1000)
                        st.session_state['step_rts'].append(rt_ms)
                        st.session_state['current_path'].append(opt['digit'])
                        st.session_state['step_start_time'] = None
                        if len(st.session_state['current_path']) >= 8:
                            final_hsl = path_to_hsl_separated(st.session_state['current_path'])
                            current_trial_idx = st.session_state['current_trial_index']
                            reset_count_for_this_trial = st.session_state.get('reset_counts', {}).get(current_trial_idx, 0)
                            trial_record = {
                                'participant_id': st.session_state.get('participant_id'), 
                                'trial': st.session_state['current_trial_index']+1, 'audioName': audio_name,
                                'path': ''.join(map(str,st.session_state['current_path'])), 'finalHex': hsl_to_hex(final_hsl),
                                'finalH': round(final_hsl['H'],2), 'finalS': final_hsl['S'], 'finalL': final_hsl['L'],
                                'stepRTs_ms': '|'.join(map(str,st.session_state.get('step_rts',[]))), 'totalRT_ms': sum(st.session_state.get('step_rts', [])),
                                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'), 'practice': False,
                                'loop_playback_used': st.session_state.get('continuous_play_mode', False),
                                'reset_count': reset_count_for_this_trial
                            }
                            append_result_csv_and_sheet(trial_record)
                            st.session_state['current_trial_index'] += 1
                            st.session_state['current_path'] = []
                            st.session_state['step_rts'] = []
                            st.session_state['listening_complete'] = False
                            st.session_state['continuous_play_mode'] = False
                            time.sleep(0.3)
                        safe_rerun()

# questionnaire (段階的選択の後)
elif st.session_state.get('page') == 'questionnaire':
    st.header("個別アンケート（段階的な色選択について）")
    with st.form("qform_stage"):
        q1 = st.radio("Q1.満足度: あなたが選んだ色は、音から感じたイメージとどの程度一致していましたか？", ("1: 全く一致しない", "2: かなり一致しない", "3: 少し一致しない", "4: どちらともいえない", "5: 少し一致する", "6: かなり一致する", "7: 完璧に一致する"))
        q2 = st.radio("Q2.操作感: 色の選択操作は、どの程度、簡単で直感的でしたか？", ("1: 非常に難しい", "2: かなり難しい", "3: 少し難しい", "4: どちらともいえない", "5: 少し簡単", "6: かなり簡単", "7: 非常に簡単"))
        q3 = st.radio("Q3.認知的負荷: 色を選ぶ作業は、精神的にどの程度大変でしたか？", ("1: 全く大変でない", "2: あまり大変でない", "3: 少し大変だった", "4: どちらともいえない", "5: やや大変だった", "6: かなり大変だった", "7: 非常に大変だった"))
        if st.form_submit_button("次へ"):
            st.session_state.setdefault('meta_answers', {})['q1'] = q1
            st.session_state.setdefault('meta_answers', {})['q2'] = q2
            st.session_state.setdefault('meta_answers', {})['q3'] = q3
            
            current_task_index = st.session_state['task_order'].index('stage')
            if current_task_index + 1 < len(st.session_state['task_order']):
                next_task = st.session_state['task_order'][current_task_index + 1]
                st.session_state['next_task_to_start'] = next_task
                go_to('transition_page')
            else:
                go_to('final_survey')

# color picker (自由色選択)
elif st.session_state.get('page') == 'color_picker':
    st.header("カラーピッカーでの色選択")
    st.markdown("このページでは、音に対して想起した色をカラーピッカーを用いて選んでいただきます。全ての音について選び終わるとアンケートへ進みます。")

    if st.session_state['color_trial_index'] >= len(st.session_state['color_trials_order']):
        st.info("全ての音刺激について色の選択が終わりました。短いアンケートにお答えください。")
        time.sleep(0.5)
        go_to('post_questionnaire') 
    else:
        cidx = st.session_state['color_trials_order'][st.session_state['color_trial_index']]
        audio_name = '(なし)' if cidx is None else st.session_state['audio_files'][cidx]['name']
        st.write(f"トライアル {st.session_state['color_trial_index']+1} / {len(st.session_state['color_trials_order'])}")
        
        audio_bytes = None
        if cidx is not None:
            audio_bytes = st.session_state['audio_files'][cidx]['data']
            audio_mime = st.session_state['audio_files'][cidx].get('mime','audio/wav')

        if not st.session_state.get('color_picker_listening_complete'):
            st.markdown("---")
            st.subheader(f"トライアル {st.session_state['color_trial_index']+1} の再生")
            st.info("まず、今回の音刺激を一度最後までお聞きください。\n\n再生が終了したら、下のボタンを押して色選択に進んでください。")
            render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=False)
            if st.button("再生が終了したので、色選択に進む", key="cp_finish_listening"):
                st.session_state['color_picker_listening_complete'] = True
                safe_rerun()
        else:
            col1, col2 = st.columns([1,1])
            with col1:
                st.markdown("**再生コントロール**")
                if not st.session_state.get('color_picker_continuous_play'):
                    if st.button("音をループ再生", key="cp_start_continuous"):
                        st.session_state['color_picker_continuous_play'] = True; safe_rerun()
                else:
                    if st.button("再生を停止", key="cp_stop_continuous"):
                        st.session_state['color_picker_continuous_play'] = False; safe_rerun()
                
                if st.session_state.get('color_picker_continuous_play'):
                    st.write("ループ再生中...")
                    render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=True)
                
                picked = st.color_picker(":arrow_down: 音に対して想起した色をカラーピッカーから選んでください", "#808080", key=f"picker_{st.session_state['color_trial_index']}",width="content")
                
                if st.button("この色を保存して次へ"):
                    def hex_to_hsl(hexc):
                        hexc=hexc.lstrip('#'); r=int(hexc[0:2],16)/255.0; g=int(hexc[2:4],16)/255.0; b=int(hexc[4:6],16)/255.0
                        maxc,minc=max(r,g,b),min(r,g,b); l=(maxc+minc)/2
                        if maxc==minc: h=s=0
                        else:
                            d=maxc-minc; s=d/(2-maxc-minc) if l>0.5 else d/(maxc+minc)
                            if maxc==r: h=(g-b)/d+(6 if g<b else 0)
                            elif maxc==g: h=(b-r)/d+2
                            else: h=(r-g)/d+4
                            h=(h*60)%360
                        return {'H': round(h,2), 'S': round(s*100,2), 'L': round(l*100,2)}
                    picked_hsl = hex_to_hsl(picked)
                    row = {
                        'participant_id': st.session_state.get('participant_id'), # ★★★ participant_id を追加
                        'trial': st.session_state['color_trial_index']+1, 'audioName': audio_name,
                        'pickedHex': picked, 'pickedH': picked_hsl['H'], 'pickedS': picked_hsl['S'], 'pickedL': picked_hsl['L'],
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'loop_playback_used': st.session_state.get('color_picker_continuous_play', False)
                    }
                    append_color_csv_and_sheet(row)
                    st.session_state['color_results'].append(row)
                    st.session_state['color_trial_index'] += 1
                    st.session_state['color_picker_listening_complete'] = False
                    st.session_state['color_picker_continuous_play'] = False
                    safe_rerun()
            with col2:
                st.markdown("**色のプレビュー**")
                st.markdown(f'<div style="width:100%;height:250px;background-color:{picked};border:1px solid #d3d3d3;border-radius:5px;"></div>', unsafe_allow_html=True)


# post_questionnaire (自由選択の後)
elif st.session_state.get('page') == 'post_questionnaire':
    st.header("短いアンケート（自由な色選択について）")
    with st.form("post_qform"):
        q4 = st.radio("Q1.満足度: あなたが選んだ色は、音から感じたイメージとどの程度一致していましたか？", ("1: 全く一致しない", "2: かなり一致しない", "3: 少し一致しない", "4: どちらともいえない", "5: 少し一致する", "6: かなり一致する", "7: 完璧に一致する"))
        q5 = st.radio("Q2.操作感: 色の選択操作は、どの程度、簡単で直感的でしたか？", ("1: 非常に難しい", "2: かなり難しい", "3: 少し難しい", "4: どちらともいえない", "5: 少し簡単", "6: かなり簡単", "7: 非常に簡単"))
        q6 = st.radio("Q3.認知的負荷: 色を選ぶ作業は、精神的にどの程度大変でしたか？", ("1: 全く大変でない", "2: あまり大変でない", "3: 少し大変だった", "4: どちらともいえない", "5: やや大変だった", "6: かなり大変だった", "7: 非常に大変だった"))
        if st.form_submit_button("次へ"):
            st.session_state.setdefault('meta_answers', {})['q4'] = q4
            st.session_state.setdefault('meta_answers', {})['q5'] = q5
            st.session_state.setdefault('meta_answers', {})['q6'] = q6


            current_task_index = st.session_state['task_order'].index('color_picker')
            if current_task_index + 1 < len(st.session_state['task_order']):
                next_task = st.session_state['task_order'][current_task_index + 1]
                st.session_state['next_task_to_start'] = next_task
                go_to('transition_page')
            else:
                go_to('final_survey')

# タスク間の遷移ページ
elif st.session_state.get('page') == 'transition_page':
    st.header("次のタスクへ")

    next_task_name = "（不明）"
    next_task_description = "次の作業に進みます。"
    
    next_task_key = st.session_state.get('next_task_to_start')
    
    if next_task_key == 'stage':
        next_task_name = "段階的な色選択"
        next_task_description = """
        次に行う作業は「**段階的な色選択**」です。
        
        この作業では、音を聴きながら、提示される選択肢から想起した色に近いものを選び続けて色を決定します。
        """
    elif next_task_key == 'color_picker':
        next_task_name = "カラーピッカーでの色選択"
        next_task_description = """
        次に行う作業は「**カラーピッカーでの色選択**」です。
        
        この作業では、音を聴きながら、カラーピッカーを使って、想起した色を自由に1つ選びます。
        """

    st.markdown(f"一つ目のタスクは終了です。必要な方は休憩時間を5分取ることができます。")
    st.info(next_task_description)
    st.markdown("準備ができたら、下のボタンを押して次のタスクを開始してください。")

    if st.button(f"「{next_task_name}」を開始する"):
        if next_task_key:
            st.session_state['next_task_to_start'] = None # 使用後にクリア
            go_to(next_task_key)
        else:
            # フォールバック
            st.error("エラー：次のタスクが見つかりません。最初からやり直してください。")
            go_to('consent')


# final_survey
elif st.session_state.get('page') == 'final_survey':
    st.header("総合アンケート")
    with st.form("final"):
        q7 = st.radio("Q1.総合評価: 二つの色選択手法のうち、「音を聴いて想起した色を選ぶ」という作業に対して、どちらが色選択において総合的に適している手法だと感じましたか？", ("1: 段階的に色選択する手法", "2: カラーピッカーで直接選択する手法", "3: どちらともいえない"))
        q8 = st.text_input("Q2.総合評価の理由: Q1でそのように回答した理由を、具体的に教えてください")
        st.markdown("Q3.各手法の長所・短所")
        q9 = st.text_input("A:段階的に色選択する手法 長所", key="q9")
        q10 = st.text_input("短所", key="q10")
        q11 = st.text_input("B:カラーピッカーで色選択する手法 長所", key="q11")
        q12 = st.text_input("短所", key="q12")
        q13 = st.radio("Q7.年代", ("1: 10代", "2: 20代", "3: 30代", "4: 40代", "5: 50代", "6: 60代以上"))
        q14 = st.radio("Q8.性別", ("1: 男性", "2: 女性", "3: その他", "4: 選択しない"))
        st.markdown("Q9.デバイス環境について")
        q15 = st.text_input("・PC(デスクトップPCかノートPCか、OS、ブラウザ、画面サイズと解像度など)")
        q16 = st.text_input("・ヘッドホンまたはイヤホン(ヘッドホンかイヤホンか、有線か無線か、メーカー名、製品名など)")
        q17 = st.text_input("Q10.音楽経験: 楽器の演奏経験（楽器名、年数）、歌唱経験、作曲やDTMの経験、バンド活動、音楽の学習歴（専門教育を受けた、独学など）など、音楽に関する経験を可能な範囲で詳しく教えてください。")
        q18 = st.text_input("Q11.色彩・美術・デザイン経験: 絵画（油絵、水彩、イラストなど）、デザイン（グラフィック、Webなど）、写真、映像制作に関する学習歴や活動歴、色彩検定などの関連資格の有無など、色彩・美術・デザインに関する経験を可能な範囲で詳しく教えてください。")
        submitted = st.form_submit_button("送信して終了")
        
        if submitted:
            is_valid = all([
                q8.strip(), q9.strip(), q10.strip(), q11.strip(), q12.strip(),
                q15.strip(), q16.strip(), q17.strip(), q18.strip()
            ])
            
            if not is_valid:
                st.error("未入力の項目があります。すべての質問にご回答ください。")
            else:
                meta_answers = st.session_state.setdefault('meta_answers', {})
                meta_answers.update({
                    'q7': q7, 'q8': q8, 'q9': q9, 'q10': q10, 'q11': q11, 'q12': q12,
                    'q13': q13, 'q14': q14, 'q15': q15, 'q16': q16, 'q17': q17, 'q18': q18
                })

                row_data = {
                    'participant_id': st.session_state.get('participant_id'),
                    'task_order': ' -> '.join(st.session_state.get('task_order', [])), 
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    **{f'q{i}': meta_answers.get(f'q{i}', '') for i in range(1, 19)},
                    'n_color_picks': len(st.session_state.get('color_results', [])),
                    'n_hierarchical_trials': st.session_state['current_trial_index']
                }
                
                try:
                    append_meta_csv_and_sheet(row_data)
                    go_to('end')
                except Exception as e:
                    st.error(f"メタデータの保存に失敗しました: {e}")

# end
elif st.session_state.get('page') == 'end':
    st.header("終了ページ")
    st.markdown("ご協力ありがとうございました。")


st.markdown("---")
st.caption("注: 問題が発生した場合は実験を中断してください。")