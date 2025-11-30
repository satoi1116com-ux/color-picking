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
from typing import List, Dict, Tuple

# ---------- 設定 ----------
st.set_page_config(page_title="色選択手法比較実験", layout="wide")
# --- ローカルCSVへの書き込みは削除 ---
# RESULTS_CSV = 'results.csv'
# COLOR_RESULTS_CSV = 'color_results.csv'
UPLOAD_DIR = Path('static')
UPLOAD_DIR.mkdir(exist_ok=True)
# META_RESULTS_CSV = 'meta_results.csv'



# ---------- ユーティリティ ----------
def safe_rerun():
    """Streamlit のバージョン差に対処してアプリを再実行するユーティリティ（フォールバックあり）。"""
    # 簡略化: st.rerun() が現在の標準
    st.rerun()


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



@st.cache_data(show_spinner=False)
def get_audio_base64(audio_bytes: bytes) -> str:
    """音声バイナリをBase64文字列に変換してキャッシュする"""
    return base64.b64encode(audio_bytes).decode('ascii')

# 2. プレーヤー表示関数
def render_audio_player(filename: str, autoplay=False, loop=False):
    """
    ファイル名を受け取り、staticフォルダのURLを参照させる
    """
    # Streamlit Cloud上でのファイルの住所
    # "app/static/ファイル名" でアクセスできます
    audio_url = f"app/static/{filename}"
    
    # Pythonでの重い読み込み処理は一切なし！
    
    autoplay_attr = 'autoplay' if autoplay else ''
    loop_attr = 'loop' if loop else ''
    
    # HTMLタグを作る
    html = f"""
    <audio controls {autoplay_attr} {loop_attr} style="width:100%">
      <source src="{audio_url}">
    </audio>
    """
    components.html(html, height=90)

def safe_filename(name: str) -> str:
    name = os.path.basename(name)
    return "".join(c for c in name if c.isalnum() or c in "._-")

def create_non_repeating_trials(stimuli_indices: List[int], repeats: int) -> List[int]:
    """
    指定されたリストを `repeats` 回繰り返し、
    連続する要素が決してないシャッフル済みリストを生成する。
    """
    # 1. フルリストを作成 (例: [0,1,2...7, 0,1,2...7])
    trial_list = stimuli_indices * repeats
    
    # 2. 安全装置（万が一、修正が無限ループするのを防ぐ）
    max_attempts = 10
    
    for attempt in range(max_attempts):
        random.shuffle(trial_list) # まず全体をシャッフル
        
        has_repeats = False
        for i in range(len(trial_list) - 1):
            if trial_list[i] == trial_list[i+1]:
                has_repeats = True
                
                # 連続する重複を発見
                # i+1 の要素を、i とも i+1 とも異なる要素と交換する
                
                # まず前方にスワップ対象を探す
                swap_idx = -1
                for j in range(i + 2, len(trial_list)):
                    if trial_list[j] != trial_list[i]:
                        swap_idx = j
                        break
                
                # 前方で見つからなければ後方に探す
                if swap_idx == -1:
                    for j in range(i - 1, -1, -1):
                        if trial_list[j] != trial_list[i]:
                            swap_idx = j
                            break
                
                # スワップを実行
                if swap_idx != -1:
                    # i+1 (重複した後者) をスワップ
                    temp = trial_list[i+1]
                    trial_list[i+1] = trial_list[swap_idx]
                    trial_list[swap_idx] = temp
                else:
                    # スワップ対象が見つからない（非常に稀）
                    # ループを抜けて再シャッフル
                    break 
        
        # 重複がなければループを終了
        if not has_repeats:
            return trial_list

    # 10回試行しても失敗した場合（通常はあり得ない）
    st.warning("連続重複の排除に失敗しました。通常のシャッフルを使用します。")
    random.shuffle(trial_list) # 最終的なフォールバック
    return trial_list

@st.cache_resource
def get_gspread_client():
    try:
        creds = st.secrets["gcp_service_account"]
        key = st.secrets["google_sheet_key"]
        gc = gspread.service_account_from_dict(creds)
        sh = gc.open_by_key(key)
        return sh
    except Exception as e:
        st.error(f"Google Sheets への接続に失敗しました: {e}")
        return None
    
