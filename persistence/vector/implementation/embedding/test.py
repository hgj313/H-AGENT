import os
from dotenv import load_dotenv
load_dotenv()
from .factory import EmbedderFactory
model_path = os.getenv("BGE_M3_MODEL_PATH")

embeddings = EmbedderFactory.create("bge-m3", model_name_or_path=model_path)
print("=="*25)
print(embeddings.embed_documents(["你好", "你好吗"]))
