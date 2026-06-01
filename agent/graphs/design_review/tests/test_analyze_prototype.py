import os
import logging
import sys
from langchain.messages import HumanMessage
from langchain.agents import create_agent
from infrastructure import UploadService,DownloadService
from oss.base import  OSSConfig,PublicURLRequest,PublicURLResult
from oss.di import OSSClient, OSSConfig,OSSRegistry
from dotenv import load_dotenv
load_dotenv()
from agent.graphs.design_review.tools.analyze_prototype.analyze_prototype import analyze_prototype
from agent.graphs.design_review.design_review_graph import create_design_review_graph
from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "test_analyze_prototype.log")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

oss_config = OSSConfig(
    access_key_id=os.getenv("OSS_ACCESS_KEY_ID"),
    access_key_secret=os.getenv("OSS_ACCESS_KEY_SECRET"),
    endpoint=os.getenv("OSS_ENDPOINT"),
    bucket=os.getenv("OSS_BUCKET"),
    region=os.getenv("OSS_REGION"),
)

oss_register = OSSRegistry.get_instance()
oss_client = oss_register.register_from_config(oss_config)
upload_service = UploadService()
params = {
    "file_path": "C:\HGJ-T\H-AGENT\maqima.jpeg",
    "object_name": "测试/玛琪玛.jpeg",
}
upload_result = upload_service.upload(**params)
image_url = upload_service._oss.get_public_url(PublicURLRequest(object_name="测试/玛琪玛.jpeg"))
llm_minimax = MinimaxReasoningModelProvider("MiniMax-M2.7").get_model()
graph = create_design_review_graph(llm_minimax)
messages = [HumanMessage(content=f"请读取文件: test_data\测试文档.md , 并查看图片: {image_url.url}，并假装你就是图片中的人物，那你是我的谁？")]

logger.info("分析原型")
result = graph.invoke({"messages": messages})

print("="*50)
print("===== 最终结果 ===")
for message in result['messages']:
    # if hasattr(message, 'tool_calls'):
    #     tool_calls = message.tool_calls[0]
    #     print(tool_calls['name'])
    #     print()
    #     print(tool_calls['args'])
    #     print("="*50)
    #     print("\n")
    # else:
        print(type(message).__name__)
        print("-"*50)
        print(message)
        print("+"*50)
        print("\n")
    # print("="*50)
    # print("\n")
print(result.get("llm_calls"))
