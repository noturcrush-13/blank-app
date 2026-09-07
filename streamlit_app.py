import streamlit as st
import pandas as pd
import numpy as np

# Judul Aplikasi
st.title("🚀 Aplikasi Streamlit Pertama Saya")

# Header dan Teks
st.header("Selamat Datang!")
st.write("Aplikasi interaktif sederhana yang siap didaftarkan/dideploy ke internet.")

# Sidebar untuk Input User
st.sidebar.header("Pengaturan User")
nama = st.sidebar.text_input("Masukkan Nama Anda:", "Pengunjung")
jumlah_data = st.sidebar.slider("Pilih Jumlah Data:", min_value=10, max_value=100, value=50)

# Menyapa User
st.subheader(f"Halo, {nama}!")

# Membuat Data Acak
chart_data = pd.DataFrame(
    np.random.randn(jumlah_data, 2),
    columns=['Nilai A', 'Nilai B']
)

# Menampilkan Grafik Line Chart
st.subheader("Grafik Data Interaktif")
st.line_chart(chart_data)

# Menampilkan Tabel Data
with st.expander("Lihat Detail Data"):
    st.dataframe(chart_data)

# Tombol Interaktif
if st.button("Klik Saya!"):
    st.balloons()
    st.success("Terima kasih sudah mengklik tombol ini!")