import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# File lokal tempat link Google Sheet disimpan supaya tidak perlu paste ulang
# tiap buka app. Isinya cuma URL/nama-tab (bukan kredensial), tapi tetap
# di-.gitignore-kan supaya tidak ikut ter-commit.
CONFIG_PATH = Path(__file__).parent / ".becare_dashboard_config.json"


def load_saved_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_config(data: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

# =========================================================================
# KONFIGURASI HALAMAN & KONSTANTA
# =========================================================================
st.set_page_config(
    page_title="BeCare SPI & Highlight Issue",
    page_icon="🟢",
    layout="wide",
)

STATUS_COLOR = {"Low": "#0ca30c", "Medium": "#fab219", "High": "#d03b3b"}
STATUS_ICON = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}
SEVERITY_ORDER = ["High", "Medium", "Low"]  # urutan tampil (paling berat di atas)
BRAND_GREEN = "#0ca30c"
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7", "#e34948"]

HIGHLIGHT_COLUMNS = [
    "No", "Modul", "Tanggal Pelaporan", "Deskripsi",
    "Solusi / Update", "Risiko Isu", "Due Date", "Status", "Link",
]

# List ClickUp default: space "Monitoring All System" -> "Monitoring Issue Operational".
CLICKUP_DEFAULT_LIST_ID = "901820651612"

# Kandidat nama kolom dari sheet "Form Responses 1" milik BeCare — dipakai
# untuk auto-deteksi kolom supaya tetap jalan walau header sheet live sedikit berubah.
COLUMN_CANDIDATES = {
    "timestamp": ["timestamp"],
    "modul": ["nama aplikasi / modul", "nama aplikasi/modul", "modul", "aplikasi"],
    "severity": ["resiko isu", "risiko isu", "risk", "severity"],
    "status": ["closed permanent", "status"],
    "due_date": ["tanggal selesai development", "due date", "tanggal target"],
    "week": ["week of timestamp", "week"],
    "year": ["year", "tahun"],
}
DESC_CANDIDATES = [
    "kronologi isu becare", "kronologi isu web lms (sintesis)",
    "kronologi isu", "jawaban", "pertanyaan",
]
SOLUSI_CANDIDATES = ["cara penyelesaian", "solusi"]

DEFAULT_SEVERITY_WEIGHT = {"Low": 1, "Medium": 2, "High": 3}
DEFAULT_STATUS_WEIGHT = {
    "Open": 2,
    "On Progress": 1,
    "Close": 0,
    "Closed": 0,
    "Closed Permanent": 0,
    "Workaround": 1,
    "Closed Temporary (workaround)": 1,
}

