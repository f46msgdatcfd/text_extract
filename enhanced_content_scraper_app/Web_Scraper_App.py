import streamlit as st
import pandas as pd
import tempfile
from pathlib import Path
from Enhanced_Web_Scraper import scrape_from_excel, set_file_prefix, scrape_multiple_urls

st.set_page_config(page_title="网页爬虫助手", layout="wide")
st.title("🌐 高鲁棒性网页爬虫系统")

st.markdown("""
欢迎使用Winter为您构建的新闻text内容爬虫助手。
- 上传包含 URL 的 Excel 或 CSV 文件
- 选择 URL 所在列
- 一键启动爬虫任务
- 下载 JSON、Excel、CSV 结果 + 日志文件
- 任何疑问，请联系Winter咨询
""")

uploaded_file = st.file_uploader("📁 上传 Excel / CSV 文件", type=["xlsx", "csv"])

if uploaded_file:
    suffix = ".csv" if uploaded_file.name.endswith(".csv") else ".xlsx"
    temp_path = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path.write(uploaded_file.getvalue())
    temp_path.flush()
    filename_prefix = Path(uploaded_file.name).stem

    try:
        if suffix == ".csv":
            df_preview = pd.read_csv(temp_path.name)
        else:
            df_preview = pd.read_excel(temp_path.name)

        st.subheader("📊 文件预览")
        st.dataframe(df_preview.head())
        url_column = st.selectbox("🔗 选择 URL 所在列", df_preview.columns.tolist())

        if st.button("🚀 启动爬虫任务"):
            with st.spinner("正在抓取网页内容，请稍候..."):
                set_file_prefix(filename_prefix)
                urls = df_preview[url_column].dropna().tolist()
                results = scrape_multiple_urls(urls, output_prefix=filename_prefix)

                # 保存 CSV
                output_dir = Path(f"output_{filename_prefix}")
                csv_path = output_dir / f"{filename_prefix}.csv"
                pd.DataFrame(results).to_csv(csv_path, index=False, encoding="utf-8-sig")

                st.session_state["output_dir"] = output_dir
                st.session_state["prefix"] = filename_prefix

        # ✅ 下载按钮始终存在
        if "output_dir" in st.session_state and "prefix" in st.session_state:
            output_dir = st.session_state["output_dir"]
            filename_prefix = st.session_state["prefix"]

            json_path = output_dir / f"{filename_prefix}.json"
            excel_path = output_dir / f"{filename_prefix}.xlsx"
            csv_path = output_dir / f"{filename_prefix}.csv"
            log_path = output_dir / "failed_urls.log"
            screenshot_dir = f"screenshots_{filename_prefix}"

            st.success("✅ 爬取完成！")

            if json_path.exists():
                st.download_button("📥 下载 JSON 文件", open(json_path, "rb"), file_name=json_path.name)
            if excel_path.exists():
                st.download_button("📥 下载 Excel 文件", open(excel_path, "rb"), file_name=excel_path.name)
            if csv_path.exists():
                st.download_button("📥 下载 CSV 文件", open(csv_path, "rb"), file_name=csv_path.name)
            if log_path.exists():
                st.download_button("🪵 下载失败日志", open(log_path, "rb"), file_name=log_path.name)

            st.info(f"📸 所有失败截图保存在 `{screenshot_dir}` 文件夹中。")

    except Exception as e:
        st.error(f"❌ 文件处理失败: {e}")

