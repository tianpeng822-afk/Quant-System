import os
import sys
import subprocess

def main():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    script_path = os.path.join(root_dir, "web", "0_首页.py")
    
    print("========================================")
    print("  Starting Streamlit Web Panel...")
    print("========================================")
    print("DO NOT CLOSE THIS WINDOW.")
    
    subprocess.run([sys.executable, "-m", "streamlit", "run", script_path], cwd=root_dir)

if __name__ == "__main__":
    main()
