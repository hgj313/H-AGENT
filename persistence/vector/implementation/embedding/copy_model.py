import shutil
import os
from pathlib import Path

def copy_model_to_project():
    source_dir = Path(os.path.expanduser("~/.cache/modelscope/hub/models/BAAI/bge-m3"))
    target_dir = Path(__file__).parent / "models" / "bge-m3"
    
    if not source_dir.exists():
        print(f"源目录不存在: {source_dir}")
        return False
    
    if target_dir.exists():
        print(f"目标目录已存在，将删除后重新复制: {target_dir}")
        shutil.rmtree(target_dir)
    
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"正在复制模型从 {source_dir} 到 {target_dir}...")
    shutil.copytree(source_dir, target_dir)
    print("模型复制完成！")
    
    return True

if __name__ == "__main__":
    copy_model_to_project()