st.markdown(
    """
    <style>
    /* Pastikan latar selalu cerah walau browser/OS pakai dark mode */
    .stApp, section[data-testid="stSidebar"] > div { background-color: #ffffff; }
    section[data-testid="stSidebar"] { background-color: #f5faf5; }

    /* Banner header ala BeCare */
    .becare-hero{
        background: linear-gradient(135deg, #e8f7e8 0%, #ffffff 75%);
        border: 1px solid #0ca30c2e; border-radius: 16px;
        padding: 1.3rem 1.7rem; margin-bottom: 1.1rem;
        box-shadow: 0 2px 12px rgba(12,163,12,0.09);
    }
    .becare-hero h1{ margin:0; font-size:1.65rem; color:#0a5c0a; line-height:1.3; }
    .becare-hero p{ margin:.35rem 0 0; color:#555; font-size:.92rem; }

    /* Kartu metric (Low/Medium/High/Total dst) — dengan efek hover interaktif */
    div[data-testid="stMetric"]{
        background:#ffffff; border:1px solid #e6e6df; border-radius:12px;
        padding:.85rem 1rem .55rem; box-shadow:0 1px 5px rgba(0,0,0,.045);
        transition: transform .15s ease, box-shadow .15s ease;
    }
    div[data-testid="stMetric"]:hover{
        transform: translateY(-3px);
        box-shadow: 0 6px 16px rgba(12,163,12,.14);
        border-color:#0ca30c66;
    }

    /* Tab ala dashboard: lebih besar, aksen hijau di tab aktif */
    button[data-baseweb="tab"]{ font-weight:600; font-size:.95rem; }
    div[data-baseweb="tab-highlight"]{ background-color:#0ca30c !important; height:3px; }
    button[aria-selected="true"] p{ color:#0a5c0a !important; }

    /* Aksen hijau di setiap judul section */
    h2, h3{ border-left:4px solid #0ca30c; padding-left:.65rem; }

    /* Badge severity kecil (dipakai untuk tabel/keterangan) */
    .badge{padding:2px 10px;border-radius:999px;font-weight:600;font-size:0.8rem;
           display:inline-block;white-space:nowrap;}
    .badge-low{background:#0ca30c1a;color:#0ca30c;border:1px solid #0ca30c55;}
    .badge-medium{background:#fab2191a;color:#8a6100;border:1px solid #fab21966;}
    .badge-high{background:#d03b3b1a;color:#d03b3b;border:1px solid #d03b3b55;}
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================================
# HELPER — AMBIL DATA GOOGLE SHEET (dipakai tab Rekap Laporan)
# =========================================================================
def extract_sheet_id(url_or_id: str) -> str:
    """Terima URL lengkap Google Sheet ATAU langsung ID-nya."""
    url_or_id = url_or_id.strip()
    m = re.search(r"/d/([a-zA-Z0-9-_]+)", url_or_id)
    return m.group(1) if m else url_or_id


def gsheet_csv_url(sheet_id: str, sheet_name: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={quote(sheet_name)}"
    )


@st.cache_data(ttl=300, show_spinner="Mengambil data terbaru dari Google Sheet...")
def load_from_gsheet(sheet_id: str, sheet_name: str) -> pd.DataFrame:
    url = gsheet_csv_url(sheet_id, sheet_name)
    return pd.read_csv(url)


def has_service_account() -> bool:
    """True kalau kredensial Google Sheets API (service account) sudah dipasang di Secrets."""
    try:
        return "gcp_service_account" in st.secrets
    except Exception:  # noqa: BLE001
        return False


def get_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    return gspread.authorize(creds)


@st.cache_data(ttl=300, show_spinner="Mengambil data terbaru dari Google Sheet (API)...")
def load_via_api(sheet_id: str, sheet_name: str) -> pd.DataFrame:
    gc = get_gspread_client()
    ws = gc.open_by_key(sheet_id).worksheet(sheet_name)
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame()
    header, rows = values[0], values[1:]
    return pd.DataFrame(rows, columns=header)


# =========================================================================
# HELPER — NORMALISASI DATA (Google Sheet / rekap laporan)
# =========================================================================
def detect_column(columns, keywords) -> str | None:
    low_map = {c: str(c).strip().lower() for c in columns}
    for kw in keywords:
        for col, low in low_map.items():
            if kw in low:
                return col
    return None


def coalesce(df: pd.DataFrame, candidates) -> pd.Series:
    found = [c for c in df.columns if any(k in str(c).strip().lower() for k in candidates)]
    if not found:
        return pd.Series([None] * len(df), index=df.index)
    out = df[found[0]].astype("object")
    for c in found[1:]:
        out = out.where(out.notna() & (out.astype(str).str.strip() != ""), df[c])
    return out


def normalize_severity(val):
    if val is None or (not isinstance(val, str) and pd.isna(val)):
        return None
    v = str(val).strip().title()
    return v if v in ("Low", "Medium", "High") else None


@st.cache_data(show_spinner=False)
def prepare_data(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["timestamp"] = pd.to_datetime(df.get(col_map.get("timestamp")), errors="coerce")
    out["modul"] = df.get(col_map.get("modul"))
    out["modul"] = out["modul"].replace({"-": None}).fillna("Lainnya")
    out["deskripsi"] = coalesce(df, DESC_CANDIDATES)
    out["solusi"] = coalesce(df, SOLUSI_CANDIDATES)
    out["severity"] = df.get(col_map.get("severity")).map(normalize_severity) if col_map.get("severity") else None
    out["status"] = df.get(col_map.get("status")).astype("object") if col_map.get("status") else None
    out["due_date"] = pd.to_datetime(df.get(col_map.get("due_date")), errors="coerce") if col_map.get("due_date") else pd.NaT

    if col_map.get("week") and col_map.get("year"):
        out["week"] = pd.to_numeric(df.get(col_map["week"]), errors="coerce")
        out["year"] = pd.to_numeric(df.get(col_map["year"]), errors="coerce")
    else:
        iso = out["timestamp"].dt.isocalendar()
        out["week"] = iso["week"]
        out["year"] = iso["year"]

    out["week"] = out["week"].astype("Int64")
    out["year"] = out["year"].astype("Int64")
    return out


def filter_pairs(df_in: pd.DataFrame, pairs) -> pd.DataFrame:
    """Ambil baris df_in yang (year, week)-nya ada di `pairs` (list of (year, week))."""
    pairs = list(pairs)
    if df_in.empty or not pairs or "year" not in df_in.columns:
        return df_in.iloc[0:0]
    pairs_df = pd.DataFrame(pairs, columns=["year", "week"])
    return df_in.merge(pairs_df, on=["year", "week"], how="inner")


def compute_spi(df_period: pd.DataFrame, sev_w: dict, status_w: dict, status_default: int = 1):
    counts = {lvl: int((df_period["severity"] == lvl).sum()) for lvl in ("Low", "Medium", "High")}
    total_isu = len(df_period)
    if total_isu == 0:
        return counts, 0, 0, 0.0
    skor_sev = df_period["severity"].map(sev_w).fillna(0)
    skor_status = df_period["status"].map(status_w).fillna(status_default)
    total_skor = float((skor_sev + skor_status).sum())
    spi = total_skor / total_isu
    return counts, total_isu, total_skor, spi


# =========================================================================
# HELPER — INTEGRASI CLICKUP (dipakai tab Highlight Issue & SPI)
# =========================================================================
CLICKUP_STATUS_NORMALIZE = {
    "OPEN": "Open",
    "CLOSE": "Close",
    "CLOSED": "Close",
    "DONE": "Close",
    "COMPLETE": "Close",
    "ON PROGRESS": "On Progress",
    "IN PROGRESS": "On Progress",
    "ONGOING": "On Progress",
}


def has_clickup() -> bool:
    try:
        return bool(st.secrets["clickup"].get("api_token"))
    except Exception:  # noqa: BLE001
        return False


def clickup_list_id() -> str:
    try:
        lid = str(st.secrets["clickup"].get("list_id", "")).strip()
    except Exception:  # noqa: BLE001
        lid = ""
    return lid or CLICKUP_DEFAULT_LIST_ID


def normalize_clickup_status(s) -> str:
    if not s:
        return "Open"
    return CLICKUP_STATUS_NORMALIZE.get(str(s).strip().upper(), str(s).strip().title())


def _cf_by_name(task: dict) -> dict:
    return {cf.get("name"): cf for cf in task.get("custom_fields", []) if cf.get("name")}


def _cf_dropdown(cf: dict | None):
    """ClickUp dropdown value bisa berupa UUID option ATAU orderindex integer."""
    if not cf or cf.get("value") in (None, ""):
        return None
    val = cf["value"]
    opts = (cf.get("type_config") or {}).get("options", [])
    for o in opts:
        if str(o.get("id")) == str(val):
            return o.get("name") or o.get("label")
    try:
        vi = int(val)
        for o in opts:
            if o.get("orderindex") == vi:
                return o.get("name") or o.get("label")
    except (ValueError, TypeError):
        pass
    return str(val)


def _cf_date(cf: dict | None):
    if not cf or not cf.get("value"):
        return pd.NaT
    try:
        return pd.to_datetime(int(cf["value"]), unit="ms")
    except (ValueError, TypeError):
        return pd.to_datetime(cf["value"], errors="coerce")


def _cf_text(cf: dict | None):
    if not cf:
        return None
    v = cf.get("value")
    return str(v).strip() if v not in (None, "") else None


def _epoch_ms(v):
    if not v:
        return pd.NaT
    try:
        return pd.to_datetime(int(v), unit="ms")
    except (ValueError, TypeError):
        return pd.to_datetime(v, errors="coerce")


def _local_date_str(ts) -> str:
    """Tanggal kalender dari timestamp ClickUp.

    ClickUp menyimpan field 'date' sebagai midnight di zona waktu workspace
    (WIB/WITA), jadi nilainya bisa jatuh di sore hari UTC. Geser +12 jam
    sebelum ambil tanggalnya supaya kalendernya sesuai tampilan ClickUp.
    """
    if ts is None or pd.isna(ts):
        return "-"
    return (ts + pd.Timedelta(hours=12)).date().isoformat()


def _extract_labeled(text: str | None, label: str):
    """Ambil isi 'Label: ....' dari markdown/plain description (tahan format **Label:**)."""
    if not text:
        return None
    m = re.search(rf"{re.escape(label)}\s*:?\s*\**\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if not m:
        return None
    out = m.group(1).strip().strip("*").strip()
    return out or None


def _is_placeholder(v: str | None) -> bool:
    if not v:
        return True
    s = v.strip().lower().rstrip(".")
    return s in ("", "-", "n/a", "na", "belum ditentukan") or s.startswith("tbd")


def _clean_solusi(text: str | None, root_cause: str | None) -> str:
    parts = []
    wa = _extract_labeled(text, "Solusi Sementara (Workaround)")
    lp = _extract_labeled(text, "Solusi Jangka Panjang")
    if not _is_placeholder(wa):
        parts.append(f"Workaround: {wa}")
    if not _is_placeholder(lp):
        parts.append(f"Jangka panjang: {lp}")
    if not _is_placeholder(root_cause):
        parts.append(f"Root cause: {root_cause}")
    return " | ".join(parts) if parts else "-"


def _clickup_tasks_to_df(tasks: list[dict]) -> pd.DataFrame:
    rows = []
    for t in tasks:
        cf = _cf_by_name(t)
        desc = t.get("markdown_description") or t.get("description") or t.get("text_content") or ""

        modul = _cf_dropdown(cf.get("Jenis Kendala")) or _extract_labeled(desc, "Modul") or "Lainnya"

        tgl = _cf_date(cf.get("Timestamp"))
        if pd.isna(tgl):
            tgl = _epoch_ms(t.get("date_created"))

        deskripsi = _cf_text(cf.get("Kronologi Issue")) or (t.get("name") or "").strip() or "-"

        solusi = _clean_solusi(desc, _cf_text(cf.get("Root Cause")))

        sev = normalize_severity(_cf_dropdown(cf.get("Risiko Issue"))) or "Belum Dinilai"

        due = _epoch_ms(t.get("due_date"))
        if pd.isna(due):
            due = _cf_date(cf.get("Timestamps Closed"))
        due_txt = _local_date_str(due) if not pd.isna(due) else "TBD"

        status_raw = _cf_dropdown(cf.get("Status")) or (t.get("status") or {}).get("status")
        status = normalize_clickup_status(status_raw)

        rows.append({
            "No": 0,
            "Modul": modul,
            "Tanggal Pelaporan": _local_date_str(tgl),
            "Deskripsi": deskripsi,
            "Solusi / Update": solusi,
            "Risiko Isu": sev,
            "Due Date": due_txt,
            "Status": status,
            "Link": t.get("url") or "",
        })

    df = pd.DataFrame(rows, columns=HIGHLIGHT_COLUMNS)
    if not df.empty:
        # urutkan: High dulu, lalu terbaru
        rank = {"High": 3, "Medium": 2, "Low": 1, "Belum Dinilai": 0}
        df["_r"] = df["Risiko Isu"].map(rank).fillna(0)
        df["_d"] = pd.to_datetime(df["Tanggal Pelaporan"], errors="coerce")
        df = df.sort_values(["_r", "_d"], ascending=[False, False]).drop(columns=["_r", "_d"])
        df["No"] = range(1, len(df) + 1)
    return df.reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner="Menarik issue dari ClickUp...")
def fetch_clickup_issues(list_id: str) -> pd.DataFrame:
    import requests

    token = st.secrets["clickup"]["api_token"]
    headers = {"Authorization": token}
    params = {
        "include_closed": "true",
        "subtasks": "false",
        "include_markdown_description": "true",
    }
    all_tasks: list[dict] = []
    for page in range(0, 50):
        resp = requests.get(
            f"https://api.clickup.com/api/v2/list/{list_id}/task",
            headers=headers, params={**params, "page": page}, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("tasks", [])
        all_tasks.extend(batch)
        if data.get("last_page") or not batch:
            break
    return _clickup_tasks_to_df(all_tasks)


def highlight_to_spi_source(hdf: pd.DataFrame) -> pd.DataFrame:
    """Ubah tabel Highlight Issue jadi input compute_spi (kolom severity + status)."""
    if hdf is None or hdf.empty:
        return pd.DataFrame(columns=["modul", "severity", "status"])
    return pd.DataFrame({
        "modul": hdf.get("Modul", pd.Series(dtype=object)),
        "severity": hdf.get("Risiko Isu", pd.Series(dtype=object)).map(normalize_severity),
        "status": hdf.get("Status", pd.Series(dtype=object)),
    })


# =========================================================================
# SUMBER DATA GOOGLE SHEET — dipakai diam-diam dari Secrets/config tersimpan.
# Prioritas sheet_url/sheet_tab: Secrets -> file config lokal.
# =========================================================================
saved_cfg = load_saved_config()
try:
    _secrets_sheet_url = st.secrets.get("sheet_url", "")
    _secrets_sheet_tab = st.secrets.get("sheet_tab", "")
except Exception:  # noqa: BLE001
    _secrets_sheet_url = _secrets_sheet_tab = ""

source_mode = saved_cfg.get("source_mode", "Google Sheet (Live)")
sheet_url = _secrets_sheet_url or saved_cfg.get("sheet_url", "")
sheet_tab = _secrets_sheet_tab or saved_cfg.get("sheet_tab", "Form Responses 1")
use_api = has_service_account()

raw_df = None
data_error = None

if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    load_from_gsheet.clear()
    load_via_api.clear()
    fetch_clickup_issues.clear()
    st.rerun()

if source_mode == "Google Sheet (Live)" and sheet_url.strip():
    try:
        sheet_id = extract_sheet_id(sheet_url)
        raw_df = load_via_api(sheet_id, sheet_tab) if use_api else load_from_gsheet(sheet_id, sheet_tab)
    except Exception as e:  # noqa: BLE001
        data_error = f"Gagal mengambil data Rekap dari Google Sheet: {e}"
else:
    data_error = "Sumber data Rekap belum dikonfigurasi (Google Sheet)."

if data_error:
    st.sidebar.error(data_error)

# Pemetaan kolom selalu auto-deteksi.
col_map = {
    key: (detect_column(raw_df.columns, keywords) if raw_df is not None and not raw_df.empty else None)
    for key, keywords in COLUMN_CANDIDATES.items()
}

# =========================================================================
# OLAH DATA REKAP (Google Sheet)
# =========================================================================
df = pd.DataFrame()
if raw_df is not None and not raw_df.empty:
    df = prepare_data(raw_df, col_map)

# =========================================================================
# TARIK DATA CLICKUP (Highlight Issue) — sekali saat load, bisa di-refresh
# =========================================================================
clickup_ready = has_clickup()
clickup_error = None
LIST_ID = clickup_list_id()

if "highlight_df" not in st.session_state:
    st.session_state.highlight_df = pd.DataFrame(columns=HIGHLIGHT_COLUMNS)
    if clickup_ready:
        try:
            st.session_state.highlight_df = fetch_clickup_issues(LIST_ID)
        except Exception as e:  # noqa: BLE001
            clickup_error = f"Gagal menarik dari ClickUp: {e}"

highlight_df = st.session_state.highlight_df

# =========================================================================
# SIDEBAR — FILTER MINGGU (hanya memengaruhi tab Rekap Laporan)
# =========================================================================
st.sidebar.header("📅 Filter Periode")
st.sidebar.caption("Filter minggu ini hanya berlaku untuk tab **Rekap Laporan**.")
all_pairs = []
anchor_pair = None
if not df.empty and df["year"].notna().any() and df["week"].notna().any():
    all_pairs = sorted({
        (int(y), int(w)) for y, w in df[["year", "week"]].dropna().itertuples(index=False)
    })
    pairs_desc = list(reversed(all_pairs))
    labels_desc = [f"Week {w} {y}" for (y, w) in pairs_desc]
    chosen_idx = st.sidebar.selectbox("Pilih Minggu", range(len(pairs_desc)), format_func=lambda i: labels_desc[i])
    anchor_pair = pairs_desc[chosen_idx]
    st.sidebar.caption("Bar & tren harian otomatis merekap hingga 4 minggu ke belakang dari minggu ini.")
else:
    st.sidebar.caption("Belum ada data untuk difilter.")

if anchor_pair:
    anchor_idx = all_pairs.index(anchor_pair)
    trend_pairs = all_pairs[max(0, anchor_idx - 3): anchor_idx + 1]
    anchor_label = f"Week {anchor_pair[1]} {anchor_pair[0]}"
    df_period = filter_pairs(df, [anchor_pair])
    df_trend = filter_pairs(df, trend_pairs)
else:
    trend_pairs = []
    anchor_label = None
    df_period = df.iloc[0:0]
    df_trend = df.iloc[0:0]

# =========================================================================
# SIDEBAR — BOBOT SKOR SPI (status diambil dari Highlight Issue / ClickUp)
# =========================================================================
st.sidebar.header("⚖️ Bobot Skor SPI")
with st.sidebar.expander("Atur bobot", expanded=False):
    st.caption("Total Skor = Σ (bobot Severity + bobot Status) dari Highlight Issue.")
    sev_w = {}
    for lvl in ("Low", "Medium", "High"):
        sev_w[lvl] = st.number_input(
            f"Bobot Severity: {lvl}", min_value=0, max_value=20,
            value=DEFAULT_SEVERITY_WEIGHT[lvl], step=1, key=f"sevw_{lvl}",
        )

    _statuses = sorted(
        s for s in highlight_df.get("Status", pd.Series(dtype=object)).dropna().unique() if str(s).strip()
    )
    status_values = _statuses or list(DEFAULT_STATUS_WEIGHT)
    status_w = {}
    for s in status_values:
        default_val = DEFAULT_STATUS_WEIGHT.get(s, 1)
        status_w[s] = st.number_input(
            f"Bobot Status: {s}", min_value=0, max_value=20, value=default_val, step=1, key=f"statw_{s}"
        )
    status_default = st.number_input("Bobot Status lainnya (default)", min_value=0, max_value=20, value=1, step=1)

if not status_w:
    status_w = DEFAULT_STATUS_WEIGHT
    status_default = 1

# =========================================================================
# HEADER
# =========================================================================
periode_txt = anchor_label if anchor_label else "belum ada periode dipilih"

st.markdown(
    f"""
    <div class="becare-hero">
        <h1>🟢 BeCare — System Performance Index &amp; Highlight Issue</h1>
        <p>Rekap laporan (Google Sheet) &amp; Highlight Issue + SPI (ClickUp) · <b>Rekap: {periode_txt}</b></p>
    </div>
    """,
    unsafe_allow_html=True,
)

# =========================================================================
# RINGKASAN CEPAT
# =========================================================================
spi_src_all = highlight_to_spi_source(highlight_df)
spi_src_valid = spi_src_all[spi_src_all["severity"].notna()]
if not spi_src_valid.empty:
    _kc, _kti, _kts, _kspi = compute_spi(spi_src_valid, sev_w, status_w, status_default)
    kpi_spi_display, kpi_high = f"{_kspi:.2f}", _kc["High"]
else:
    kpi_spi_display, kpi_high = "—", 0

k1, k2, k3, k4 = st.columns(4)
k1.metric("📄 Laporan Minggu Ini", len(df_period), help="Jumlah laporan Google Sheet pada minggu terpilih")
k2.metric("📝 Highlight Issue", len(highlight_df), help="Jumlah issue ditarik dari ClickUp")
k3.metric("🎯 Skor SPI", kpi_spi_display, help="Dihitung dari Highlight Issue (ClickUp)")
k4.metric("🔴 Issue High", kpi_high, help="Jumlah issue level High di Highlight Issue")

tab_rekap, tab_highlight, tab_spi = st.tabs(
    ["📈 Rekap Laporan", "📝 Highlight Issue", "📊 System Performance Index"]
)

# =========================================================================
# TAB 1 — REKAP LAPORAN (Google Sheet)
# =========================================================================
with tab_rekap:
    st.caption("Volume laporan mentah dari Google Sheet — tidak tergantung klasifikasi Risiko Isu.")

    if df_trend.empty:
        st.info("Belum ada data pada periode yang dipilih. Cek koneksi Google Sheet & pilih minggu di sidebar.")
    else:
        wk_counts = (
            df_trend.dropna(subset=["year", "week"])
            .groupby(["year", "week"]).size().reset_index(name="jumlah")
            .sort_values(["year", "week"])
        )
        wk_counts["label"] = wk_counts.apply(lambda r: f"W{int(r['week'])} '{str(int(r['year']))[-2:]}", axis=1)
        avg_wk = wk_counts["jumlah"].mean()

        rc1, rc2 = st.columns(2)

        with rc1:
            st.markdown("**Laporan Per Minggu**")
            fig_w = go.Figure(go.Bar(
                x=wk_counts["label"], y=wk_counts["jumlah"],
                marker_color=BRAND_GREEN,
                text=wk_counts["jumlah"], textposition="outside",
                cliponaxis=False,
                hovertemplate="<b>%{x}</b><br>Laporan: %{y}<extra></extra>",
            ))
            fig_w.add_hline(
                y=avg_wk, line_dash="dash", line_color="#898781",
                annotation_text=f"Average {avg_wk:.1f}", annotation_position="top left",
                annotation_font_color="#52514e",
            )
            fig_w.update_layout(
                height=240, margin=dict(l=10, r=10, t=30, b=30),
                xaxis=dict(showgrid=False, title=None),
                yaxis=dict(showgrid=True, gridcolor="#e1e0d9", title=None),
                plot_bgcolor="#fcfcfb", paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
            )
            st.plotly_chart(fig_w, use_container_width=True, config={"displayModeBar": False})

            if len(wk_counts) >= 2:
                last, prev = wk_counts.iloc[-1], wk_counts.iloc[-2]
                diff = int(last["jumlah"] - prev["jumlah"])
                arah = "naik" if diff > 0 else "turun" if diff < 0 else "sama dengan"
                posisi = "di bawah" if last["jumlah"] < avg_wk else "di atas"
                st.caption(
                    f"{last['label']} {arah} {abs(diff)} laporan vs {prev['label']}, "
                    f"dan berada **{posisi} rata-rata** {len(wk_counts)} minggu terakhir."
                )

        with rc2:
            st.markdown("**Grafik Tren Harian**")
            daily = df_trend.dropna(subset=["timestamp"]).groupby(df_trend["timestamp"].dt.date).size().sort_index()
            avg_day = daily.mean() if len(daily) else 0
            fig_d = go.Figure(go.Scatter(
                x=list(daily.index), y=daily.values,
                mode="lines+markers", line=dict(color=BRAND_GREEN, width=2),
                marker=dict(size=6, color=BRAND_GREEN),
                hovertemplate="%{x|%d %b}<br>Laporan: %{y}<extra></extra>",
            ))
            fig_d.add_hline(
                y=avg_day, line_dash="dash", line_color="#898781",
                annotation_text=f"Average {avg_day:.2f}", annotation_position="top left",
                annotation_font_color="#52514e",
            )
            fig_d.update_layout(
                height=240, margin=dict(l=10, r=10, t=30, b=30),
                xaxis=dict(showgrid=False, title=None),
                yaxis=dict(showgrid=True, gridcolor="#e1e0d9", title=None),
                plot_bgcolor="#fcfcfb", paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                hovermode="x unified",
            )
            st.plotly_chart(fig_d, use_container_width=True, config={"displayModeBar": False})
            st.caption(f"Tren harian jumlah laporan, {trend_pairs[0][1]}–{trend_pairs[-1][1]} {trend_pairs[-1][0]}.")

    st.markdown("**Distribusi Pelaporan**" + (f" — {anchor_label}" if anchor_label else ""))
    if df_period.empty:
        st.info("Belum ada data pada minggu yang dipilih.")
    else:
        modul_counts = df_period["modul"].fillna("Lainnya").value_counts()
        TOP_N = 6
        if len(modul_counts) > TOP_N:
            modul_counts = pd.concat([
                modul_counts.iloc[:TOP_N],
                pd.Series({"Others": modul_counts.iloc[TOP_N:].sum()}),
            ])

        total_dist = int(modul_counts.sum())
        fig_p = go.Figure(go.Pie(
            labels=modul_counts.index, values=modul_counts.values, hole=0.55,
            marker=dict(colors=CATEGORICAL[: len(modul_counts)], line=dict(color="#fcfcfb", width=2)),
            textinfo="label+percent", textposition="outside",
            hovertemplate="<b>%{label}</b><br>%{value} laporan (%{percent})<extra></extra>",
        ))
        fig_p.update_layout(
            height=340, margin=dict(l=10, r=10, t=10, b=10), showlegend=True,
            annotations=[dict(text=f"Total<br><b>{total_dist}</b><br>Laporan", x=0.5, y=0.5, font_size=14, showarrow=False)],
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_p, use_container_width=True, config={"displayModeBar": False})
        dominant = modul_counts.idxmax()
        dominant_pct = modul_counts.max() / total_dist * 100
        st.caption(f"Pelaporan {anchor_label} didominasi oleh **{dominant}** ({dominant_pct:.1f}%).")


# =========================================================================
# TAB 2 — HIGHLIGHT ISSUE (ditarik dari ClickUp)
# =========================================================================
with tab_highlight:
    hc1, hc2 = st.columns([3, 1])
    hc1.caption(
        f"Ditarik otomatis dari ClickUp — list **Monitoring Issue Operational** (`{LIST_ID}`). "
        "Boleh diedit manual sebelum diunduh; SPI dihitung dari tabel ini."
    )
    if hc2.button("🔄 Tarik ulang dari ClickUp", use_container_width=True, disabled=not clickup_ready):
        fetch_clickup_issues.clear()
        try:
            st.session_state.highlight_df = fetch_clickup_issues(LIST_ID)
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"Gagal menarik dari ClickUp: {e}")

    if not clickup_ready:
        st.warning(
            "🔌 ClickUp belum terhubung. Tambahkan di **Secrets**:\n\n"
            "```toml\n[clickup]\napi_token = \"pk_xxxxx\"\nlist_id = \"901820651612\"\n```\n\n"
            "Personal token dibuat di ClickUp → Settings → Apps → *Generate*."
        )
    elif clickup_error:
        st.error(clickup_error)

    if highlight_df.empty:
        st.info("Belum ada Highlight Issue. Klik **Tarik ulang dari ClickUp** setelah token dipasang.")
    else:
        st.caption(f"{len(highlight_df)} issue termuat.")

    edited = st.data_editor(
        st.session_state.highlight_df,
        num_rows="dynamic",
        use_container_width=True,
        key="highlight_editor",
        column_config={
            "No": st.column_config.NumberColumn("No", width="small"),
            "Modul": st.column_config.TextColumn("Modul"),
            "Tanggal Pelaporan": st.column_config.TextColumn("Tanggal Pelaporan"),
            "Deskripsi": st.column_config.TextColumn("Deskripsi", width="large"),
            "Solusi / Update": st.column_config.TextColumn("Solusi / Update", width="large"),
            "Risiko Isu": st.column_config.SelectboxColumn(
                "Risiko Isu", options=["Belum Dinilai", "Low", "Medium", "High"]
            ),
            "Due Date": st.column_config.TextColumn("Due Date"),
            "Status": st.column_config.SelectboxColumn(
                "Status", options=["Open", "On Progress", "Workaround", "Close", "Closed Permanent"]
            ),
            "Link": st.column_config.LinkColumn("Link", display_text="buka di ClickUp"),
        },
    )
    if not edited.empty:
        edited["No"] = range(1, len(edited) + 1)
    st.session_state.highlight_df = edited
    highlight_df = edited

    csv_bytes = highlight_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download Highlight Issue (CSV)", data=csv_bytes,
        file_name="highlight_issue.csv", mime="text/csv",
    )


# =========================================================================
# TAB 3 — SYSTEM PERFORMANCE INDEX (dihitung dari Highlight Issue / ClickUp)
# =========================================================================
with tab_spi:
    st.latex(
        r"SPI_{Severity+Status}=\dfrac{\text{Total Skor}}{\text{Total Issue}}"
        r"\qquad \text{Total Skor}=\sum_{i=1}^{n}\big(\text{Bobot Severity}_i+\text{Bobot Status}_i\big)"
    )
    st.caption("Sumber: tabel **Highlight Issue** (ClickUp). Ubah bobot di sidebar untuk menyesuaikan aturan skoring.")

    spi_src = highlight_to_spi_source(highlight_df)
    spi_src_valid = spi_src[spi_src["severity"].notna()]

    if highlight_df.empty:
        st.info("Belum ada Highlight Issue untuk dihitung. Tarik data di tab **Highlight Issue** dulu.")
    elif spi_src_valid.empty:
        st.warning(
            f"Ada **{len(highlight_df)} issue** di Highlight Issue, tapi belum ada yang diberi **Risiko Isu** "
            "(Low/Medium/High). Isi kolom Risiko Isu di ClickUp atau langsung di tabel Highlight Issue."
        )
    else:
        counts, total_isu, total_skor, spi = compute_spi(spi_src_valid, sev_w, status_w, status_default)

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric(f"{STATUS_ICON['Low']} Low", counts["Low"])
        m2.metric(f"{STATUS_ICON['Medium']} Medium", counts["Medium"])
        m3.metric(f"{STATUS_ICON['High']} High", counts["High"])
        m4.metric("Total Isu", total_isu)
        m5.metric("Total Skor", f"{total_skor:.0f}")
        m6.metric("Skor SPI", f"{spi:.2f}")

        if counts["High"] > 0:
            st.warning(f"⚠️ Ada **{counts['High']} issue level HIGH** yang perlu perhatian segera.")
        elif counts["Medium"] > total_isu * 0.3:
            st.warning(f"⚠️ Proporsi issue **Medium** cukup tinggi ({counts['Medium']}/{total_isu}).")
        else:
            st.success(f"✅ Mayoritas issue berada pada level **Low** ({counts['Low']}/{total_isu}), tanpa issue High.")

        c1, c2 = st.columns([1, 1.3])

        with c1:
            st.markdown("**Distribusi Severity**")
            order = [l for l in SEVERITY_ORDER if counts[l] >= 0]
            fig = go.Figure(
                go.Bar(
                    x=[counts[l] for l in order],
                    y=[f"{STATUS_ICON[l]} {l}" for l in order],
                    orientation="h",
                    marker_color=[STATUS_COLOR[l] for l in order],
                    text=[f"{counts[l]} ({counts[l] / total_isu * 100:.0f}%)" for l in order],
                    textposition="outside",
                    cliponaxis=False,
                    hovertemplate="<b>%{y}</b><br>%{x} isu<extra></extra>",
                )
            )
            fig.update_layout(
                height=230,
                margin=dict(l=10, r=60, t=10, b=10),
                xaxis=dict(showgrid=True, gridcolor="#e1e0d9", zeroline=False, title=None),
                yaxis=dict(showgrid=False, title=None),
                plot_bgcolor="#fcfcfb",
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                bargap=0.45,
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        with c2:
            st.markdown("**Rincian SPI per Modul**")
            per_mod = []
            for mod, grp in spi_src.groupby("modul"):
                grp_valid = grp[grp["severity"].notna()]
                if grp_valid.empty:
                    continue
                _, n_isu, skor, spi_m = compute_spi(grp_valid, sev_w, status_w, status_default)
                per_mod.append({"Modul": mod, "Isu": n_isu, "Total Skor": round(skor), "Skor SPI": round(spi_m, 2)})
            if per_mod:
                per_mod_df = pd.DataFrame(per_mod).sort_values("Skor SPI", ascending=False)
                st.dataframe(per_mod_df, use_container_width=True, hide_index=True, height=230)
            else:
                st.caption("Belum ada modul dengan Risiko Isu terisi.")

        with st.expander("Lihat daftar issue yang dihitung"):
            show = highlight_df[highlight_df["Risiko Isu"].isin(["Low", "Medium", "High"])]
            st.dataframe(
                show[["No", "Modul", "Deskripsi", "Risiko Isu", "Status"]],
                use_container_width=True, hide_index=True,
            )
