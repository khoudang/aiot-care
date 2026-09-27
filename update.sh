#!/bin/bash

echo "========================================="
echo "  AIOT CARE STATION - AUTO UPDATE SCRIPT "
echo "========================================="

echo "[1/2] Kéo code mới nhất từ GitHub..."
git pull origin main

echo ""
echo "[2/2] Khởi động lại hệ thống..."
sudo systemctl restart aiot-care

echo ""
echo "========================================="
echo "       CẬP NHẬT THÀNH CÔNG!              "
echo "========================================="