@st.cache_resource
def get_worksheet(worksheet_name: str):
    """
    ワークシートオブジェクトを取得し、キャッシュする
    """
    sh = get_gspread_client()
    if sh is None:
        st.error("GSheet接続がないため、ワークシートを取得できません。")
        return None
    try:
        wks = sh.worksheet(worksheet_name)
        return wks
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"ワークシート '{worksheet_name}' が見つかりません。")
        return None
    except Exception as e:
        st.error(f"ワークシート '{worksheet_name}' の取得に失敗: {e}")
        return None

def append_to_gsheet(worksheet_name: str, header: List[str], row_data: Dict):
    """
    指定されたワークシートにヘッダーを確認し、データを1行追記する
    """
    wks = get_worksheet(worksheet_name) 
    if wks is None:
        st.error(f"'{worksheet_name}' へのログ保存に失敗（ワークシート取得不可）。")
        return
    
    try:
        values_to_append = [row_data.get(key, "") for key in header]
        
        # (変更) この append_row だけがネットワーク通信を行う
        wks.append_row(values_to_append, value_input_option='USER_ENTERED')
        
    except Exception as e:
        # 同時書き込み競合などでエラーが起きても実験が停止しないようにする
        st.error(f"'{worksheet_name}' へのログ書き込みに失敗: {e}")


# (ここから追加) ----------------
@st.cache_data
def load_audio_file(file_path: Path) -> Tuple[bytes, str]:
    """
    音声ファイルをディスクから読み込み、キャッシュする。
    戻り値: (data, mime_type)
    """
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
        
        ext = file_path.suffix.lower().lstrip('.')
        mime = 'audio/wav'
        if ext in ['mp3']: mime = 'audio/mpeg'
        elif ext in ['ogg']: mime = 'audio/ogg'
        elif ext in ['m4a','mp4','aac']: mime = 'audio/mp4'
        return (data, mime)
    except Exception as e:
        st.error(f"Failed to load audio {file_path.name}: {e}")
        return (None, None)

@st.cache_data
def get_audio_file_list() -> List[Dict]:
    """
    uploads フォルダをスキャンし、音声ファイルの（軽い）情報リストを返す。
    データ本体は読み込まない。
    """
    try:
        files_on_disk = sorted([
            p for p in UPLOAD_DIR.iterdir() 
            if p.is_file() and not p.name.startswith('_check_sound.')
        ])
    except Exception:
        files_on_disk = []

    file_info_list = []
    for p in files_on_disk:
        # ここではファイルは読み込まない！ Pathオブジェクトだけ保存
        file_info_list.append({
            'id': f"disk_{p.stem}", 
            'name': p.name, 
            'safe_name': p.name, 
            'path': p # Pathオブジェクト
        })
    return file_info_list
# (ここまで追加) ----------------


# ---------------- Google Sheets 保存専用関数 ----------------
# ローカルCSVへの書き込みを削除し、GSheetのみに書き込む

def append_result_csv_and_sheet(row: dict):
    """段階的選択結果を Google Sheets に append する。"""
    header = ['participant_id','trial','audioName','path','finalHex','finalH','finalS','finalL','stepRTs_ms','totalRT_ms','timestamp','practice','loop_playback_used','reset_count']
    # ローカルCSV保存を削除
    
    # Google Sheets 保存（失敗しても処理続行）
    try:
        append_to_gsheet("results", header, row)
    except Exception as e:
        st.warning(f"Google Sheets 書込失敗 (results): {e}")

def append_color_csv_and_sheet(row: dict):
    """色選択結果を Google Sheets に append する。"""
    header = ['participant_id','trial','audioName','pickedHex','pickedH','pickedS','pickedL','timestamp','loop_playback_used', 'totalRT_ms']
    # ローカルCSV保存を削除

    try:
        append_to_gsheet("color_results", header, row)
    except Exception as e:
        st.warning(f"Google Sheets 書込失敗 (color_results): {e}")

