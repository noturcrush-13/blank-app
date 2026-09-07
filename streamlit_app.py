import streamlit as st
import pandas as pd

# Judul Aplikasi
st.title("💰 Expense Tracker Sederhana")

# Inisialisasi data transaksi di Session State jika belum ada
if "transactions" not in st.session_state:
    st.session_state.transactions = pd.DataFrame(
        columns=["Tanggal", "Kategori", "Tipe", "Jumlah (Rp)", "Keterangan"]
    )

# --- SIDEBAR: FORM INPUT TRANSAKSI ---
st.sidebar.header("➕ Tambah Transaksi")

with st.sidebar.form("expense_form", clear_on_submit=True):
    tanggal = st.date_input("Tanggal")
    tipe = st.selectbox("Tipe Transaksi", ["Pengeluaran", "Pemasukan"])
    kategori = st.selectbox(
        "Kategori",
        ["Makanan & Minuman", "Transportasi", "Belanja", "Tagihan", "Gaji", "Lainnya"]
    )
    jumlah = st.number_input("Jumlah (Rp)", min_value=0, step=1000)
    keterangan = st.text_input("Keterangan Singkat")
    
    submitted = st.form_submit_button("Simpan Transaksi")

    if submitted:
        if jumlah > 0:
            # Buat data baru
            new_data = pd.DataFrame([{
                "Tanggal": tanggal,
                "Kategori": kategori,
                "Tipe": tipe,
                "Jumlah (Rp)": jumlah,
                "Keterangan": keterangan
            }])
            
            # Tambahkan ke dataframe di session state
            st.session_state.transactions = pd.concat(
                [st.session_state.transactions, new_data], ignore_index=True
            )
            st.sidebar.success("Transaksi berhasil ditambahkan!")
        else:
            st.sidebar.error("Jumlah transaksi harus lebih dari 0!")

# --- HALAMAN UTAMA: METRIK RINGKASAN ---
df = st.session_state.transactions

# Hitung total pengeluaran & pemasukan
total_pemasukan = df[df["Tipe"] == "Pemasukan"]["Jumlah (Rp)"].sum()
total_pengeluaran = df[df["Tipe"] == "Pengeluaran"]["Jumlah (Rp)"].sum()
saldo_akhir = total_pemasukan - total_pengeluaran

# Tampilkan ringkasan angka dalam 3 kolom
col1, col2, col3 = st.columns(3)
col1.metric("Total Pemasukan", f"Rp {total_pemasukan:,.0f}")
col2.metric("Total Pengeluaran", f"Rp {total_pengeluaran:,.0f}")
col3.metric("Saldo Akhir", f"Rp {saldo_akhir:,.0f}")

st.divider()

# --- GRAFIK & TABEL DATA ---
if not df.empty:
    st.subheader("📊 Analisis Pengeluaran per Kategori")
    
    # Filter khusus pengeluaran untuk grafik
    df_pengeluaran = df[df["Tipe"] == "Pengeluaran"]
    
    if not df_pengeluaran.empty:
        chart_data = df_pengeluaran.groupby("Kategori")["Jumlah (Rp)"].sum()
        st.bar_chart(chart_data)
    else:
        st.info("Belum ada data pengeluaran untuk ditampilkan di grafik.")

    st.subheader("📋 Riwayat Transaksi")
    st.dataframe(df, use_container_width=True)

    # Tombol hapus semua data
    if st.button("Hapus Semua Data"):
        st.session_state.transactions = pd.DataFrame(
            columns=["Tanggal", "Kategori", "Tipe", "Jumlah (Rp)", "Keterangan"]
        )
        st.rerun()
else:
    st.info("Belum ada transaksi. Silakan masukkan data transaksi melalui menu di sebelah kiri (sidebar).")