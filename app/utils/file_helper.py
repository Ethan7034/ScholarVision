import os
import shutil
from fastapi import UploadFile

def save_upload_file(upload_file: UploadFile, destination: str) -> str:
    with open(destination, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return destination

def remove_file(file_path: str):
    if os.path.exists(file_path):
        os.remove(file_path)