def append_meta_csv_and_sheet(row: dict):
    """メタ情報を Google Sheets に append する。"""
    header = ['participant_id','task_order','timestamp'] + [f"q{i}" for i in range(1,20)] + ['n_color_picks','n_hierarchical_trials']
    # ローカルCSV保存を削除

    try:
        append_to_gsheet("meta_results", header, row)
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
if 'color_picker_start_time' not in st.session_state:
    st.session_state['color_picker_start_time'] = None
# ---------- uploads/ からの自動読み込み（参加者用） ----------
# (変更) キャッシュを利用し、session_state に重いデータを入れない
if not st.session_state.get('audio_files'):
    # キャッシュされた関数を呼び出す
    st.session_state['audio_files'] = get_audio_file_list()

    if not st.session_state.get('trials_order'):
        n = len(st.session_state['audio_files'])
        if n == 0:
            st.session_state['trials_order'] = [None]
            st.session_state['color_trials_order'] = [None]
        else:
            base_indices = list(range(n))
   
            if n != 8:
                st.warning(f"警告: 8個の音刺激が期待されていましたが、{n}個見つかりました。{n}個の刺激を2回ずつ ({n*2} 試行) 実行します。")

            trials_order_16 = create_non_repeating_trials(base_indices, repeats=2)
            st.session_state['trials_order'] = trials_order_16
            
            color_trials_order_16 = create_non_repeating_trials(base_indices, repeats=2)
            st.session_state['color_trials_order'] = color_trials_order_16

# ---------- UI: 管理者/参加者ページ選択（簡易） ----------
st.title("色選択手法比較実験")
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
                # (変更) キャッシュから読み込む
                check_data, check_mime = load_audio_file(current_check_sound_path)
                if check_data:
                    render_audio_player(check_data, mime=check_mime, autoplay=False, loop=False, height=90)
                else:
                    st.error("チェックサウンドの読み込みに失敗しました。")
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
        
        # (変更) キャッシュをクリアし、リストを再読み込み
        get_audio_file_list.clear() 
        try:
            st.session_state['audio_files'] = get_audio_file_list()
            n = len(st.session_state['audio_files'])
        except Exception as e:
            st.error(f"uploads フォルダ読み込み失敗: {e}")
            n = 0

        st.session_state['trials_order'] = list(range(n)) if n > 0 else [None]
        # (注) 元のコードに従い、アップロード時はシャッフルしない
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
        # (変更) キャッシュクリアを追加
        get_audio_file_list.clear()
        st.session_state['audio_files'] = get_audio_file_list()
        
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
                    # audio_bytes, audio_mime = load_audio_file(a.get('path')) ←削除
                    render_audio_player(filename=a.get('name'), autoplay=True, loop=False, height=100)
            with cols[2]:
                # (変更) キャッシュから読み込んでダウンロード
                audio_bytes_dl, audio_mime_dl = load_audio_file(a.get('path'))
                st.download_button(f"Download", data=audio_bytes_dl, file_name=a.get('name'), mime=audio_mime_dl, key=f"dl_{a.get('safe_name')}_{idx}")
            with cols[3]:
                if st.button("削除", key=f"del_{a.get('safe_name')}_{idx}"):
                    filepath = a.get('path') # Pathオブジェクトを直接取得
                    if filepath.exists(): filepath.unlink()
                    
                    # (変更) キャッシュをクリアし、リストを再読み込み
                    get_audio_file_list.clear()
                    st.session_state['audio_files'] = get_audio_file_list()
                    
                    st.success(f"{a.get('safe_name')} を削除しました。反映するには「手動リセット」を押してください。")
                    safe_rerun()
    st.markdown("---")
    st.header("ログ / 結果の確認")
    st.info("データは Google Sheets に直接保存されます。管理者は Google Sheets を確認してください。")
    # (変更) ローカルCSVのダウンロードボタンを削除
    # if os.path.exists(RESULTS_CSV): ...
    # if os.path.exists(COLOR_RESULTS_CSV): ...
    # if os.path.exists(META_RESULTS_CSV): ...

