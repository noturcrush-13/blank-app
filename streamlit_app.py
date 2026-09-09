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
    "Solusi / Update", "Risiko Isu", "Due Date", "Status",
]

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
    "Closed Permanent": 0,
    "Closed Temporary (workaround)": 1,
    "Workaround": 1,
    "Open": 2,
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

    /* Kartu metric (Low/Medium/High/Total dst) */
    div[data-testid="stMetric"]{
        background:#ffffff; border:1px solid #e6e6df; border-radius:12px;
        padding:.85rem 1rem .55rem; box-shadow:0 1px 5px rgba(0,0,0,.045);
    }

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
# HELPER — AMBIL DATA (GOOGLE SHEET LIVE / UPLOAD FILE)
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


@st.cache_data(show_spinner=False)
def load_from_upload(file_bytes: bytes, file_name: str, sheet_name: str) -> pd.DataFrame:
    import io
    buf = io.BytesIO(file_bytes)
    if file_name.lower().endswith(".csv"):
        return pd.read_csv(buf)
    return pd.read_excel(buf, sheet_name=sheet_name)


def list_excel_sheets(file_bytes: bytes) -> list[str]:
    import io
    return pd.ExcelFile(io.BytesIO(file_bytes)).sheet_names


# =========================================================================
# HELPER — NORMALISASI DATA
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
    if pd.isna(val):
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
# SUMBER DATA — dipakai diam-diam dari config/secrets tersimpan, sidebar
# cuma nampilin tombol Refresh (menu koneksi disembunyikan, sudah tidak
# perlu di-setup ulang tiap buka app).
# =========================================================================
saved_cfg = load_saved_config()
source_mode = saved_cfg.get("source_mode", "Google Sheet (Live)")
sheet_url = saved_cfg.get("sheet_url", "")
sheet_tab = saved_cfg.get("sheet_tab", "Form Responses 1")
use_api = has_service_account()

raw_df = None
data_error = None

if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    load_from_gsheet.clear()
    load_via_api.clear()
    st.rerun()

if source_mode == "Google Sheet (Live)" and sheet_url.strip():
    try:
        sheet_id = extract_sheet_id(sheet_url)
        raw_df = load_via_api(sheet_id, sheet_tab) if use_api else load_from_gsheet(sheet_id, sheet_tab)
    except Exception as e:  # noqa: BLE001
        data_error = f"Gagal mengambil data dari Google Sheet: {e}"
elif source_mode != "Google Sheet (Live)":
    data_error = "Sumber data belum dikonfigurasi (mode Upload File tidak lagi tersedia di sidebar)."
else:
    data_error = "Sumber data belum dikonfigurasi. Hubungi admin untuk menghubungkan Google Sheet."

if data_error:
    st.sidebar.error(data_error)

# Pemetaan kolom selalu auto-deteksi (menu manual override disembunyikan dari sidebar).
col_map = {
    key: (detect_column(raw_df.columns, keywords) if raw_df is not None and not raw_df.empty else None)
    for key, keywords in COLUMN_CANDIDATES.items()
}

# =========================================================================
# OLAH DATA
# =========================================================================
df = pd.DataFrame()
if raw_df is not None and not raw_df.empty:
    df = prepare_data(raw_df, col_map)

df_issues = df[df["severity"].notna()] if not df.empty else df  # subset all-time yang sudah diberi Resiko Isu

# =========================================================================
# SIDEBAR — FILTER MINGGU
# =========================================================================
st.sidebar.header("📅 Filter Periode")
# Filter berdasarkan SEMUA laporan (df), bukan cuma yang sudah diklasifikasi
# severity-nya — supaya pilihan minggu tetap muncul walau triase belum jalan.
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
    st.sidebar.caption("Chart Laporan Per Minggu & Tren Harian otomatis merekap hingga 4 minggu ke belakang dari minggu ini.")
else:
    st.sidebar.caption("Belum ada data untuk difilter.")

if anchor_pair:
    anchor_idx = all_pairs.index(anchor_pair)
    trend_pairs = all_pairs[max(0, anchor_idx - 3): anchor_idx + 1]  # s.d. 4 minggu terakhir s.d. minggu terpilih
    anchor_label = f"Week {anchor_pair[1]} {anchor_pair[0]}"
    df_period = filter_pairs(df, [anchor_pair])  # 1 minggu — dipakai SPI, Highlight Issue, Distribusi
    df_trend = filter_pairs(df, trend_pairs)     # s.d. 4 minggu — dipakai bar & tren harian
else:
    trend_pairs = []
    anchor_label = None
    df_period = df.iloc[0:0]
    df_trend = df.iloc[0:0]

df_period_issues = (
    df_period[df_period["severity"].notna()] if "severity" in df_period.columns else df_period
)  # subset periode (1 minggu) yang sudah diklasifikasi severity

