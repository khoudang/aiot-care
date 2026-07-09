#!/bin/bash

echo "========================================="
echo "  AIOT CARE STATION - AUTO UPDATE SCRIPT "
echo "========================================="

echo "[1/3] Kéo code mới nhất từ GitHub..."
git pull origin main

echo ""
echo "[2/3] Nạp tài liệu y khoa (Cập nhật não AI)..."
# Kích hoạt môi trường ảo (tùy thuộc vào tên môi trường của bạn)
if [ -d "venv311" ]; then
    source venv311/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi
python ingest_medical_docs.py

echo ""
echo "[3/3] Khởi động lại hệ thống..."
sudo systemctl restart aiot-care

echo ""
echo "========================================="
echo "       CẬP NHẬT THÀNH CÔNG!              "
echo "========================================="