# 参加者ページフロー
elif st.session_state.get('page') == 'consent':
    st.header("実験説明と参加への同意")
    st.markdown("""
    ### 1.	実験の目的と意義
    本実験では、人々が音や音楽を聴いた際に色を想起する知覚現象を扱う実験において、2種類の色選択手法を比較します。こちらの現象についての実験を行い、実験データの分析を行うことで、今後の同分野の研究で、より信頼性の高いデータを収集するための最適な実験環境を提案することを目的としています。
    ### 2.	実験の概要
    本実験は、オンラインにて実施します。参加者の皆様には、静かな環境でPCとヘッドホンまたはイヤホンをご用意いただき、画面の指示に従って作業を進めていただきます。提示される音刺激に対して下記の二つの手法を用いて想起した色を選択する作業を行っていただきます。
    
    ・カラーピッカー 
    
    
    ・段階的な色選択 
    
    各手法で色を選択した直後に、色選択に関するアンケートに回答してください。さらに、全手法での色選択及びアンケート回答後には、全体のアンケートに回答してください。二つの手法の順序は参加者ごとに異なります。作業時間は休憩時間5分を含めて計45分を想定しています。
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
    st.markdown("---")        
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

    st.subheader("1. 音の確認")
    st.markdown("---")
    check_sound_data, check_sound_mime, check_sound_name = None, None, None
    check_sound_files = list(UPLOAD_DIR.glob('_check_sound.*'))
    if check_sound_files:
        check_sound_path = check_sound_files[0]
        try:
            # (変更) キャッシュから読み込む
            check_sound_data, check_sound_mime = load_audio_file(check_sound_path)
            check_sound_name = check_sound_path.name
        except Exception as e:
            st.error(f"チェックサウンドの読み込みに失敗: {e}")
            check_sound_data = None
    
    # フォールバック: _check_sound がない場合、audio_files[0] を使う
    if check_sound_data is None and st.session_state.get('audio_files'):
        st.info("管理者設定のチェックサウンドが見つかりません。実験用の最初の音源を再生します。")
        try:
            first = st.session_state['audio_files'][0]
            # (変更) キャッシュから読み込む
            check_sound_data, check_sound_mime = load_audio_file(first['path'])
            check_sound_name = first.get('name')
            st.write(f"再生ファイル: **{check_sound_name}**")
        except Exception:
            st.error("実験用音源の読み込みにも失敗しました。")

    # 再生UIの描画
    if check_sound_data:
        # 通常の1回再生
        st.info("まず、下の再生ボタンを押して音を一度最後までお聞きください。")
        render_audio_player(filename=check_sound_name, autoplay=False, loop=False)

        st.markdown("---")
        # ループ再生コントロール (本番タスクと同様)
        st.info("次に下のボタンを押して問題なくループ再生ができているか確認してください。")
        if not st.session_state.get('audio_check_continuous_play'):
            if st.button("ループ再生", key="check_start_continuous"):
                st.session_state['audio_check_continuous_play'] = True; safe_rerun()
        else:
            if st.button("再生を停止", key="check_stop_continuous"):
                st.session_state['audio_check_continuous_play'] = False; safe_rerun()
        
        if st.session_state.get('audio_check_continuous_play'):
            st.write("ループ再生中...")
            render_audio_player(filename=check_sound_name, autoplay=True, loop=True)
    else:
        st.error("再生できる音量チェック用の音声ファイルがありません。管理者に連絡してください。")

    st.markdown("---")
    st.header("2. 操作テスト")
    st.info("2種類の実験操作をテストしてください。**ここで選んだ色は保存されません。**")
    st.markdown("---")
    col1a,col1b = st.columns(2)


    with col1a:
        st.markdown("#### テスト1: 段階的な選択")
        st.write("""
        これは「**段階的な色選択**」タスクのテストです。

        1.  右側に表示される**色の選択肢**から、**想起した色に最も近い色**を1つ選びます。
        2.  色の下にある**ボタン**を押すと、次の選択肢が表示されます。
        3.  この操作を**合計8回**繰り返すと、1つの色が決定されます。
        
        *本番の実験では、この操作を音を聴きながら行っていただきます。*
        """)
    
    with col1b:

        st.write("左の指示に従って、慣れるまで操作を繰り返してみてください。")

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
                # st.caption(f"最終色: {final_hex}")
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
                        if st.button(f"この色を選ぶ", key=f"test_stage_s{current_step_number}_o{i}"):
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
        st.markdown("#### テスト2: カラーピッカーでの色選択")
        st.write("""
        これは「**カラーピッカーでの色選択**」タスクのテストです。
        
        1.  右側の**色の四角**をクリックして、カラーピッカーを開きます。
        2.  色を自由に選んでみてください。
        
        **【注意】**
        本番の実験でも同様ですが、色を選ぶ際は、ピッカー下部の数値欄（HEX, RGBなど）は使わず、**上の2つの色空間**(大きい四角と横長のスライダー)のみで色を選んでください。
        
        3.  色を選んだ後、**ピッカーを閉じるには、ピッカーの外側**（この画面の白い部分など）をクリックします。
        4.  ピッカーを閉じると、選んだ色が下のプレビューに反映されていることを確認してください。
        
        *本番の実験では、音を聴きながらこの操作で色を1つ決定し、「この色を保存して次へ」ボタンを押していただきます。*
        """)

    with col2b:

        st.write("左の指示に従って、慣れるまで操作を繰り返してみてください。")

        if 'test_color_picker_val' not in st.session_state:
            st.session_state['test_color_picker_val'] = '#808080'

        def update_test_color():
            st.session_state['test_color_picker_val'] = st.session_state['test_color_picker_widget']

        test_color = st.color_picker(
            ":blue-background[:arrow_down: テスト用の色を選択]", 
            key='test_color_picker_widget', 
            value=st.session_state['test_color_picker_val'],
            on_change=update_test_color,
            width="stretch"
        )

        st.markdown(f'<div style="width:100%;height:80px;background-color:{st.session_state["test_color_picker_val"]};border:1px solid #d3d3d3;border-radius:5px;"></div>', unsafe_allow_html=True)
        # st.caption(f"HEX: `{st.session_state['test_color_picker_val']}`")
    st.markdown("\n")
    st.markdown("---")
    st.info("""
    次のページから本番の実験が始まります。
    
    実験は2つの異なる色選択タスク（「段階的な色選択」と「カラーピッカーでの色選択」）で構成されています。
    2つのタスクが提示される順序はランダムです。
    
    大まかな実験の流れは以下の通りです。
    
    1.  **タスク1**（どちらかの手法）
    2.  タスク1に関する**個別アンケート**
    3.  **休憩**（5分）
    4.  **タスク2**（もう一方の手法）
    5.  タスク2に関する**個別アンケート**
    6.  **総合アンケート**
    
    準備ができたら、下のチェックボックスにチェックを入れて実験を開始してください
    """)
    if st.checkbox("再生・操作確認済み（音・操作ともに問題なし）", key="audio_and_op_checked"):
        if st.button("次へ（実験開始）"):
            first_task = st.session_state['task_order'][0]
            go_to(first_task)



# stage (階層的色選択)
elif st.session_state.get('page') == 'stage':
    st.header("段階的な色選択")
    # st.markdown("このページでは、提示される選択肢から想起した色に近いものを選び続けて色を決定します。全ての音について選び終わるとアンケートへ進みます。")

    if st.session_state['current_trial_index'] >= len(st.session_state['trials_order']):
        st.info("すべての試行が終了しました。短いアンケートにお答えください。")
        time.sleep(0.5)
        go_to('questionnaire') # stage の後のアンケートへ
        
    else:
        idx = st.session_state['trials_order'][st.session_state['current_trial_index']]
        audio_name = '(なし)' if idx is None else st.session_state['audio_files'][idx]['name']
        st.write(f"**トライアル {st.session_state['current_trial_index']+1} / {len(st.session_state['trials_order'])}**")
        


        if not st.session_state.get('listening_complete'):
            st.markdown("---")
            st.subheader(f"トライアル {st.session_state['current_trial_index']+1} の再生")
            st.info("まず、今回の音刺激を一度最後までお聞きください。\n\n再生が終了したら、下のボタンを押して色選択に進んでください。")
            render_audio_player(filename=audio_name, autoplay=True, loop=False)
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
                    render_audio_player(filename=audio_name, autoplay=True, loop=True)
            
            # st.markdown("---")
            # st.markdown("### 色選択（8段階）")
            current_step_number = len(st.session_state.get('current_path', [])) + 1
            st.write(f"**段階 {current_step_number} / 8**")


            if current_step_number == 1:
                st.info("音に対して想起した色に近い色を6つの色から1つ選んでください。ボタンを押すと次の段階に進みます。")
                options = [{'digit': d, 'hex': hsl_to_hex(path_to_hsl_separated(st.session_state['current_path'] + [d]))} for d in range(6)]
                cols = st.columns(6)
            else:
                st.info("音に対して想起した色に近い色を3つの色から1つ選んでください。ボタンを押すと次の段階に進みます。")
                options = [{'digit': d, 'hex': hsl_to_hex(path_to_hsl_separated(st.session_state['current_path'] + [d]))} for d in [0,1,2]]
                cols = st.columns(3)
            
            if st.session_state['step_start_time'] is None:
                st.session_state['step_start_time'] = time.time()
            for i, opt in enumerate(options):
                with cols[i]:
                    st.markdown(f'<div style="height:140px;border-radius:10px;background:{opt["hex"]};display:flex;align-items:center;justify-content:center;font-weight:bold;color:#000;margin-bottom:8px"></div>', unsafe_allow_html=True)
                    if st.button(f"この色を選ぶ ", key=f"sel_{st.session_state['current_trial_index']}_{current_step_number}_{i}"):
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
                                'path': ''.join(map(lambda d: str(d + 1), st.session_state['current_path'])), 'finalHex': hsl_to_hex(final_hsl),
                                'finalH': round(final_hsl['H'],2), 'finalS': final_hsl['S'], 'finalL': final_hsl['L'],
                                'stepRTs_ms': '|'.join(map(str,st.session_state.get('step_rts',[]))), 'totalRT_ms': sum(st.session_state.get('step_rts', [])),
                                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'), 'practice': False,
                                'loop_playback_used': st.session_state.get('continuous_play_mode', False),
                                'reset_count': reset_count_for_this_trial
                            }
                            # (変更) GSheet保存関数を呼び出す
                            append_result_csv_and_sheet(trial_record)
                            st.session_state['current_trial_index'] += 1
                            st.session_state['current_path'] = []
                            st.session_state['step_rts'] = []
                            st.session_state['listening_complete'] = False
                            st.session_state['continuous_play_mode'] = False
                            time.sleep(0.3)
                        safe_rerun()
            
            st.markdown("\n")
            st.markdown("\n")
            if current_step_number > 1:
                if st.button("このトライアルの選択をリセット", key=f"reset_stage_trial_{st.session_state['current_trial_index']}"):
                    current_trial_idx = st.session_state['current_trial_index']
                    current_count = st.session_state.get('reset_counts', {}).get(current_trial_idx, 0)
                    st.session_state['reset_counts'][current_trial_idx] = current_count + 1
                    st.session_state['current_path'] = []
                    st.session_state['step_rts'] = []
                    st.session_state['step_start_time'] = None
                    st.warning("このトライアルの選択をリセットしました。段階1からやり直してください。")
                    time.sleep(1) 
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
    # st.markdown("このページでは、音に対して想起した色をカラーピッカーを用いて選んでいただきます。全ての音について選び終わるとアンケートへ進みます。")

    if st.session_state['color_trial_index'] >= len(st.session_state['color_trials_order']):
        st.info("全ての音刺激について色の選択が終わりました。短いアンケートにお答えください。")
        time.sleep(0.5)
        go_to('post_questionnaire') 
    else:
        cidx = st.session_state['color_trials_order'][st.session_state['color_trial_index']]
        audio_name = '(なし)' if cidx is None else st.session_state['audio_files'][cidx]['name']
        st.write(f"**トライアル {st.session_state['color_trial_index']+1} / {len(st.session_state['color_trials_order'])}**")
        


        if not st.session_state.get('color_picker_listening_complete'):
            st.markdown("---")
            st.subheader(f"トライアル {st.session_state['color_trial_index']+1} の再生")
            st.info("まず、今回の音刺激を一度最後までお聞きください。\n\n再生が終了したら、下のボタンを押して色選択に進んでください。")
            render_audio_player(filename=audio_name, autoplay=True, loop=False)
            if st.button("再生が終了したので、色選択に進む", key="cp_finish_listening"):
                st.session_state['color_picker_listening_complete'] = True
                st.session_state['color_picker_start_time'] = None
                safe_rerun()
        else:
            if st.session_state['color_picker_start_time'] is None:
                st.session_state['color_picker_start_time'] = time.time()
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
                    render_audio_player(filename=audio_name, autoplay=True, loop=True)

                
                picked = st.color_picker(":blue-background[:arrow_down_small: 音に対して想起した色をカラーピッカーから選んでください]", "#808080", key=f"picker_{st.session_state['color_trial_index']}",width="content")
                st.markdown("\n")
                st.markdown("\n")
                st.markdown("\n")
                st.markdown("\n")
                if st.button("この色を保存して次へ"):
                    rt_ms = int((time.time() - st.session_state['color_picker_start_time'])*1000)
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
                        'loop_playback_used': st.session_state.get('color_picker_continuous_play', False),
                        'totalRT_ms': rt_ms
                    }
                    # (変更) GSheet保存関数を呼び出す
                    append_color_csv_and_sheet(row)
                    st.session_state['color_results'].append(row)
                    st.session_state['color_trial_index'] += 1
                    st.session_state['color_picker_listening_complete'] = False
                    st.session_state['color_picker_continuous_play'] = False
                    st.session_state['color_picker_start_time'] = None
                    safe_rerun()
            with col2:
                st.markdown("**色のプレビュー**")
                st.markdown(f'<div style="width:100%;height:250px;background-color:{picked};border:1px solid #d3d3d3;border-radius:5px;"></div>', unsafe_allow_html=True)


# post_questionnaire (自由選択の後)
elif st.session_state.get('page') == 'post_questionnaire':
    st.header("個別アンケート（カラーピッカーでの色選択について）")
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
        """
    elif next_task_key == 'color_picker':
        next_task_name = "カラーピッカーでの色選択"
        next_task_description = """
        次に行う作業は「**カラーピッカーでの色選択**」です。
        """

    st.markdown(f"一つ目のタスクは終了です。**必要ならば休憩時間を5分取ってください。**")
    st.info(f"{next_task_description}  \n準備ができたら、下のボタンを押して次のタスクを開始してください。")

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
    st.markdown("最後に、実験全体に関するご意見と、あなたご自身についてお伺いします。")
    
    with st.form("final"):
        task_names = {
            'stage': "段階的な色選択",
            'color_picker': "カラーピッカーでの色選択"
        }
        
        # 実施順序を取得
        task_order = st.session_state.get('task_order', ['stage', 'color_picker']) # (フォールバック)
        
        # stage (q9, q10) が最初か後か
        stage_order_text = "(最初に行ったタスク)" if task_order[0] == 'stage' else "(後に行ったタスク)"
        # color_picker (q11, q12) が最初か後か
        cp_order_text = "(最初に行ったタスク)" if task_order[0] == 'color_picker' else "(後に行ったタスク)"
        q7_option_1 = f"1: 段階的に色選択する手法 {stage_order_text}"
        q7_option_2 = f"2: カラーピッカーで直接選択する手法 {cp_order_text}"
        q7_option_3 = "3: どちらともいえない"
        q7 = st.radio("Q1.総合評価: 二つの色選択手法のうち、「音を聴いて想起した色を選ぶ」という作業に対して、どちらが色選択において総合的に適している手法だと感じましたか？", (q7_option_1, q7_option_2, q7_option_3), key="q7")
        q8 = st.text_input("Q2.総合評価の理由: Q1でそのように回答した理由を、具体的に教えてください")
        st.markdown("Q3.各手法の長所・短所")
        st.markdown(f"**A:段階的に色選択する手法** {stage_order_text}")
        q9 = st.text_input("長所", key="q9")
        q10 = st.text_input("短所", key="q10")
        st.markdown(f"**B:カラーピッカーで色選択する手法** {cp_order_text}")
        q11 = st.text_input("長所", key="q11")
        q12 = st.text_input("短所", key="q12")
        q13 = st.radio("Q7.年代", ("1: 10代", "2: 20代", "3: 30代", "4: 40代", "5: 50代", "6: 60代以上"))
        q14 = st.radio("Q8.性別", ("1: 男性", "2: 女性", "3: その他", "4: 選択しない"))
        st.markdown("Q9.デバイス環境について")
        q15 = st.text_input("・PC(デスクトップPCかノートPCか、OS、ブラウザ、画面サイズと解像度など)")
        q16 = st.text_input("・ヘッドホンまたはイヤホン(ヘッドホンかイヤホンか、有線か無線か、メーカー名、製品名など)")
        q17 = st.text_input("Q10.音楽経験 : 楽器の演奏経験（楽器名、年数）、歌唱経験、作曲やDTMの経験、バンド活動、音楽の学習歴（専門教育を受けた、独学など）など、音楽に関する経験を可能な範囲で詳しく教えてください。")
        q18 = st.text_input("Q11.色彩・美術・デザイン経験 : 絵画（油絵、水彩、イラストなど）、デザイン（グラフィック、Webなど）、写真、映像制作に関する学習歴や活動歴、色彩検定などの関連資格の有無、共感覚傾向の自己認識など、色彩・美術・デザインに関する経験を可能な範囲で詳しく教えてください。")
        
        # --- 追加ここから ---
        q19 = st.text_input("Q12.色聴共感覚の傾向 : 色聴共感覚（音を聞いたときに色や形などを感じる知覚現象）について、ご自身にそのような傾向があると感じるか、可能な範囲で詳しく教えてください。")
        # --- 追加ここまで ---

        submitted = st.form_submit_button("送信して終了")
        
        if submitted:
            # バリデーションに q19 を追加
            is_valid = all([
                q8.strip(), q9.strip(), q10.strip(), q11.strip(), q12.strip(),
                q15.strip(), q16.strip(), q17.strip(), q18.strip(), q19.strip()
            ])
            
            if not is_valid:
                st.error("未入力の項目があります。すべての質問にご回答ください。")
            else:
                meta_answers = st.session_state.setdefault('meta_answers', {})
                meta_answers.update({
                    'q7': q7, 'q8': q8, 'q9': q9, 'q10': q10, 'q11': q11, 'q12': q12,
                    'q13': q13, 'q14': q14, 'q15': q15, 'q16': q16, 'q17': q17, 'q18': q18, 
                    'q19': q19  # 追加
                })

                row_data = {
                    'participant_id': st.session_state.get('participant_id'),
                    'task_order': ' -> '.join(st.session_state.get('task_order', [])), 
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    # rangeを (1, 20) に変更して q19 まで含める
                    **{f'q{i}': meta_answers.get(f'q{i}', '') for i in range(1, 20)},
                    'n_color_picks': len(st.session_state.get('color_results', [])),
                    'n_hierarchical_trials': st.session_state['current_trial_index']
                }
                
                try:
                    # (変更) GSheet保存関数を呼び出す
                    append_meta_csv_and_sheet(row_data)
                    go_to('end')
                except Exception as e:
                    st.error(f"メタデータの保存に失敗しました: {e}")

# end
elif st.session_state.get('page') == 'end':
    st.header("終了ページ")
    st.markdown("ご協力ありがとうございました。")
    
    st.markdown(f"報酬支払いのためのパスコードは以下の通りです") 
    st.info(st.secrets["passcord"])
st.markdown("---")
st.warning("注: 実験途中でのサイトの更新やボタンの連打は行わないでください。\n問題が発生した場合は実験を中断してください。")