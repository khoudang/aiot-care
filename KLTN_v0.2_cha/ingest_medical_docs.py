from medical_rag import reset_index, ingest_documents


if __name__ == "__main__":
    print("Đang xóa index cũ...")
    reset_index()

    print("Đang nạp tài liệu trong thư mục medical_docs...")
    result = ingest_documents()

    print("Hoàn tất.")
    print(f"Tổng số đoạn đã index: {result['total_chunks']}")
    for filename, count in result["files"].items():
        print(f"- {filename}: {count} đoạn")
