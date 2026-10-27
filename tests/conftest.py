"""Chạy test bằng CSDL trong bộ nhớ, không đụng tới instance/kpi.db."""
import os
import sys

os.environ["FLASK_ENV"] = "testing"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