# =========================================================================
# SIDEBAR — BOBOT SKOR SPI (dinamis, bisa diubah user)
# =========================================================================
st.sidebar.header("⚖️ Bobot Skor SPI")
with st.sidebar.expander("Atur bobot", expanded=False):
    st.caption("Total Skor = Σ (bobot Severity + bobot Status). Sesuaikan dengan aturan skoring internal Anda.")
    sev_w = {}
    for lvl in ("Low", "Medium", "High"):
        sev_w[lvl] = st.number_input(
            f"Bobot Severity: {lvl}", min_value=0, max_value=20,
            value=DEFAULT_SEVERITY_WEIGHT[lvl], step=1, key=f"sevw_{lvl}",
        )

    status_values = sorted(df_issues["status"].dropna().unique().tolist()) if not df_issues.empty else list(DEFAULT_STATUS_WEIGHT)
    status_w = {}
    for s in status_values:
        default_val = DEFAULT_STATUS_WEIGHT.get(s, 1)
        status_w[s] = st.number_input(f"Bobot Status: {s}", min_value=0, max_value=20, value=default_val, step=1, key=f"statw_{s}")
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
        <p>Monitoring sistem untuk operasional yang lebih andal · <b>{periode_txt}</b></p>
    </div>
    """,
    unsafe_allow_html=True,
)

# =========================================================================
# SECTION 0 — REKAP LAPORAN (volume mentah, TIDAK butuh klasifikasi severity)
# =========================================================================
st.subheader("📈 Rekap Laporan")
st.caption("Volume laporan mentah — tidak tergantung status klasifikasi Resiko Isu.")

if df_trend.empty:
    st.info("Belum ada data pada periode yang dipilih. Hubungkan/upload data dan pilih minggu di sidebar.")
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

st.divider()

# =========================================================================
# SECTION 1 — SYSTEM PERFORMANCE INDEX (SPI)
# =========================================================================
st.subheader("📊 System Performance Index (SPI)")

st.latex(
    r"SPI_{Severity+Status}=\dfrac{\text{Total Skor}}{\text{Total Issue}}"
    r"\qquad \text{Total Skor}=\sum_{i=1}^{n}\big(\text{Bobot Severity}_i+\text{Bobot Status}_i\big)"
)

if df_period.empty:
    st.info("Belum ada data pada periode yang dipilih. Hubungkan/upload data dan pilih minggu di sidebar.")
elif df_period_issues.empty:
    st.warning(
        f"Ada **{len(df_period)} laporan** pada periode ini, tapi belum satupun yang diberi klasifikasi "
        "**Resiko Isu** (severity) di sheet — Skor SPI baru bisa dihitung setelah kolom itu diisi "
        "(biasanya diisi saat proses triase/review issue, bukan otomatis dari form). "
        "Sambil menunggu, Anda tetap bisa mulai menyusun **Highlight Issue** manual di bagian bawah."
    )
else:
    counts, total_isu, total_skor, spi = compute_spi(df_period_issues, sev_w, status_w, status_default)

    # --- perbandingan dengan minggu sebelumnya (persis 1 minggu sebelum minggu terpilih) ---
    spi_prev = None
    if anchor_pair in all_pairs:
        anchor_idx_all = all_pairs.index(anchor_pair)
        if anchor_idx_all > 0:
            prev_issues = filter_pairs(df_issues, [all_pairs[anchor_idx_all - 1]])
            if not prev_issues.empty:
                _, _, _, spi_prev = compute_spi(prev_issues, sev_w, status_w, status_default)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric(f"{STATUS_ICON['Low']} Low", counts["Low"])
    m2.metric(f"{STATUS_ICON['Medium']} Medium", counts["Medium"])
    m3.metric(f"{STATUS_ICON['High']} High", counts["High"])
    m4.metric("Total Isu", total_isu)
    m5.metric("Total Skor", f"{total_skor:.0f}")
    delta = None if spi_prev is None else round(spi - spi_prev, 2)
    m6.metric("Skor SPI", f"{spi:.2f}", delta=delta, delta_color="inverse")

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
        st.markdown("**Tren Skor SPI per Minggu (4 minggu terakhir)**")
        trend_rows = []
        for (y, w) in trend_pairs:
            sub = filter_pairs(df_issues, [(y, w)])
            _, _, _, spi_w = compute_spi(sub, sev_w, status_w, status_default)
            trend_rows.append({"label": f"W{w} '{str(y)[-2:]}", "spi": spi_w})
        if len(trend_rows) >= 2:
            trend_df = pd.DataFrame(trend_rows)
            fig2 = go.Figure(
                go.Scatter(
                    x=trend_df["label"], y=trend_df["spi"],
                    mode="lines+markers+text",
                    line=dict(color="#0ca30c", width=2),
                    marker=dict(size=9, color="#0ca30c"),
                    text=[f"{v:.2f}" for v in trend_df["spi"]],
                    textposition="top center",
                )
            )
            fig2.update_layout(
                height=230,
                margin=dict(l=10, r=10, t=20, b=10),
                yaxis=dict(showgrid=True, gridcolor="#e1e0d9", title="Skor SPI"),
                xaxis=dict(showgrid=False, title=None),
                plot_bgcolor="#fcfcfb",
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
            )
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Riwayat minggu di data ini belum cukup (< 2 minggu) untuk menampilkan tren Skor SPI.")

st.divider()

# =========================================================================
# SECTION 2 — HIGHLIGHT ISSUE (dinamis, bisa diinput/diedit user)
# =========================================================================
st.subheader("📝 Highlight Issue")
st.caption("Tabel ini dinamis — tambah, edit, atau hapus baris langsung. Bisa juga diisi otomatis dari data terfilter.")

if "highlight_df" not in st.session_state:
    st.session_state.highlight_df = pd.DataFrame(columns=HIGHLIGHT_COLUMNS)

ac1, ac2, ac3 = st.columns([1.4, 1, 1])
n_auto = ac1.number_input("Jumlah issue prioritas diambil", min_value=1, max_value=20, value=5, step=1)
auto_fill = ac2.button("➕ Isi otomatis dari data terfilter", use_container_width=True)
clear_table = ac3.button("🗑️ Kosongkan tabel", use_container_width=True)

if clear_table:
    st.session_state.highlight_df = pd.DataFrame(columns=HIGHLIGHT_COLUMNS)

if auto_fill:
    if df_period.empty:
        st.warning("Tidak ada data pada periode terpilih untuk diambil otomatis.")
    else:
        sev_rank = {"High": 3, "Medium": 2, "Low": 1}
        cand = df_period.copy()
        cand["_rank"] = cand["severity"].map(sev_rank).fillna(0)
        # Status kosong (belum ditriase) dianggap masih "Open" — tetap layak jadi kandidat highlight.
        is_open = cand["status"].fillna("Open") != "Closed Permanent"
        cand = cand[(cand["_rank"] >= 2) | is_open]
        cand = cand.sort_values(["_rank", "timestamp"], ascending=[False, False]).head(n_auto)

        new_rows = pd.DataFrame({
            "No": range(1, len(cand) + 1),
            "Modul": cand["modul"].values,
            "Tanggal Pelaporan": cand["timestamp"].dt.date.astype(str).values,
            "Deskripsi": cand["deskripsi"].fillna("-").values,
            "Solusi / Update": cand["solusi"].fillna("-").values,
            "Risiko Isu": cand["severity"].fillna("Belum Dinilai").values,
            "Due Date": cand["due_date"].dt.date.astype(str).where(cand["due_date"].notna(), "TBD").values,
            "Status": cand["status"].fillna("Open").values,
        })
        combined = pd.concat([st.session_state.highlight_df, new_rows], ignore_index=True)
        combined = combined.drop_duplicates(subset=["Modul", "Deskripsi"], keep="first")
        combined["No"] = range(1, len(combined) + 1)
        st.session_state.highlight_df = combined

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
        "Risiko Isu": st.column_config.SelectboxColumn("Risiko Isu", options=["Belum Dinilai", "Low", "Medium", "High"]),
        "Due Date": st.column_config.TextColumn("Due Date"),
        "Status": st.column_config.SelectboxColumn(
            "Status", options=["Open", "On Progress", "Workaround", "Closed Permanent", "Closed Temporary (workaround)"]
        ),
    },
)
edited["No"] = range(1, len(edited) + 1)
st.session_state.highlight_df = edited

dc1, dc2 = st.columns([1, 3])
csv_bytes = st.session_state.highlight_df.to_csv(index=False).encode("utf-8")
dc1.download_button("⬇️ Download Highlight Issue (CSV)", data=csv_bytes, file_name="highlight_issue.csv", mime="text/csv")

# --- opsional: simpan balik ke Google Sheet, hanya aktif jika service account tersedia ---
if source_mode == "Google Sheet (Live)" and sheet_url.strip():
    if has_service_account():
        if dc2.button("💾 Simpan Highlight Issue ke tab 'Highlight Issue' di Google Sheet"):
            try:
                gc = get_gspread_client()
                sh = gc.open_by_key(extract_sheet_id(sheet_url))
                try:
                    ws = sh.worksheet("Highlight Issue")
                    ws.clear()
                except Exception:  # noqa: BLE001
                    ws = sh.add_worksheet("Highlight Issue", rows=100, cols=len(HIGHLIGHT_COLUMNS))
                ws.update([HIGHLIGHT_COLUMNS] + st.session_state.highlight_df.astype(str).values.tolist())
                st.success("Tersimpan ke Google Sheet, tab 'Highlight Issue'.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Gagal menyimpan ke Google Sheet: {e}")
    else:
        dc2.caption(
            "💡 Tambahkan kredensial `gcp_service_account` di *Secrets* untuk mengaktifkan simpan-otomatis "
            "Highlight Issue ke tab Google Sheet Anda (opsional)."
        )
